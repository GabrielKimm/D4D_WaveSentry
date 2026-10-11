from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import os

ROOT = Path(__file__).resolve().parent.parent
FS = 20_000_000
FC = 2_449_500_000
LOW_MHZ, HIGH_MHZ = 2444.5, 2454.5
FRAME_SAMPLES = 400_000
FRAME_BYTES = FRAME_SAMPLES * 2
MODEL_SHA256 = "06b998be1d8dd85389803ba5f1704c673ba38f3fcac15044e6bf54e5ea0b088f"
MODEL = Path(os.environ.get("D4D_MODEL_PATH", str(ROOT / "models/model_02a_picked.pt"))).expanduser().resolve()
IR = MODEL.parent / f"{MODEL.stem}_openvino_model/{MODEL.stem}.xml"
REPLAY_DIR = Path(os.environ.get("D4D_REPLAY_DIR", str(ROOT / "assets/replay"))).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    lna: int = 16
    vga: int = 16
    confidence: float = 0.25
    backend: str = "AUTO"
    serial: str = ""
    survey_low: int = 1
    survey_high: int = 6000
    survey_zooms: int = 4
    survey_threshold_db: float = 6.0
    survey_profile: str = "antenna_24_5"
    survey_channel_mhz: int = 20

    @property
    def survey_ranges(self):
        # Operating preset, not a measured antenna gain specification.
        if self.survey_profile == "antenna_24_5":
            return ((2400, 2500), (5150, 5890))
        if self.survey_profile == "full":
            return ((1, 6000),)
        return ((self.survey_low, self.survey_high),)

    @property
    def survey_label(self):
        return {"antenna_24_5": "2.4 / 5 GHz 안테나", "full": "전체 1–6000 MHz",
                "custom": "사용자 지정"}[self.survey_profile]

    def __post_init__(self):
        if self.lna not in range(0, 41, 8) or self.vga not in range(0, 63, 2):
            raise ValueError("LNA: 0–40 dB / 8 dB step; VGA: 0–62 dB / 2 dB step")
        if not 0.05 <= self.confidence <= 0.95:
            raise ValueError("Confidence must be between 0.05 and 0.95")
        if self.backend not in ("AUTO", "GPU", "CPU", "TORCH"):
            raise ValueError("Unknown inference backend")
        if self.survey_profile not in ("antenna_24_5", "full", "custom"):
            raise ValueError("Unknown survey antenna profile")
        if self.survey_channel_mhz not in (10, 20):
            raise ValueError("Survey channel hypothesis must be 10 or 20 MHz")
        if not (isinstance(self.survey_low, int) and isinstance(self.survey_high, int)
                and 1 <= self.survey_low < self.survey_high <= 6000):
            raise ValueError("Survey range must be integer MHz within 1–6000")
        if not isinstance(self.survey_zooms, int) or not 2 <= self.survey_zooms <= 8 or not 3 <= self.survey_threshold_db <= 20:
            raise ValueError("Survey: 2–8 zooms, 3–20 dB candidate threshold")

    def metadata(self):
        return dict(asdict(self), centerFrequencyHz=FC, sampleRateHz=FS,
                    targetLowMHz=LOW_MHZ, targetHighMHz=HIGH_MHZ,
                    basebandFilterBandwidthHz=20_000_000, frameSamples=FRAME_SAMPLES,
                    rfAmplifierEnabled=False, antennaPowerEnabled=False,
                    sampleFormat="ci8 / signed int8 interleaved IQ",
                    modelSha256=MODEL_SHA256, model=str(MODEL))


def dll_directory():
    candidates = [Path(os.environ.get("D4D_HACKRF_BIN", str(ROOT / "runtime/hackrf"))).expanduser().resolve()]
    for path in candidates:
        if (path / "hackrf-0.dll").is_file():
            return path
    raise FileNotFoundError("HackRF DLL not found. Set D4D_HACKRF_BIN to the Library/bin folder.")


def verify_model():
    if not MODEL.is_file():
        raise FileNotFoundError(
            "Model weights are not included. Place model_02a_picked.pt in models/ "
            "or set D4D_MODEL_PATH. See docs/SETUP.md."
        )
    digest = hashlib.sha256(MODEL.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        raise ValueError("model_02a_picked.pt hash mismatch; restore the original selected model.")
    return digest


def read_settings():
    try:
        return Settings(**json.loads((ROOT / "settings.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return Settings()


def save_settings(settings):
    temp = ROOT / "settings.json.tmp"
    temp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    temp.replace(ROOT / "settings.json")
