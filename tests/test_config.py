import hashlib
import pytest
from d4d import config


def test_missing_and_modified_model_are_rejected(tmp_path, monkeypatch):
    model = tmp_path / 'model.pt'
    monkeypatch.setattr(config, 'MODEL', model)
    with pytest.raises(FileNotFoundError, match='not included'):
        config.verify_model()
    model.write_bytes(b'invalid model')
    with pytest.raises(ValueError, match='hash mismatch'):
        config.verify_model()
    expected = hashlib.sha256(model.read_bytes()).hexdigest()
    monkeypatch.setattr(config, 'MODEL_SHA256', expected)
    assert config.verify_model() == expected


def test_hackrf_lookup_uses_configured_directory(tmp_path, monkeypatch):
    monkeypatch.setenv('D4D_HACKRF_BIN', str(tmp_path))
    with pytest.raises(FileNotFoundError):
        config.dll_directory()
    (tmp_path / 'hackrf-0.dll').touch()
    assert config.dll_directory() == tmp_path


def test_settings_recover_from_invalid_json_and_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    path = tmp_path / 'settings.json'
    path.write_text('{broken', encoding='utf-8')
    assert config.read_settings() == config.Settings()
    settings = config.Settings(lna=24, vga=32, survey_profile='custom', survey_low=2400, survey_high=2500)
    config.save_settings(settings)
    assert config.read_settings() == settings
    assert not (tmp_path / 'settings.json.tmp').exists()
