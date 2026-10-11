"""Presentation of existing RF evidence; never a new detector or transmitter count."""
from .evidence import EvidenceBank


FRESH_SECONDS = 6.0  # Existing EvidenceBank freshness policy.
UPDATE_TIMEOUT = 3.0


class SurveyAssessment:
    def __init__(self):
        self.reset()

    def reset(self, ranges=((2400, 2500), (5150, 5890))):
        self.lifecycle = 'IDLE'
        self.ranges = tuple(ranges)
        self.frame = None
        self.last_confirmed = None
        self.raw_candidates = []
        self.band_visits = {}
        self.last_visit = None
        self.error = ''

    def set_lifecycle(self, state, message=''):
        if self.lifecycle in ('STOPPING','STOPPED','ERROR') and state in ('LOADING','READY'):
            return
        mapped = {'LOADING': 'STARTING', 'READY': 'RUNNING'}
        if state in ('LOADING', 'READY', 'STOPPING', 'STOPPED', 'ERROR'):
            self.lifecycle = mapped.get(state, state)
        if state == 'ERROR':
            self.error = message

    def ingest(self, frame):
        if self.lifecycle not in ('STARTING', 'RUNNING'):
            return  # A late queued frame must not resurrect a stopped alarm.
        self.frame = frame
        self.ranges = tuple(tuple(r) for r in frame['survey_ranges'])
        now = frame['generated_mono']
        regions = self.regions()
        confirmed = [r for r in regions if r['supported'] and 0 <= now-r['last_seen'] <= FRESH_SECONDS]
        if confirmed:
            newest = max(confirmed, key=lambda r: r['last_seen'])
            if not self.last_confirmed or newest['last_seen'] >= self.last_confirmed['last_seen']:
                self.last_confirmed = dict(newest)
        self.raw_candidates = [r for r in self.raw_candidates if now-r['last_seen'] <= FRESH_SECONDS]
        zoom = frame.get('zoom')
        if not zoom or frame['visits'] == self.last_visit:
            return
        self.last_visit = frame['visits']
        stamp = zoom.get('observed_mono', zoom['record']['last_mono'])
        good = not zoom['quality_flags']
        for span in self.ranges:
            if span[0] <= zoom['center_mhz'] <= span[1]:
                self.band_visits[span] = dict(stamp=stamp, good=good)
        if good:
            boxes = [b for b in zoom['boxes'] if b['class']=='drone' and b['confidence']>=.35
                     and any(max(a,b['low_mhz']) < min(z,b['high_mhz']) for a,z in self.ranges)]
            if boxes:
                best = max(boxes,key=lambda b:b['confidence'])
                self.raw_candidates.append(dict(low_mhz=best['low_mhz'],high_mhz=best['high_mhz'],
                    last_seen=stamp,confidence=best['confidence']))
                self.raw_candidates = self.raw_candidates[-64:]

    def regions(self):
        # EvidenceBank IDs deduplicate overlapping observation records.
        return list({r['id']:r for r in (self.frame or {}).get('evidence_regions', [])}.values())

    def evaluate(self, now):
        frame = self.frame or {}
        generated = frame.get('generated_mono')
        source_fresh = generated is not None and 0 <= now-generated <= UPDATE_TIMEOUT
        regions = self.regions()
        fresh = [r for r in regions if 0 <= now-r['last_seen'] <= FRESH_SECONDS and r['score']>0]
        active = [r for r in fresh if r['supported']]
        raw = [r for r in self.raw_candidates if 0 <= now-r['last_seen'] <= FRESH_SECONDS]
        quality = []
        for source in (frame.get('sweep'),frame.get('zoom')):
            if source:
                quality.extend(source.get('quality_flags',[]))
        quality = sorted(set(quality))
        last_age = max(0,now-self.last_confirmed['last_seen']) if self.last_confirmed else None
        if self.lifecycle in ('IDLE','STARTING','STOPPING','STOPPED','ERROR'):
            state = self.lifecycle
        elif not frame:
            state = 'STARTING'
        elif not source_fresh:
            state = 'STALE'
        elif quality:
            state = 'QUALITY'
        elif active:
            state = 'DETECTED'
        elif fresh or raw:
            state = 'CANDIDATE'
        elif last_age is not None and last_age <= EvidenceBank.lifetime:
            state = 'GAP'
        elif frame.get('processed',0)==0:
            state = 'STARTING'
        else:
            state = 'NO_EVIDENCE'
        trusted = state in ('DETECTED','CANDIDATE','GAP','NO_EVIDENCE')
        focus = max(active or fresh,key=lambda r:r['score'],default=None) if trusted else None
        candidate = max(raw,key=lambda r:r['confidence'],default=None) if trusted and not focus else None
        focus = focus or candidate
        bands = []
        for span in self.ranges:
            overlaps = lambda r: max(span[0],r['low_mhz']) < min(span[1],r['high_mhz'])
            visit = self.band_visits.get(span)
            band_state = ('HELD' if not trusted else 'DETECTED' if any(overlaps(r) for r in active)
                          else 'CANDIDATE' if any(overlaps(r) for r in fresh+raw)
                          else 'WAITING' if visit is None else 'QUALITY' if not visit['good'] else 'NO_EVIDENCE')
            bands.append(dict(span=span,state=band_state,
                age=max(0,now-visit['stamp']) if visit else None))
        return dict(state=state,active_regions=len(active) if trusted else None,focus=focus,
                    last_detection_age=last_age,bands=bands,quality=quality,error=self.error,
                    source_age=max(0,now-generated) if generated is not None else None,
                    phase=frame.get('phase','WAIT'),processed=frame.get('processed',0),
                    sweep_seconds=(frame.get('sweep') or {}).get('seconds'),
                    score=focus.get('score') if focus else None,
                    episodes=focus.get('episodes',0) if focus else 0,
                    focus_age=max(0,now-focus['last_seen']) if focus else None)
