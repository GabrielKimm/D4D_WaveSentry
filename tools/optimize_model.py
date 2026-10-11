"""Export and hash the separately provisioned model for OpenVINO inference."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hashlib
import json
import os
from d4d.config import ROOT, MODEL, verify_model
os.environ["YOLO_CONFIG_DIR"] = str(ROOT / "runtime/ultralytics")
os.environ["YOLO_OFFLINE"] = "true"
(ROOT / "runtime/ultralytics").mkdir(parents=True, exist_ok=True)


def main():
    digest = verify_model()
    from ultralytics import YOLO, settings
    settings.update({"sync": False})
    model = YOLO(str(MODEL))
    print("Classes:", model.names)
    path = Path(model.export(format="openvino", imgsz=640, half=False, dynamic=False, batch=1, device="cpu"))
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir() if p.suffix in (".xml", ".bin")}
    (path / "source.json").write_text(json.dumps({"source_sha256": digest, "names": model.names,
        "artifacts": files, "precision": "FP32 export; runtime device precision may vary"}, indent=2), encoding="utf-8")
    print("Export verified:", path)


if __name__ == "__main__":
    main()
