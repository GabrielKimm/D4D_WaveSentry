from datetime import datetime, timezone
import json
import shutil
import threading
import time
from collections import deque
import numpy as np
from PIL import Image
from .config import ROOT, REPLAY_DIR
from .detection import Decision
from .inference import Detector
from .radio import RadioStream
from .preparation import PreparedStream


class Engine:
    """UI-independent worker. All heavy work runs outside the Qt GUI thread."""
    def __init__(self, settings, mode="live", on_frame=lambda _: None, on_status=lambda _: None):
        self.settings, self.mode = settings, mode
        self.on_frame, self.on_status = on_frame, on_status
        self.stop_event = threading.Event()
        self.snapshot_event = threading.Event()
        self.session = None
        self.summary = {}

    def stop(self):
        self.stop_event.set()

    def request_snapshot(self):
        self.snapshot_event.set()

    def run(self, seconds=None):
        radio = None
        prepared = None
        log = None
        stats = {"bytes": 0, "mbps": 0, "overruns": None, "device_error": 0}
        started = time.perf_counter()
        processed = skipped = events = 0
        times = deque(maxlen=50)
        inference_times, dsp_times, ages = (deque(maxlen=10000) for _ in range(3))
        error = None
        last_sequence = 0
        last_state = ""
        decision = Decision()
        try:
            self.on_status({"state": "LOADING", "message": "모델을 준비하고 있습니다…"})
            detector = Detector(self.settings.backend, self.settings.confidence)
            if self.stop_event.is_set():
                return
            self.on_status({"state": "READY", "message": detector.warning or detector.device_name,
                            "backend": detector.backend})
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self.session = ROOT / "output" / f"{stamp}_{self.mode}"
            self.session.mkdir(parents=True)
            metadata = dict(self.settings.metadata(), mode=self.mode, startedUtc=datetime.now(timezone.utc).isoformat(),
                            backend=detector.backend, device=detector.device_name,
                            timestampBasis="host delivery monotonic; not hardware UTC",
                            policy="latest complete 20 ms frame; bandwidth 7–13 MHz and target frequency IoU >=0.6; 2/3 hits in 0.75 s; release 1.2 s",
                            environmentLabel="unverified live environment" if self.mode == "live" else "recorded sample replay")
            (self.session / "session.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            log = (self.session / "frames.jsonl").open("w", encoding="utf-8", buffering=1)
            if self.mode == "live":
                radio = RadioStream(self.settings)
                radio.start()
                prepared = PreparedStream(radio, workers=2 if "GPU" in detector.backend else 1)
                samples = None
            else:
                samples = sorted(REPLAY_DIR.glob("*.png"))
                if not samples:
                    raise FileNotFoundError("Replay images are not included. Add PNG files to assets/replay/ or set D4D_REPLAY_DIR.")
            stream_started = time.perf_counter()
            last_frame_time = stream_started
            degraded_until = 0
            sample_index = 0
            while not self.stop_event.is_set():
                now = time.perf_counter()
                if seconds and now - stream_started >= seconds:
                    break
                raw = None
                if radio:
                    for msg in radio.messages():
                        if msg["type"] == "error":
                            raise RuntimeError(msg["message"])
                        if msg["type"] == "stats":
                            if msg["overruns"] > (stats["overruns"] or 0):
                                degraded_until = now + 1.3
                            stats.update(msg)
                        elif msg["type"] == "ready":
                            stats.update({k: v for k, v in msg.items() if k != "type"})
                            metadata["actualRadio"] = dict(stats)
                            (self.session / "session.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
                    packet = prepared.latest(last_sequence)
                    if packet is None:
                        if not radio.process.is_alive():
                            raise RuntimeError("HackRF 수신 프로세스가 종료되었습니다.")
                        if now - last_frame_time > 3:
                            raise RuntimeError("3초 동안 새 IQ 데이터가 없습니다.")
                        self.stop_event.wait(0.003)
                        continue
                    seq, acquired, raw, gray, spectrum, signal, dsp_ms = packet
                    skipped += max(0, seq - last_sequence - 1)
                    last_sequence = seq
                    sample_name = None
                else:
                    # Explicitly labelled recorded-image replay, no simulated RF readings.
                    path = samples[(sample_index // 8) % len(samples)]
                    sample_index += 1
                    gray = np.asarray(Image.open(path).convert("L").resize((640, 640)))
                    spectrum, signal, dsp_ms = None, {}, 0.0
                    acquired, seq, sample_name = time.perf_counter(), sample_index, path.name
                boxes, inference_ms = detector.predict(gray)
                completed = time.perf_counter()
                age_ms = (completed - acquired) * 1000
                valid = age_ms < 750 and completed > degraded_until and stats["device_error"] == 0
                if radio and stats["overruns"] is None:
                    valid = False
                # Replay source center varies; present class confidence without fixed-band filtering.
                if not radio:
                    for box in boxes:
                        box["in_target"] = box["class"] == "drone"
                        box["gate_reason"] = "replay_gate_bypassed"
                        box["target_iou"] = None
                    for box in boxes:
                        for key in ("low_mhz", "high_mhz", "bandwidth_mhz"):
                            box[key] = None
                state, confidence = decision.update(boxes, completed, valid)
                if state == "DETECTED" and last_state != "DETECTED":
                    events += 1
                last_state = state
                processed += 1
                times.append(completed)
                fps = (len(times) - 1) / max(times[-1] - times[0], 0.001) if len(times) > 1 else 0
                inference_times.append(inference_ms)
                dsp_times.append(dsp_ms)
                ages.append(age_ms)
                elapsed = completed - stream_started
                last_frame_time = completed
                payload = {"sequence": seq, "utc": datetime.now(timezone.utc).isoformat(), "mode": self.mode,
                           "state": state, "confidence": confidence, "boxes": boxes, "backend": detector.backend,
                           "raw_drone_score": max((b["confidence"] for b in boxes if b["class"] == "drone"), default=0),
                           "rejected_drone_boxes": sum(b["class"] == "drone" and not b["in_target"] for b in boxes),
                           "inference_ms": inference_ms, "dsp_ms": dsp_ms, "age_ms": age_ms,
                           "fps": fps, "processed": processed, "skipped": skipped, "events": events,
                           "elapsed": elapsed, "coverage_pct": processed / max(seq, 1) * 100 if radio else None,
                           "signal": signal, "radio": dict(stats), "session": str(self.session),
                           "sample": sample_name, "sample_offset_ms": (seq - 1) * 20 if radio else None}
                # Rotate at ~20 MB so a long observation doesn't create an unbounded single file.
                if log.tell() > 20_000_000:
                    log.close()
                    log = (self.session / f"frames_{processed:08d}.jsonl").open("w", encoding="utf-8", buffering=1)
                if processed % 500 == 0 and shutil.disk_usage(self.session).free < 512_000_000:
                    raise RuntimeError("저장 공간이 512 MB 미만입니다. 수신을 중지하고 기록을 보존합니다.")
                log.write(json.dumps(payload, ensure_ascii=False) + "\n")
                if self.snapshot_event.is_set():
                    self.snapshot_event.clear()
                    folder = self.session / f"snapshot_{seq:08d}"
                    folder.mkdir(exist_ok=True)
                    Image.fromarray(gray).save(folder / "model_input.png")
                    if raw is not None:
                        (folder / "frame.cs8").write_bytes(raw)
                        (folder / "frame.cs8.json").write_text(json.dumps(dict(self.settings.metadata(),
                            frame=seq, durationSeconds=0.02, capture=payload), indent=2), encoding="utf-8")
                    (folder / "detections.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
                    self.on_status({"state": "SAVED", "message": str(folder)})
                self.on_frame(dict(payload, image=gray, spectrum=spectrum))
                if not radio:
                    self.stop_event.wait(max(0, 0.2 - (time.perf_counter() - acquired)))
        except Exception as exc:
            error = str(exc)
            self.on_status({"state": "ERROR", "message": error})
        finally:
            if prepared:
                prepared.close()
            final_messages = radio.close() if radio else []
            for message in final_messages:
                if message["type"] == "stopped":
                    stats.update(message)
                elif message["type"] == "error" and error is None:
                    error = message["message"]
            if log:
                log.close()
            self.summary = {"mode": self.mode, "processed": processed, "skipped": skipped,
                "events": events, "wall_seconds": time.perf_counter() - started,
                "statistics_window_frames": len(ages),
                "received_frames": stats.get("frames"),
                "analysis_coverage_pct": processed / max(stats.get("frames", 0), 1) * 100 if radio else None,
                "unanalysed_frames": max(0, stats.get("frames", 0) - processed) if radio else None,
                "shutdown_unanalysed_frames": max(0, stats.get("frames", 0) - last_sequence) if radio else None,
                "inference_ms_median": float(np.median(inference_times)) if inference_times else None,
                "dsp_ms_median": float(np.median(dsp_times)) if dsp_times else None,
                "age_ms_p95": float(np.percentile(ages, 95)) if ages else None,
                "radio": stats, "error": error}
            if self.session:
                (self.session / "summary.json").write_text(json.dumps(self.summary, indent=2), encoding="utf-8")
            self.on_status({"state": "ERROR" if error else "STOPPED", "message": error or "수신을 중지했습니다.",
                            "summary": self.summary})
