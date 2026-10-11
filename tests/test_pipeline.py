import importlib.util
from pathlib import Path
import numpy as np
import pytest
from d4d.config import Settings, ROOT, MODEL, FRAME_BYTES, FRAME_SAMPLES, verify_model
from d4d.dsp import process_iq
from d4d.detection import detection_record, Decision
from d4d.inference import decode_predictions


@pytest.mark.integration
@pytest.mark.skipif(not MODEL.is_file(), reason="Private model weights are not distributed")
def test_model_identity():
    assert verify_model().startswith("06b998be1d8d")


@pytest.mark.parametrize("kwargs", [{"lna": 7}, {"vga": 63}, {"confidence": 1}, {"backend": "FAKE"}])
def test_reject_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_frequency_mapping_and_target_gate():
    box = detection_record("drone", 0.8, [0, 160, 640, 480])
    assert box["low_mhz"] == 2444.5
    assert box["high_mhz"] == 2454.5
    assert box["bandwidth_mhz"] == 10
    assert box["start_ms"] == 0 and box["end_ms"] == 20
    assert box["in_target"]
    assert not detection_record("wifi", 0.99, [0, 160, 640, 480])["in_target"]
    assert not detection_record("drone", 0.99, [0, 0, 640, 100])["in_target"]
    # Actual observed no-drone failure: almost 20 MHz box centered in the ROI.
    wide = detection_record("drone", 0.89, [2.5, 0, 633, 640])
    assert not wide["in_target"]
    assert wide["gate_reason"] == "channel_geometry_mismatch"


def test_persistence_release_and_missing_data():
    d = Decision()
    hit = [detection_record("drone", 0.8, [0, 160, 640, 480])]
    assert d.update(hit, 0)[0] == "CANDIDATE"
    assert d.update([], 0.1)[0] == "CLEAR"
    assert d.update(hit, 0.2)[0] == "DETECTED"
    assert d.update([], 1.0)[0] == "DETECTED"
    assert d.update([], 1.5)[0] == "CLEAR"
    d.update(hit, 1.6)
    assert d.update(hit, 1.7)[0] == "DETECTED"
    assert d.update(hit, 1.8, valid=False)[0] == "DEGRADED"
    assert d.update(hit, 1.9)[0] == "CANDIDATE"


def test_old_hit_does_not_confirm_new_hit():
    d = Decision()
    hit = [detection_record("drone", 0.8, [0, 160, 640, 480])]
    assert d.update(hit, 0)[0] == "CANDIDATE"
    assert d.update(hit, 1)[0] == "CANDIDATE"


def test_class_aware_nms_and_threshold():
    p = np.zeros((1, 7, 4), dtype=np.float32)
    p[0, :4] = np.array([[320, 320, 320, 100], [320, 320, 320, 100],
                         [200, 200, 200, 10], [200, 200, 200, 10]])
    p[0, 4] = [0.9, 0.8, 0.1, 0.1]
    p[0, 5] = [0.1, 0.1, 0.85, 0.1]
    rows = decode_predictions(p, 0.25)
    assert len(rows) == 2
    assert sorted(rows[:, 5].tolist()) == [0, 1]
    assert np.allclose(rows[0, :4], [220, 220, 420, 420])
    assert decode_predictions(p, 0.95).shape == (0, 6)


def test_reject_partial_iq():
    with pytest.raises(ValueError):
        process_iq(bytes(200))


def test_input_pixel_identity_with_reference_code():
    import hashlib
    reference_path = ROOT / "vendor/iq_to_image.py"
    assert hashlib.sha256(reference_path.read_bytes()).hexdigest() == "7ae2801f7443de313374691e6ead19c25224e48dfe449aaf1d0944453bb4f85f"
    spec = importlib.util.spec_from_file_location("reference", reference_path)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    raw = np.random.default_rng(42).integers(-128, 128, FRAME_BYTES, dtype=np.int8).tobytes()
    r = np.frombuffer(raw, np.int8).astype(np.float32)
    iq = (r[0::2] + 1j * r[1::2]).astype(np.complex64)
    gray, spectrum, stats = process_iq(raw)
    assert np.array_equal(gray, np.asarray(reference.picture(iq)))
    assert gray.shape == (640, 640)
    assert np.isfinite(spectrum).all()
    assert stats["samples"] == FRAME_SAMPLES


def test_zero_iq_is_finite():
    gray, spectrum, stats = process_iq(bytes(FRAME_BYTES))
    assert np.isfinite(spectrum).all()
    assert np.isfinite(stats["rms_dbfs"])
    assert not gray.any()
