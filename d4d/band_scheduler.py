"""Antenna-aware scheduling with bounded latency and power-independent probes."""
import math
from .evidence import interval_iou


class BandScheduler:
    def __init__(self, ranges, slots=4):
        self.ranges = tuple(ranges)
        self.slots = slots
        self.round = 0
        self.pool, self.visited, self.hits = {}, {}, {}
        self.evidence = []
        self.grids, self.cursors = [], []
        for a, b in self.ranges:
            margin = min(9, (b - a) / 2)
            start, end = a + margin, b - margin
            n = max(1, math.ceil((end - start) / 8))
            self.grids.append([start + (end - start) * i / n for i in range(n + 1)] if end > start else [start])
            self.cursors.append(0)

    @staticmethod
    def key(c):
        return round(c['center_mhz'] / 2)

    @property
    def explore(self):
        return self.grids[0][self.cursors[0]]

    def bonus(self, c, now):
        return max((min(8, 4 * r['score']) for r in self.evidence
                    if now - r['last_seen'] <= 6 and interval_iou(
                        (c['low_mhz'], c['high_mhz']), (r['low_mhz'], r['high_mhz'])) >= .35), default=0)

    def recent_hit(self, c, now):
        score, stamp = self.hits.get(self.key(c), (0, -1e12))
        return score if now - stamp <= 4 else 0

    def plan(self, candidates, now):
        for c in candidates:
            span = next(((a, b) for a, b in self.ranges if a <= c['center_mhz'] < b), None)
            if span is None:
                continue
            a, b = span
            margin = min(9, (b - a) / 2)
            c = dict(c, center_mhz=max(a + margin, min(b - margin, c['center_mhz'])), coarse_last_seen=now)
            self.pool[self.key(c)] = c
        self.pool = {k: c for k, c in self.pool.items() if now - c['coarse_last_seen'] <= 3}
        self.hits = {k: v for k, v in self.hits.items() if now - v[1] <= 4}
        self.visited = {k: v for k, v in self.visited.items() if now - v <= 120}
        if len(self.pool) > 512:
            self.pool = dict(sorted(self.pool.items(), key=lambda kv: kv[1]['coarse_last_seen'], reverse=True)[:512])
        order = list(range(len(self.ranges)))
        if self.round % 2:
            order.reverse()
        self.round += 1
        chosen = []
        for i in order:
            a, b = self.ranges[i]
            center = self.grids[i][self.cursors[i]]
            chosen.append(dict(center_mhz=center, low_mhz=max(a, center - 9), high_mhz=min(b, center + 9),
                priority=0, contrast_db=0, change_db=0, peak_db=None, reason='blind_probe_no_power_gate', probe_band=i))
        for i in order:
            if len(chosen) >= self.slots:
                break
            a, b = self.ranges[i]
            # A coherent two-window observation warrants a short, bounded recheck.
            # Do not renew this deadline from scheduling: only new model evidence does.
            recent = []
            for region in self.evidence:
                center = (region['low_mhz'] + region['high_mhz']) / 2
                if ('paired_partial' not in region.get('evidence_kinds', [])
                        or not a + 15 <= center <= b - 15
                        or now - region['last_seen'] > 6):
                    continue
                candidate = dict(center_mhz=center, low_mhz=region['low_mhz'], high_mhz=region['high_mhz'],
                    priority=0, contrast_db=0, change_db=0, peak_db=None,
                    reason='evidence_revisit', evidence_region_id=region['id'],
                    evidence_last_seen=region['last_seen'])
                if (now - self.visited.get(self.key(candidate), -1e12) >= 1
                        and all(abs(center - old['center_mhz']) >= 4 for old in chosen)):
                    recent.append((region['score'], candidate))
            if recent:
                chosen.append(max(recent, key=lambda item: item[0])[1])
                continue
            eligible = [c for c in self.pool.values() if a <= c['center_mhz'] < b
                        and all(abs(c['center_mhz'] - old['center_mhz']) >= 4 for old in chosen)]
            if not eligible:
                continue
            def rank(c):
                wait = min(12, max(0, now - self.visited.get(self.key(c), now - 12)))
                return min(c['priority'], 35) + wait * 2 + self.bonus(c, now)
            candidate = max(eligible, key=rank)
            chosen.append(dict(candidate, reason='priority_interest_band'))
        # Start with a fresh power candidate, retaining one blind probe in EACH band.
        if len(chosen) > len(self.ranges):
            first = next((i for i,c in enumerate(chosen) if c['reason']=='evidence_revisit'), len(self.ranges))
            chosen.insert(0, chosen.pop(first))
        return chosen[:self.slots]

    def complete(self, c, now, score):
        self.visited[self.key(c)] = now
        self.hits[self.key(c)] = (score, now)
        if c['reason'] == 'blind_probe_no_power_gate':
            i = c['probe_band']
            self.cursors[i] = (self.cursors[i] + 1) % len(self.grids[i])
