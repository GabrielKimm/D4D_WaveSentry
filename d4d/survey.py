"""RF-region scheduling and evidence accounting, independent of radio/UI.

Record IDs are frequency-region observation IDs, never transmitter identities.
Power is relative, uncalibrated, and compared only within a conditions epoch.
"""
from datetime import datetime, timezone
import numpy as np
from scipy.ndimage import percentile_filter


def utc_at(monotonic, origin_mono, origin_utc):
    return datetime.fromtimestamp(origin_utc + monotonic - origin_mono, timezone.utc).isoformat()


def quality_flags(quality, clipped_pct=0):
    flags = []
    if quality.get("overruns", 0):
        flags.append("device_overrun")
    if quality.get("host_dropped_transfers", 0):
        flags.append("host_dropped_transfers")
    if quality.get("device_error", 0):
        flags.append("device_error")
    if clipped_pct > 0.1:
        flags.append("adc_clipping")
    return flags


def find_candidates(power, low, threshold=6, previous=None):
    """1 MHz tiles: local contrast + same-bin change; no protocol decisions.

    Split broad activity into <=12 MHz cores to leave margins in 20 MHz IQ.
    Missing bins remain unknown. No power threshold asserts RF absence.
    """
    power = np.asarray(power)
    seen = np.isfinite(power)
    if not seen.any():
        return []
    fill = np.where(seen, power, np.median(power[seen]))
    floor = percentile_filter(fill, percentile=20, size=61, mode="nearest")
    contrast = np.maximum(0, power - floor)
    change = np.zeros_like(power)
    if previous is not None and len(previous) == len(power):
        comparable = seen & np.isfinite(previous)
        change[comparable] = np.maximum(0, power[comparable] - previous[comparable])
    active = seen & ((contrast >= threshold) | (change >= threshold))
    # Bridge one quiet tile, never an unobserved tile.
    if len(active) > 2:
        active[1:-1] |= active[:-2] & active[2:] & seen[1:-1]
    edges = np.diff(np.r_[False, active, False].astype(int))
    candidates = []
    for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        count = max(1, int(np.ceil((end - start) / 12)))
        boundaries = np.linspace(start, end, count + 1).astype(int)
        for a, b in zip(boundaries[:-1], boundaries[1:]):
            candidates.append(dict(low_mhz=float(low + a), high_mhz=float(low + b),
                center_mhz=float(low + (a + b) / 2),
                contrast_db=float(np.max(contrast[a:b])), change_db=float(np.max(change[a:b])),
                peak_db=float(np.max(power[a:b])),
                priority=float(np.max(contrast[a:b]) + 0.5 * np.max(change[a:b]) + min(b - a, 10)),
                reason="power_contrast_or_change"))
    return sorted(candidates, key=lambda c: c["priority"], reverse=True)


class Scheduler:
    """Bounded queue; rotate RF sectors, interest bands, and a blind probe.

    Stable high-power regions cool down through the age term. Model scores may
    prioritize a revisit but cannot monopolize all slots. One cycle ends after
    the configured count or a two-second zoom budget (whichever comes first).
    """
    def __init__(self, low, high, slots=4):
        self.low, self.high, self.slots = low, high, slots
        self.visited = {}
        self.hits = {}
        self.hit_times = {}
        self.refinements = []
        self.pool = {}
        self.sector = 0
        self.round = 0
        self.explore = low + min(8, (high - low) / 2)

    @staticmethod
    def key(candidate):
        return round(candidate["center_mhz"] / 4)

    def plan(self, candidates, now):
        self.hits = {k: v for k, v in self.hits.items() if now - self.hit_times.get(k, -1e12) <= 4}
        # Retain short-lived candidates for 10s; losing contrast on the next sweep
        # must not silently cancel a pending inspection. This is not persistence evidence.
        unique = {}
        for c in candidates:
            unique.setdefault(self.key(c), c)
        for key, c in unique.items():
            self.pool[key] = dict(c, coarse_last_seen=now)
        self.pool = {k: c for k, c in self.pool.items() if now - c["coarse_last_seen"] <= 10}
        if len(self.pool) > 512:
            self.pool = dict(sorted(self.pool.items(), key=lambda item: item[1]["coarse_last_seen"], reverse=True)[:512])
        candidates = list(self.pool.values())
        chosen = []
        rest = []
        if candidates:
            # Rotating 1GHz sectors prevents stronger 2.4GHz activity starving 5GHz.
            sectors = max(1, int(np.ceil((self.high - self.low) / 1000)))
            sector_candidates = []
            for _ in range(sectors):
                a = self.low + self.sector * 1000
                self.sector = (self.sector + 1) % sectors
                sector_candidates = [c for c in candidates if a <= c["center_mhz"] < a + 1000]
                if sector_candidates:
                    break
            oldest = min(sector_candidates, key=lambda c: self.visited.get(self.key(c), -1e12))
            chosen.append(dict(oldest, reason="fair_revisit"))
            rest = sorted(candidates, key=lambda c: c["priority"]
                + min(40, max(0, now - self.visited.get(self.key(c), now - 20)))
                + self.hits.get(self.key(c), 0) * (12 if 2400 <= c["center_mhz"] <= 2500 else 2), reverse=True)
        exploration = dict(center_mhz=self.explore, low_mhz=max(self.low, self.explore - 8),
            high_mhz=min(self.high, self.explore + 8), priority=0, contrast_db=0,
            change_db=0, peak_db=None, reason="blind_probe_no_power_gate")
        # Second slot ensures budget exhaustion cannot starve blind exploration.
        chosen.insert(min(1, len(chosen)), exploration)
        # User's 2.4/5GHz auto-hopping experiment gets explicit opportunities.
        # Empty interest bands fall back to ranked general RF candidates.
        bands = [(2400, 2500), (5000, 6000)]
        if self.round % 2:
            bands.reverse()
        self.round += 1
        for a, b in bands:
            if len(chosen) >= self.slots:
                break
            eligible = [c for c in rest if a <= c["center_mhz"] < b
                        and all(abs(c["center_mhz"] - x["center_mhz"]) >= 6 for x in chosen)]
            if eligible:
                chosen.append(dict(eligible[0], reason="priority_interest_band"))
        # At most one targeted recenter, every other round, preserving fair/blind slots
        # and the 5GHz opportunity. A pending recenter is never followed indefinitely.
        self.refinements = [(until, c) for until, c in self.refinements if until >= now]
        if self.slots >= 3 and self.refinements and self.round % 2 == 1:
            _, refinement = self.refinements.pop(0)
            if len(chosen) < self.slots:
                chosen.append(refinement)
            else:
                chosen[-1] = refinement
        for c in rest:
            if len(chosen) >= self.slots:
                break
            if all(abs(c["center_mhz"] - x["center_mhz"]) >= 6 for x in chosen):
                chosen.append(c)
        return chosen[:self.slots]

    def refine(self, candidate, boxes, now):
        if candidate["reason"] == "edge_recenter":
            return
        edges = [b for b in boxes if b["class"] == "drone" and b["edge_truncated"]
                 and b["confidence"] >= 0.35 and 1 < b["bandwidth_mhz"] < 16]
        if not edges:
            return
        box = max(edges, key=lambda b: b["confidence"])
        center = (box["low_mhz"] + box["high_mhz"]) / 2
        if self.low <= center <= self.high and abs(center - candidate["center_mhz"]) > 1:
            c = dict(candidate, center_mhz=center, low_mhz=box["low_mhz"],
                     high_mhz=box["high_mhz"], reason="edge_recenter")
            if all(abs(center - old["center_mhz"]) > 4 for _, old in self.refinements):
                self.refinements.append((now + 10, c))
                self.refinements = self.refinements[-4:]

    def complete(self, candidate, now, score):
        self.visited[self.key(candidate)] = now
        self.hits[self.key(candidate)] = score
        self.hit_times[self.key(candidate)] = now
        if candidate["reason"] == "blind_probe_no_power_gate":
            self.explore += 16
            if self.explore >= self.high:
                self.explore = self.low + min(8, (self.high - self.low) / 2)


def survey_boxes(boxes, center_mhz, low, high, ranges=None):
    """Remap from the fixed model coordinates and preserve every raw class score."""
    result = []
    for original in boxes:
        box = dict(original)
        _, y0, _, y1 = box["xyxy"]
        box["low_mhz"] = center_mhz + (0.5 - y1 / 640) * 20
        box["high_mhz"] = center_mhz + (0.5 - y0 / 640) * 20
        box["bandwidth_mhz"] = box["high_mhz"] - box["low_mhz"]
        edge = y0 < 32 or y1 > 608
        in_scope = any(a <= box["low_mhz"] < box["high_mhz"] <= b for a, b in (ranges or [(low, high)]))
        box.update(in_target=box["class"] == "drone" and not edge and in_scope,
            target_iou=None, edge_truncated=edge,
            gate_reason="edge_truncated" if edge else "outside_survey_scope" if not in_scope else "morphology_only",
            protocol_verified=False, device_identity=None,
            model_domain="limited_2.4GHz_evidence" if 2400 <= box["low_mhz"] < box["high_mhz"] <= 2500 else "unvalidated_frequency_domain")
        result.append(box)
    return result


class Ledger:
    def __init__(self, epoch, origin_mono, origin_utc):
        self.epoch, self.origin_mono, self.origin_utc = epoch, origin_mono, origin_utc
        self.records = {}
        self.counter = 0
        self.archived = 0

    def observe(self, candidate, frames, now, conditions):
        center = candidate["center_mhz"]
        matches = [r for r in self.records.values() if abs(r["center_mhz"] - center) <= 3
                   and now - r["last_mono"] < 60 and r["conditions"] == conditions]
        row = min(matches, key=lambda r: abs(r["center_mhz"] - center)) if matches else None
        if row is None:
            self.counter += 1
            row = dict(id=f"OBS-{self.counter:05d}", center_mhz=center,
                low_mhz=candidate["low_mhz"], high_mhz=candidate["high_mhz"],
                first_utc=utc_at(frames[0]["stamp"] - 0.02, self.origin_mono, self.origin_utc),
                conditions=conditions, observed_seconds=0.0, valid_seconds=0.0,
                visits=0, analyzed_frames=0, gap_seconds=0.0, last_mono=frames[0]["stamp"] - 0.02,
                power_dbfs_min=None, power_dbfs_max=None, power_delta_db=None,
                device_identity=None, protocol_verified=False)
            self.records[row["id"]] = row
        start, end = frames[0]["stamp"] - 0.02, frames[-1]["stamp"]
        # Delivery timestamps are approximate; exact duration comes from sample count.
        row["gap_seconds"] += max(0, start - row["last_mono"])
        row["last_gap_seconds"] = max(0, start - row["last_mono"])
        row["last_mono"] = end
        row["last_center_mhz"] = center
        row["low_mhz"], row["high_mhz"] = candidate["low_mhz"], candidate["high_mhz"]
        row["last_utc"] = utc_at(end, self.origin_mono, self.origin_utc)
        row["observed_seconds"] += len(frames) * 0.02
        valid = [f for f in frames if not f["quality_flags"]]
        row["valid_seconds"] += len(valid) * 0.02
        row["analyzed_frames"] += len(frames)
        row["visits"] += 1
        row["quality_flags"] = sorted({flag for f in frames for flag in f["quality_flags"]})
        hits = [max((b["confidence"] for b in f["boxes"] if b["in_target"]), default=0) for f in valid]
        row["drone_score"] = max(hits, default=0)
        row["drone_hit_frames"] = sum(score > 0 for score in hits)
        row["repeated_drone_shape"] = row["drone_hit_frames"] >= 2
        classes = sorted({b["class"] for f in valid for b in f["boxes"] if b["gate_reason"] == "morphology_only"})
        row["class_shapes"] = classes
        row["assessment"] = ("판정 보류 · 입력 품질" if row["quality_flags"] else
            "드론 유사 형태 · 반복" if row["repeated_drone_shape"] else
            "드론 유사 형태 · 단일" if row["drone_score"] else
            "/".join(classes) + " 유사 형태" if classes else "분류 근거 부족")
        row["model_domain"] = "2.4 GHz 제한 검증" if 2400 <= center <= 2500 else "이 주파수의 모델 성능 미검증"
        row["basis"] = dict(selection=candidate["reason"], contrast_db=candidate["contrast_db"],
            change_db=candidate["change_db"], model="model_02a_picked", rule="2 valid 20ms frames within this visit",
            uncertainty="형태 분류만 수행; 프로토콜/송신기/지속 존재 여부 미확인")
        row["power_delta_db"] = None
        if valid:
            powers = [f["signal"]["rms_dbfs"] for f in valid]
            power_condition = f"{conditions}/FC{center:.6f}"
            comparable = row.get("power_condition") == power_condition
            prior = row.get("last_power_dbfs") if comparable else None
            if not comparable:
                row["power_dbfs_min"] = row["power_dbfs_max"] = None
            row["power_condition"] = power_condition
            row["last_power_dbfs"] = float(np.mean(powers))
            row["power_delta_db"] = None if prior is None else row["last_power_dbfs"] - prior
            row["power_dbfs_min"] = min(powers + ([row["power_dbfs_min"]] if row["power_dbfs_min"] is not None else []))
            row["power_dbfs_max"] = max(powers + ([row["power_dbfs_max"]] if row["power_dbfs_max"] is not None else []))
        # Stable memory cap; full visit history is independently appended to JSONL.
        if len(self.records) > 512:
            oldest = min(self.records, key=lambda k: self.records[k]["last_mono"])
            del self.records[oldest]
            self.archived += 1
        return dict(row, current_center_mhz=center)

    def view(self, now):
        return [dict(r, since_last_seconds=max(0, now - r["last_mono"]),
                     observation_state="관측 공백 · 현재 상태 미확인")
                for r in sorted(self.records.values(), key=lambda r: r["last_mono"], reverse=True)]
