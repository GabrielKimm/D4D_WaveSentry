import json
import os
from pathlib import Path
import time
import numpy as np
from .config import ROOT, MODEL, IR, MODEL_SHA256, verify_model
from .detection import detection_record

# Keep Ultralytics runtime data inside this app and disable its analytics.
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / "runtime/ultralytics"))
os.environ.setdefault("YOLO_OFFLINE", "true")
(ROOT / "runtime/ultralytics").mkdir(parents=True, exist_ok=True)


def decode_predictions(pred, confidence, iou_threshold=0.7):
    """Ultralytics single-label, class-aware NMS, max_det=300, no resizing."""
    if pred.ndim == 3 and pred.shape[-1] == 6:
        rows = pred[0]
        return rows[np.isfinite(rows).all(axis=1) & (rows[:, 4] >= confidence)]
    if pred.ndim != 3 or pred.shape[1] != 7:
        raise ValueError(f"Unexpected model output: {pred.shape}")
    candidates = pred[0].T
    classes = candidates[:, 4:].argmax(axis=1)
    scores = candidates[np.arange(len(candidates)), classes + 4]
    keep = np.isfinite(candidates).all(axis=1) & (scores > confidence)
    coords, scores, classes = candidates[keep, :4], scores[keep], classes[keep]
    boxes = np.empty_like(coords)
    boxes[:, :2] = coords[:, :2] - coords[:, 2:] / 2
    boxes[:, 2:] = coords[:, :2] + coords[:, 2:] / 2
    order = scores.argsort(kind="stable")[::-1][:30000]
    selected = []
    while len(order) and len(selected) < 300:
        idx = order[0]
        selected.append(idx)
        rest = order[1:]
        low = np.maximum(boxes[idx, :2], boxes[rest, :2])
        high = np.minimum(boxes[idx, 2:], boxes[rest, 2:])
        intersection = np.maximum(high - low, 0).prod(axis=1)
        area0 = np.maximum(boxes[idx, 2:] - boxes[idx, :2], 0).prod()
        area1 = np.maximum(boxes[rest, 2:] - boxes[rest, :2], 0).prod(axis=1)
        iou = intersection / (area0 + area1 - intersection + 1e-7)
        order = rest[(iou <= iou_threshold) | (classes[rest] != classes[idx])]
    return np.column_stack((boxes[selected], scores[selected], classes[selected]))


class Detector:
    def __init__(self, backend="AUTO", confidence=0.25):
        verify_model()
        self.confidence = confidence
        self.names = {0: "drone", 1: "wifi", 2: "bt"}
        self.warning = ""
        self.torch_model = None
        if backend == "TORCH" or not IR.exists():
            self._torch()
            if backend != "TORCH":
                self.warning = "OpenVINO 모델이 없어 PyTorch CPU로 실행합니다. Optimize Model.cmd를 실행하세요."
        else:
            import openvino as ov
            manifest = json.loads((IR.parent / "source.json").read_text(encoding="utf-8"))
            if manifest["source_sha256"] != MODEL_SHA256:
                raise ValueError("OpenVINO model source hash mismatch. Re-run Optimize Model.cmd.")
            import hashlib
            for name, digest in manifest["artifacts"].items():
                if hashlib.sha256((IR.parent / name).read_bytes()).hexdigest() != digest:
                    raise ValueError(f"OpenVINO artifact hash mismatch: {name}")
            core = ov.Core()
            device = ("GPU" if "GPU" in core.available_devices else "CPU") if backend == "AUTO" else backend
            (ROOT / "runtime/ov_cache").mkdir(parents=True, exist_ok=True)
            opts = {"PERFORMANCE_HINT": "LATENCY", "CACHE_DIR": str(ROOT / "runtime/ov_cache")}
            if device == "CPU":
                opts["INFERENCE_NUM_THREADS"] = 4
            try:
                compiled = core.compile_model(str(IR), device, opts)
            except Exception as exc:
                if backend != "AUTO":
                    raise
                device = "CPU"
                opts["INFERENCE_NUM_THREADS"] = 4
                self.warning = f"GPU 초기화 실패; CPU로 전환: {exc}"
                compiled = core.compile_model(str(IR), device, opts)
            self.request = compiled.create_infer_request()
            self.backend = f"OpenVINO / {device}"
            self.device_name = core.get_property(device, "FULL_DEVICE_NAME")
        # Allocate once; grayscale repeated over RGB, exactly as PNG loading does.
        self.tensor = np.empty((1, 3, 640, 640), dtype=np.float32)
        self.predict(np.zeros((640, 640), dtype=np.uint8))

    def _torch(self):
        import torch
        torch.set_num_threads(4)
        from ultralytics import YOLO, settings
        settings.update({"sync": False})
        self.torch_model = YOLO(str(MODEL))
        self.names = self.torch_model.names
        self.backend, self.device_name = "PyTorch / CPU", "CPU"

    def predict(self, gray):
        begin = time.perf_counter()
        if self.torch_model is not None:
            rgb = np.repeat(gray[..., None], 3, axis=2)
            result = self.torch_model.predict(rgb, imgsz=640, conf=self.confidence,
                                             device="cpu", verbose=False)[0]
            boxes = [detection_record(self.names[int(c)], s, xy) for c, s, xy in zip(
                result.boxes.cls.tolist(), result.boxes.conf.tolist(), result.boxes.xyxy.tolist())]
        else:
            np.multiply(gray, 1.0 / 255.0, out=self.tensor[0, 0], casting="unsafe")
            self.tensor[0, 1] = self.tensor[0, 0]
            self.tensor[0, 2] = self.tensor[0, 0]
            self.request.infer({0: self.tensor})
            pred = self.request.get_output_tensor(0).data
            rows = decode_predictions(pred, self.confidence)
            boxes = [detection_record(self.names.get(int(row[5]), str(int(row[5]))), row[4], row[:4])
                     for row in rows]
        return boxes, (time.perf_counter() - begin) * 1000
