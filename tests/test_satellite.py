import pytest
from d4d.demo_model import DemoModel
from d4d.satellite_map import DAEGU_CENTER, map_payload


OPTIONS=dict(trails=True,uncertainty=True,allLabels=False)


def test_public_reference_point_and_shared_native_telemetry():
    m=DemoModel();m.set_running(True)
    payload=map_payload(m,'F-02',OPTIONS)
    assert DAEGU_CENTER['latitude']==pytest.approx(35.8941666667)
    assert DAEGU_CENTER['longitude']==pytest.approx(128.6588888889)
    assert payload['selected']=='F-02'
    assert len(payload['tracks'])==3 and payload['spotPulses']==[]
    for web,native in zip(payload['tracks'],m.tracks()):
        assert web['x']==native['x'] and web['speed']==native['speed']
        assert len(web['trail'])==31
        assert web['trail'][-1]==[native['x'],native['y']]


def test_bearing_only_never_sends_a_hidden_position_to_webview():
    now=[0.0]
    m=DemoModel(lambda:now[0]);m.set_running(True);now[0]=3;m.advance();m.set_mode('bearing')
    h=map_payload(m,'H-01',OPTIONS)['tracks'][2]
    assert h['bearingOnly'] and h['bearing'] is not None
    for key in ('x','y','vx','vy','distance','speed','course'):
        assert h[key] is None
    assert h['trail']==[]
    assert set(map_payload(m,'H-01',OPTIONS)['spotPulses'][0])=={'id','age','bearing'}
    m.set_mode('lost')
    assert map_payload(m,'H-01',OPTIONS)['tracks'][2]['x'] is None


def test_stopped_web_telemetry_has_no_current_velocity():
    m=DemoModel();m.set_running(True);m.set_running(False)
    p=map_payload(m,'H-01',OPTIONS)
    assert p['stale']
    for d in p['tracks']:
        assert d['x'] is not None
        assert d['speed'] is d['course'] is d['vx'] is d['vy'] is None


def test_fallback_is_explicit_and_retryable():
    from PySide6.QtWidgets import QApplication
    from d4d.satellite_map import SatelliteMap
    app=QApplication.instance() or QApplication([])
    widget=SatelliteMap(DemoModel())
    widget._status('error','test connection failure')
    assert widget.failed
    assert widget.stack.currentWidget() is widget.native
    assert '개략 지도' in widget.notice_label.text()
    assert widget.retry.isEnabled()
    widget.close()


def test_contact_birth_and_removal_share_map_payload():
    now=[0.0]
    m=DemoModel(lambda:now[0]);m.set_running(True)
    now[0]=8;m.advance()
    payload=map_payload(m,'H-02',OPTIONS)
    assert len(payload['tracks'])==5
    h=next(d for d in payload['tracks'] if d['id']=='H-02')
    assert h['trail']==[[h['x'],h['y']]]
    now[0]=m.next_event;m.advance()
    payload=map_payload(m,'F-01',OPTIONS)
    assert len(payload['tracks'])==4
    assert {d['id'] for d in payload['tracks']}=={d['id'] for d in m.tracks()}


def test_missing_satellite_assets_use_native_map_immediately(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from d4d import satellite_map
    monkeypatch.delenv('WAVESENTRY_DEMO_MAP', raising=False)
    monkeypatch.setattr(satellite_map, 'ASSETS', tmp_path)
    app = QApplication.instance() or QApplication([])
    widget = satellite_map.SatelliteMap(DemoModel())
    widget.set_active(True)
    assert widget.failed and widget.web is None
    assert widget.stack.currentWidget() is widget.native
    assert 'vendor_cesium.py' in widget.notice_label.toolTip()
    widget.close()
