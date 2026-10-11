"""Coarse sweep -> fair candidate schedule -> settled IQ -> model -> revisit."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from collections import deque
import json
import hashlib
import shutil
import threading
import time
import numpy as np
from PIL import Image
from .config import ROOT
from .dsp import process_iq
from .inference import Detector
from .survey_radio import SurveyRadio
from .survey import Scheduler, Ledger, find_candidates, quality_flags, survey_boxes
from .band_scheduler import BandScheduler
from .evidence import EvidenceBank, evidence_snapshot, confirmation_plan, paired_partial_evidence


class SurveyEngine:
    def __init__(self, settings, mode="survey", on_frame=lambda _: None, on_status=lambda _: None):
        self.settings, self.mode = settings, "survey"
        self.on_frame, self.on_status = on_frame, on_status
        self.stop_event, self.snapshot_event = threading.Event(), threading.Event()
        self.session = None
        self.summary = {}
        self.environment_label = "실측 환경 미확인; 사용자 ground truth와 모델 결과는 별도"

    def stop(self):
        self.stop_event.set()

    def request_snapshot(self):
        self.snapshot_event.set()

    def run(self, seconds=None):
        settings = self.settings
        origin, utc_origin = time.perf_counter(), time.time()
        radio = pool = log = None
        error = None
        cycle = processed = visits = runtime_overruns = host_drops = saved = 0
        repeated = set()
        accumulated = set()
        episode = 0
        evidence_bands = set()
        sweep_times, cycle_times, infer_times = (deque(maxlen=10000) for _ in range(3))
        conditions = f"LNA{settings.lna}/VGA{settings.vga}/AMP0/FS20M/BW20M"
        ledger = Ledger(conditions, origin, utc_origin)
        ranges = settings.survey_ranges
        low, high = ranges[0][0], ranges[-1][1]
        scheduler = (BandScheduler(ranges, settings.survey_zooms) if len(ranges) > 1 else
                     Scheduler(low, high, settings.survey_zooms))
        evidence = EvidenceBank()
        previous = None
        last_zoom = None
        survey_view = None
        radio_info = {}
        def observations(now):
            bank = {e['id']: e for e in evidence.view(now)}
            return [dict(r, evidence=bank.get((r.get('evidence') or {}).get('id')))
                    for r in ledger.view(now)]
        def emit(phase, **extra):
            now = time.perf_counter()
            self.on_frame(dict(mode="survey", phase=phase, elapsed=now - origin,
                generated_mono=now, evidence_regions=evidence.view(now),
                cycle=cycle, processed=processed, visits=visits, total_records=ledger.counter,
                archived_records=ledger.archived, observations=observations(now),
                sweep=survey_view, zoom=last_zoom, survey_low=low, survey_ranges=ranges,
                survey_profile=settings.survey_label, survey_channel_mhz=settings.survey_channel_mhz,
                survey_high=high, next_explore_mhz=scheduler.explore,
                runtime_overruns=runtime_overruns, host_drops=host_drops, **extra))
        def write(kind, data):
            nonlocal log
            if log.tell() > 20_000_000:
                log.close()
                log = (self.session / f"events_{cycle:06d}_{processed:06d}.jsonl").open("w", encoding="utf-8", buffering=1)
            log.write(json.dumps(dict(kind=kind, utc=datetime.now(timezone.utc).isoformat(), **data),
                                 ensure_ascii=False, allow_nan=False) + "\n")
        try:
            self.on_status(dict(state="LOADING", message=settings.survey_label + " 관측 모델 준비 중…"))
            detector = Detector(settings.backend, settings.confidence)
            if self.stop_event.is_set():
                return
            self.on_status(dict(state="READY", message=detector.warning or detector.device_name, backend=detector.backend))
            self.session = ROOT / "output" / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_survey")
            self.session.mkdir(parents=True)
            meta = dict(settings.metadata(), mode="survey", centerFrequencyHz=None,
                targetLowMHz=None, targetHighMHz=None, surveyRangeMHz=[low, high], surveyRangesMHz=ranges,
                algorithmVersion="survey-v3.2-20mhz", antennaElectricalContactMeasured=False,
                targetChannelWidthMHz=settings.survey_channel_mhz, simultaneousUsableBandwidthMHz=18,
                sourceHashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'd4d').glob('*.py')},
                environmentLabel=self.environment_label, startedUtc=datetime.now(timezone.utc).isoformat(),
                hostMonotonicOrigin=origin, unixUtcOrigin=utc_origin,
                backend=detector.backend, protocolVerification=False, deviceIdentification=False,
                timestampBasis="host USB delivery; approximate UTC, not hardware timestamps",
                policy="antenna ranges; blind probe per band; 4/6 frames; 20MHz: one sequential complementary pair/cycle; 2s soft budget; decaying episode evidence",
                evidencePolicy=dict(halfLifeSeconds=evidence.half_life, lifetimeSeconds=evidence.lifetime,
                    enterScore=evidence.enter_score, leaveScore=evidence.leave_score, minEpisodes=3,
                    maxEpisodeWeight=1, scoreIsProbability=False),
                sweepSampleSecondsPerBin=0.0002048, sweepFilterHz=15_000_000, zoomFilterHz=20_000_000,
                limitations="Frequency tuning capability is not equal antenna sensitivity. Model generalization outside controlled 2.4GHz samples is unverified.")
            log = (self.session / "events.jsonl").open("w", encoding="utf-8", buffering=1)
            pool = ThreadPoolExecutor(max_workers=2 if "GPU" in detector.backend else 1)
            radio = SurveyRadio(settings, self.stop_event)
            radio_info = radio.receive()
            meta["radio"] = radio_info
            (self.session / "session.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            running = time.perf_counter()
            while not self.stop_event.is_set() and (seconds is None or time.perf_counter() - running < seconds):
                if shutil.disk_usage(self.session).free < 512_000_000:
                    raise RuntimeError("남은 저장 공간이 512 MB 미만입니다.")
                cycle_start = time.perf_counter()
                cycle += 1
                emit("SWEEP")
                sweep = radio.request("sweep", low=low, high=high, ranges=ranges)
                sweep_times.append(sweep["wall_seconds"])
                runtime_overruns += sweep["quality"]["overruns"]
                host_drops += sweep["quality"]["host_dropped_transfers"]
                flags = quality_flags(sweep["quality"], float(np.max(sweep["clips"])))
                power = sweep["power"]
                candidates = []
                for a, b in ranges:
                    candidates.extend(find_candidates(power[a-low:b-low], a, settings.survey_threshold_db,
                        previous[a-low:b-low] if previous is not None and not flags else None))
                # Degraded sweeps do not create power-based decisions or update baseline.
                if flags:
                    candidates = []
                else:
                    previous = power.copy()
                np.savez_compressed(self.session / f"sweep_{cycle:06d}.npz", power=power,
                    stamps=sweep["stamps"], clips=sweep["clips"], low=low,
                    high=high, ranges=np.array(ranges), quality=json.dumps(sweep["quality"]),
                    sample_seconds_per_bin=sweep["sample_seconds_per_bin"])
                survey_view = dict(low=low, high=high, ranges=ranges,
                    power=power, coverage_pct=sweep["coverage_pct"], seconds=sweep["wall_seconds"],
                    ended=sweep["ended"], candidates=candidates, quality_flags=flags)
                if isinstance(scheduler, BandScheduler):
                    scheduler.evidence = evidence.view(time.perf_counter())
                plan = scheduler.plan(candidates, time.perf_counter())
                write("sweep", dict(cycle=cycle, seconds=sweep["wall_seconds"], coverage_pct=sweep["coverage_pct"],
                    candidate_count=len(candidates), quality=sweep["quality"], quality_flags=flags,
                    candidates=candidates, plan=plan, ranges=ranges, raw_psd_file=f"sweep_{cycle:06d}.npz"))
                zoom_start = time.perf_counter()
                emit("SELECT", queued=len(plan), candidate_count=len(candidates))
                queue = deque(plan)
                followups = 0
                episode_visits = {}
                while queue:
                    if self.stop_event.is_set() or time.perf_counter() - zoom_start > 2.0:
                        break
                    if seconds is not None and time.perf_counter() - running >= seconds:
                        break
                    candidate = queue.popleft()
                    is_followup = candidate['reason'].startswith('immediate_')
                    if not is_followup:
                        episode += 1
                        candidate = dict(candidate, episode=episode)
                    fc = int(candidate["center_mhz"] * 1e6)
                    now = time.perf_counter()
                    recent = (scheduler.recent_hit(candidate, now) if isinstance(scheduler, BandScheduler)
                              else scheduler.hits.get(scheduler.key(candidate), 0))
                    count = 3 if candidate['reason']=='immediate_partial_pair' else 4 if is_followup or not recent else 6
                    emit("ZOOM", active_center_mhz=fc / 1e6, active_reason=candidate["reason"])
                    dwell = radio.request("dwell", center_hz=fc, frames=count)
                    runtime_overruns += dwell["quality"]["overruns"]
                    host_drops += dwell["quality"]["host_dropped_transfers"]
                    # Bounded to eight original 20 ms frames; inference is serialized.
                    futures = [pool.submit(process_iq, raw) for _, raw in dwell["frames"]]
                    frames, images = [], []
                    for (stamp, raw), future in zip(dwell["frames"], futures):
                        if self.stop_event.is_set():
                            raise InterruptedError("Survey cancelled")
                        gray, spectrum, signal = future.result()
                        boxes, infer_ms = detector.predict(gray)
                        boxes = survey_boxes(boxes, fc / 1e6, low, high, ranges)
                        infer_times.append(infer_ms)
                        processed += 1
                        frame_flags = quality_flags(dwell["quality"], signal["clipped_pct"])
                        if signal["rms_dbfs"] < -100:
                            frame_flags.append("flat_input")
                        frames.append(dict(stamp=stamp, boxes=boxes, signal=signal, inference_ms=infer_ms,
                            quality_flags=frame_flags))
                        images.append((gray, spectrum, raw))
                    visits += 1
                    episode_visits.setdefault(candidate['episode'],[]).append(dict(candidate=candidate,frames=frames))
                    pair = (paired_partial_evidence(episode_visits[candidate['episode']], settings.survey_channel_mhz)
                            if candidate.get('pair_side')=='upper' else None)
                    row = ledger.observe(candidate, frames, time.perf_counter(), conditions)
                    touched = evidence.observe(frames, time.perf_counter(), conditions, candidate['episode'])
                    if pair:
                        touched.extend(evidence.observe_pair(pair,time.perf_counter(),conditions,candidate['episode']))
                    row['partial_pair'] = pair
                    if pair:
                        row['assessment'] = '20 MHz 가설 · 부분 창 형태 일치'
                    row['evidence'] = (max(touched, key=lambda e: e['score']) if touched else
                                       evidence_snapshot(evidence, fc / 1e6, time.perf_counter(), conditions))
                    row['evidence_supported'] = any(e['supported'] for e in touched)
                    row['episode'] = candidate['episode']
                    if row['evidence_supported']:
                        row['assessment'] = '누적 드론 유사 근거 · 프로토콜 미확인'
                    row['basis']['temporal'] = 'RF interval IoU >=0.35; max one weight/episode; 8s half-life; >=3 episodes'
                    ledger.records[row['id']].update({k: row[k] for k in ('evidence', 'evidence_supported', 'episode', 'assessment', 'basis', 'partial_pair')})
                    accumulated.update(e['id'] for e in touched if e['supported'])
                    scheduler.complete(candidate, time.perf_counter(), row["drone_score"])
                    # Reserve the remainder for the planned band probes; never chain follow-ups.
                    if not is_followup and not followups and time.perf_counter() - zoom_start < .8:
                        follow = confirmation_plan(candidate, frames, ranges,settings.survey_channel_mhz)
                        if follow:
                            queue.extendleft(reversed(follow))
                            followups += len(follow)
                    if row["repeated_drone_shape"]:
                        repeated.add(row["id"])
                    best = max(range(len(frames)), key=lambda i: max(
                        (b["confidence"] for b in frames[i]["boxes"] if b["class"] == 'drone'), default=0))
                    frame = frames[best]
                    gray, spectrum, raw = images[best]
                    last_zoom = dict(center_mhz=fc / 1e6, record=row, image=gray, spectrum=spectrum,
                        observed_mono=frame['stamp'],
                        boxes=frame["boxes"], signal=frame["signal"], inference_ms=frame["inference_ms"],
                        ended=time.perf_counter(), frames=count, quality_flags=row["quality_flags"],
                        duration_seconds=count * 0.02, capture_seconds=dwell["wall_seconds"])
                    write("visit", dict(cycle=cycle, visit=visits, center_hz=fc, candidate=candidate,
                        observation=row, frames=frames, quality=dwell["quality"],
                        discarded_settling_seconds=dwell["discarded_settling_seconds"],
                        capture_seconds=dwell["wall_seconds"]))
                    raw_hit = any(b['class'] == 'drone' for f in frames for b in f['boxes'])
                    auto_save = raw_hit and (row['visits'] == 1 or is_followup) and saved < 32
                    evidence_band = "2.4GHz" if 2400 <= fc / 1e6 <= 2500 else "5GHz" if 5000 <= fc / 1e6 <= 6000 else None
                    if evidence_band and evidence_band not in evidence_bands:
                        auto_save = True
                        evidence_bands.add(evidence_band)
                    if self.snapshot_event.is_set() or auto_save:
                        self.snapshot_event.clear()
                        folder = self.session / f"snapshot_{visits:06d}_{row['id']}"
                        folder.mkdir()
                        (folder / "frame.cs8").write_bytes(raw)
                        # Preserve every frame of selected visits for later annotation/replay.
                        for index, (_, _, iq) in enumerate(images):
                            (folder / f"input_{index:02d}.cs8").write_bytes(iq)
                        Image.fromarray(gray).save(folder / "model_input.png")
                        snapshot = dict(meta, centerFrequencyHz=fc, durationSeconds=0.02,
                                        observation=row, frame=frame, frames=frames, visit=visits)
                        (folder / "frame.cs8.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
                        saved += 1
                        self.on_status(dict(state="SAVED", message=str(folder)))
                    emit("REVISIT", active_center_mhz=fc / 1e6)
                cycle_times.append(time.perf_counter() - cycle_start)
                write("cycle", dict(cycle=cycle, seconds=cycle_times[-1], visits=visits,
                    model_frames=processed, next_explore_mhz=scheduler.explore))
        except InterruptedError:
            pass
        except Exception as exc:
            error = str(exc)
            self.on_status(dict(state="ERROR", message=error))
        finally:
            if radio:
                radio.close()
            if pool:
                pool.shutdown(wait=True, cancel_futures=True)
            if log:
                log.close()
            rows = observations(time.perf_counter())
            self.summary = dict(mode="survey", cycles=cycle, visits=visits, analyzed_frames=processed,
                total_observation_records=ledger.counter, repeated_drone_shape_records=len(repeated),
                accumulated_shape_regions=len(accumulated), algorithm_version="survey-v3.2-20mhz", survey_ranges=ranges,
                target_channel_mhz=settings.survey_channel_mhz,
                sweep_seconds_median=float(np.median(sweep_times)) if sweep_times else None,
                cycle_seconds_median=float(np.median(cycle_times)) if cycle_times else None,
                inference_ms_median=float(np.median(infer_times)) if infer_times else None,
                runtime_overruns=runtime_overruns, host_dropped_transfers=host_drops,
                wall_seconds=time.perf_counter() - origin, environment_label=self.environment_label,
                error=error, radio=radio_info)
            if self.session:
                (self.session / "summary.json").write_text(json.dumps(self.summary, indent=2, ensure_ascii=False), encoding="utf-8")
                (self.session / "observations.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
            self.on_status(dict(state="ERROR" if error else "STOPPED", message=error or "RF 대역 관측을 중지했습니다.", summary=self.summary))
