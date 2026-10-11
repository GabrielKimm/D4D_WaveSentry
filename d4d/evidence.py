"""Decaying evidence for RF regions, never transmitter IDs or probabilities."""
def interval_iou(a, b):
    overlap = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    return overlap / max(a[1] - a[0] + b[1] - b[0] - overlap, 1e-6)


class EvidenceBank:
    half_life = 8.0
    lifetime = 30.0
    enter_score = 1.6
    leave_score = 0.8

    def __init__(self):
        self.tracks = {}
        self.counter = 0

    def _view(self, track, now):
        points = [p for p in track['points'].values() if now - p['stamp'] <= self.lifetime]
        score = min(4.0, sum(p['weight'] * 2 ** (-max(0, now - p['stamp']) / self.half_life) for p in points))
        age = max(0.0, now - track['last_seen'])
        threshold = self.leave_score if track['supported'] else self.enter_score
        supported = len(points) >= 3 and score >= threshold and age <= 6
        return dict(id=track['id'], low_mhz=track['band'][0], high_mhz=track['band'][1],
                    score=score, episodes=len(points), last_seen=track['last_seen'], age_seconds=age,
                    supported=supported, conditions=track['conditions'],
                    state='누적 드론 유사 근거' if supported else '근거 노후 · 현재 미확인' if age > 6 else '근거 누적 중',
                    evidence_kinds=sorted(track.get('kinds',{'single_window'})),
                    probability=False, device_identity=None, protocol_verified=False)

    def view(self, now):
        return [self._view(t, now) for t in self.tracks.values() if now - t['last_seen'] <= self.lifetime]

    def observe(self, frames, now, conditions, episode):
        self.tracks = {k: t for k, t in self.tracks.items() if now - t['last_seen'] <= self.lifetime}
        groups = []
        for frame_index, frame in enumerate(frames):
            if frame['quality_flags']:
                continue
            for box in sorted(frame['boxes'], key=lambda b: b['confidence'], reverse=True):
                if box['class'] != 'drone' or not box['in_target']:
                    continue
                band = (box['low_mhz'], box['high_mhz'])
                if any(b['class'] != 'drone' and b['confidence'] >= box['confidence']
                       and interval_iou(band, (b['low_mhz'], b['high_mhz'])) >= .5 for b in frame['boxes']):
                    continue
                group = next((g for g in groups if interval_iou(g['band'], band) >= .35), None)
                if group is None:
                    group = dict(band=band, confidence=0, frames=set(), stamp=frame['stamp'])
                    groups.append(group)
                group['frames'].add(frame_index)
                if box['confidence'] > group['confidence']:
                    group['confidence'], group['band'] = box['confidence'], band
                group['stamp'] = max(group['stamp'], frame['stamp'])
        return self._accumulate(groups, now, conditions, episode)

    def observe_pair(self, pair, now, conditions, episode):
        group = dict(band=(pair['low_mhz'],pair['high_mhz']), confidence=pair['confidence']*.75,
                     frames={0,1},stamp=pair['stamp'],kind='paired_partial')
        return self._accumulate([group],now,conditions,episode)

    def _accumulate(self, groups, now, conditions, episode):
        touched = []
        used = set()
        for group in sorted(groups, key=lambda g: g['confidence'], reverse=True):
            matches = [t for t in self.tracks.values() if t['conditions'] == conditions and t['id'] not in used
                       and interval_iou(t['band'], group['band']) >= .35]
            track = max(matches, key=lambda t: interval_iou(t['band'], group['band'])) if matches else None
            if track is None:
                self.counter += 1
                track = dict(id=f'RF-{self.counter:05d}', band=group['band'], conditions=conditions,
                             points={}, last_seen=group['stamp'], supported=False,kinds=set())
                self.tracks[track['id']] = track
            else:
                # A stale supported state must re-enter at the higher threshold.
                track['supported'] = self._view(track, now)['supported']
            used.add(track['id'])
            track.setdefault('kinds',set()).add(group.get('kind','single_window'))
            # One capped contribution per scheduling episode, including its immediate follow-up.
            weight = min(1.0, group['confidence'] * (1 if len(group['frames']) >= 2 else .8))
            prior = track['points'].get(episode)
            if prior is None or weight > prior['weight']:
                track['points'][episode] = dict(weight=weight, stamp=group['stamp'])
            track['points'] = {e: p for e, p in track['points'].items() if now - p['stamp'] <= self.lifetime}
            track['last_seen'] = max(track['last_seen'], group['stamp'])
            track['band'] = group['band']
            view = self._view(track, now)
            track['supported'] = view['supported']
            touched.append(view)
        if len(self.tracks) > 512:
            keep = sorted(self.tracks.values(), key=lambda t: t['last_seen'], reverse=True)[:512]
            self.tracks = {t['id']: t for t in keep}
        return touched


def evidence_snapshot(bank, center_mhz, now, conditions):
    rows = [r for r in bank.view(now) if r['conditions'] == conditions
            and max(r['low_mhz'], center_mhz - 9) < min(r['high_mhz'], center_mhz + 9)]
    return max(rows, key=lambda r: r['score']) if rows else None


def confirmation_candidate(candidate, frames, ranges):
    """At most one immediate follow-up; engine reserves global exploration slots."""
    boxes = [b for f in frames if not f['quality_flags'] for b in f['boxes']
             if b['class'] == 'drone' and b['confidence'] >= .35 and 1 < b['bandwidth_mhz'] < 18]
    if not boxes:
        return None
    edges = [b for b in boxes if b['edge_truncated']]
    box = max(edges or [b for b in boxes if b['in_target']], key=lambda b: b['confidence'], default=None)
    if box is None:
        return None
    center = (box['low_mhz'] + box['high_mhz']) / 2 if edges else candidate['center_mhz']
    span = next(((a, b) for a, b in ranges if a <= center < b), None)
    if span is None:
        return None
    a, b = span
    margin = min(9, (b - a) / 2)
    center = max(a + margin, min(b - margin, center))
    if edges and abs(center - candidate['center_mhz']) < 1:
        return None
    return dict(candidate, center_mhz=center, low_mhz=box['low_mhz'], high_mhz=box['high_mhz'],
                reason='immediate_recenter' if edges else 'immediate_confirmation',
                trigger_stamp=frames[-1]['stamp'])


def confirmation_plan(candidate, frames, ranges, channel_mhz):
    if channel_mhz == 10:
        follow = confirmation_candidate(candidate,frames,ranges)
        return [follow] if follow else []
    boxes = [b for f in frames if not f['quality_flags'] for b in f['boxes']
             if b['class']=='drone' and b['confidence']>=.35 and b['edge_truncated'] and b['bandwidth_mhz']>=4]
    if not boxes:
        follow=confirmation_candidate(candidate,frames,ranges)
        return [follow] if follow else []
    center=candidate['center_mhz']
    span=next(((a,b) for a,b in ranges if a<=center<b),None)
    if span is None or span[1]-span[0]<30:
        return []
    a,b=span
    center=max(a+15,min(b-15,center))
    return [dict(candidate,center_mhz=center+offset,reason='immediate_partial_pair',
                 pair_side=side,pair_center_mhz=center,trigger_stamp=frames[-1]['stamp'])
            for side,offset in [('lower',-6),('upper',6)]]


def paired_partial_evidence(visits, expected_width=20):
    """Cross-window consistency, not stitched IQ or a full-band YOLO prediction.

    Need two quality frames on EACH side, complementary clipped edges, shared
    observed frequencies, compatible outer bounds, and <=1s acquisition gap.
    This is a bandwidth hypothesis; it does not prove a transmitter or protocol.
    """
    sides={v['candidate'].get('pair_side'):v for v in visits if v['candidate'].get('pair_side')}
    if 'lower' not in sides or 'upper' not in sides:
        return None
    lo,hi=sides['lower'],sides['upper']
    if abs(hi['frames'][0]['stamp']-lo['frames'][-1]['stamp'])>1:
        return None
    candidates=[]
    for side,v in [('lower',lo),('upper',hi)]:
        groups=[]
        for index,f in enumerate(v['frames']):
            if f['quality_flags']:
                continue
            for b in f['boxes']:
                y0,y1=b['xyxy'][1],b['xyxy'][3]
                complementary=(y0<32 and y1<=608) if side=='lower' else (y1>608 and y0>=32)
                if b['class']!='drone' or b['confidence']<.35 or not complementary:
                    continue
                band=(b['low_mhz'],b['high_mhz'])
                if any(x['class']!='drone' and x['confidence']>=b['confidence'] and
                       interval_iou(band,(x['low_mhz'],x['high_mhz']))>=.5 for x in f['boxes']):
                    continue
                group=next((g for g in groups if interval_iou(g['band'],band)>=.5),None)
                if group is None:
                    group=dict(band=band,confidence=b['confidence'],indices=set())
                    groups.append(group)
                group['indices'].add(index)
                group['confidence']=min(group['confidence'],b['confidence'])
        candidates.append([g for g in groups if len(g['indices'])>=2])
    pairs=[]
    for lower in candidates[0]:
        for upper in candidates[1]:
            band=(lower['band'][0],upper['band'][1])
            width=band[1]-band[0]
            overlap=min(lower['band'][1],upper['band'][1])-max(lower['band'][0],upper['band'][0])
            if .8*expected_width<=width<=1.2*expected_width and overlap>=2:
                pairs.append(dict(low_mhz=band[0],high_mhz=band[1],bandwidth_mhz=width,
                    confidence=min(lower['confidence'],upper['confidence']),stamp=hi['frames'][-1]['stamp'],
                    evidence_kind='paired_partial',simultaneous=False,protocol_verified=False,
                    acquisition_gap_seconds=hi['frames'][0]['stamp']-lo['frames'][-1]['stamp']))
    return max(pairs,key=lambda p:p['confidence']) if pairs else None
