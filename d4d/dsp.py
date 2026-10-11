"""Training-compatible preprocessing. The vendored reference is unchanged."""
import numpy as np
from vendor.iq_to_image import spectrogram_clean, to_image
from .config import FRAME_BYTES, FRAME_SAMPLES


def process_iq(raw):
    if len(raw) != FRAME_BYTES:
        raise ValueError(f"Expected {FRAME_BYTES} IQ bytes, got {len(raw)}")
    components = np.frombuffer(raw, dtype=np.int8).astype(np.float32)
    iq = components.view(np.complex64)
    clean = spectrogram_clean(iq)
    gray = np.asarray(to_image(clean))
    # Display-only summary; model input remains the exact reference grayscale image.
    # These are relative STFT magnitudes, not calibrated dBm or a PSD density.
    power = 10 * np.log10(np.mean(10 ** (clean / 10), axis=1) + 1e-12)
    spectrum = power.reshape(512, 16).mean(axis=1).astype(np.float32)
    rms = float(10 * np.log10(np.mean(np.abs(iq / 128) ** 2) + 1e-12))
    clipped = float(np.mean(np.abs(components) >= 127) * 100)
    return gray, spectrum, {"rms_dbfs": rms, "clipped_pct": clipped,
                            "samples": FRAME_SAMPLES}
