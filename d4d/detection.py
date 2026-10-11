from collections import deque
from .config import FC, LOW_MHZ, HIGH_MHZ


def detection_record(cls, confidence, xyxy, fc=FC):
    x0, y0, x1, y1 = [max(0.0, min(640.0, float(v))) for v in xyxy]
    low = fc / 1e6 + (0.5 - y1 / 640) * 20
    high = fc / 1e6 + (0.5 - y0 / 640) * 20
    center = (low + high) / 2
    width = high - low
    overlap = max(0.0, min(high, HIGH_MHZ) - max(low, LOW_MHZ))
    frequency_iou = overlap / max(width + HIGH_MHZ - LOW_MHZ - overlap, 1e-6)
    # The user's target is a known fixed 10 MHz downlink. Wideband interference
    # classified as drone must not pass solely because its center is in the ROI.
    accepted = cls == "drone" and 7 <= width <= 13 and frequency_iou >= 0.60
    reason = "accepted" if accepted else "other_class" if cls != "drone" else "channel_geometry_mismatch"
    return {"class": cls, "confidence": float(confidence), "xyxy": [x0, y0, x1, y1],
            "low_mhz": low, "high_mhz": high, "bandwidth_mhz": width,
            "start_ms": x0 / 640 * 20, "end_ms": x1 / 640 * 20,
            "in_target": bool(accepted), "target_iou": frequency_iou, "gate_reason": reason}


class Decision:
    """2 of the last 3 observations within 0.75 s; release after 1.2 s.

    This is an explicit UI persistence rule, not a calibrated probability.
    Missing/invalid data resets the detector instead of claiming a clear band.
    """
    def __init__(self):
        self.history = deque(maxlen=3)
        self.active = False
        self.last_hit = -1e9

    def reset(self):
        self.history.clear()
        self.active = False
        self.last_hit = -1e9

    def update(self, detections, now, valid=True):
        if not valid:
            self.reset()
            return "DEGRADED", 0.0
        confidence = max((d["confidence"] for d in detections if d["in_target"]), default=0.0)
        self.history.append((now, confidence > 0))
        while self.history and now - self.history[0][0] > 0.75:
            self.history.popleft()
        if confidence:
            self.last_hit = now
        if sum(hit for _, hit in self.history) >= 2:
            self.active = True
        elif now - self.last_hit > 1.2:
            self.active = False
        return ("DETECTED" if self.active else "CANDIDATE" if confidence else "CLEAR"), confidence
