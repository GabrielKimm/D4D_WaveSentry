from math import hypot
import pytest
from d4d.demo_model import DemoModel, SCENES, sample_tracks, angle, threat


@pytest.mark.parametrize('site', SCENES)
@pytest.mark.parametrize('t', [0, 99.99, 100, 119.99, 120, 120.01, 3600, 86400])
def test_motion_derivatives_and_no_end_boundary(site,t):
    dt=.001
    before=sample_tracks(t-dt,site)
    after=sample_tracks(t+dt,site)
    for d,a,b in zip(sample_tracks(t,site),before,after):
        vx,vy=(b['x']-a['x'])/(2*dt),(b['y']-a['y'])/(2*dt)
        assert hypot(vx,vy)==pytest.approx(d['speed'],rel=1e-6)
        assert angle(vx,vy)==pytest.approx(d['course'],abs=1e-5)
        assert angle(d['x'],d['y'])==pytest.approx(d['bearing'])
        assert d['speed']>0
        assert hypot(b['x']-a['x'],b['y']-a['y'])<.1


def test_receive_stop_retains_last_observation_and_age():
    now=[0.0]
    m=DemoModel(lambda:now[0]);m.set_running(True)
    now[0]=12;m.advance();m.set_running(False)
    tracks=m.tracks()
    now[0]=24;m.advance()
    assert m.tracks()==tracks
    assert m.age==12
    assert m.observed_time==12
    m.set_running(True)
    now[0]=25;m.advance()
    assert m.observed_time==13
    assert not m.stale and m.age==0


def test_lost_keeps_last_bearing_only_evidence():
    now=[0.0]
    m=DemoModel(lambda:now[0]);m.set_running(True);m.set_mode('bearing')
    now[0]=10;m.set_mode('lost');tracks=m.tracks()
    now[0]=20;m.advance()
    assert m.elapsed==20 and m.observed_time==10 and m.age==10
    assert m.tracks()==tracks
    assert m.bearing_only(tracks[2])
    m.set_running(False);now[0]=25;m.set_running(True)
    assert m.stale and m.tracks()==tracks
    m.set_mode('position')
    assert not m.stale and not m.bearing_only(m.tracks()[2])


def test_settings_while_paused_cannot_invent_a_position_fix():
    now=[0.0]
    m=DemoModel(lambda:now[0]);m.set_running(True);now[0]=3;m.advance()
    m.set_mode('bearing');m.set_running(False)
    m.set_mode('position')
    assert m.bearing_only(m.tracks()[2])
    m.set_running(True)
    assert not m.bearing_only(m.tracks()[2])


@pytest.mark.parametrize('site', SCENES)
def test_patrol_produces_protected_zone_entry_and_exit(site):
    states=[threat(sample_tracks(t,site)[2],site)[0] for t in range(400)]
    assert 'inside' in states and 'approach' in states and 'outbound' in states


def test_opening_cues_then_bounded_random_contacts():
    import random
    now=[0.0]
    m=DemoModel(lambda:now[0],random.Random(17));m.set_running(True)
    for t,ids in [(0,set()),(2.99,set()),(3,{'H-01'}),(7.99,{'H-01'}),(8,{'H-01','H-02'})]:
        now[0]=t;m.advance()
        assert set(m.hostiles)==ids
    events=m.take_events()
    assert [(e['id'],e['time']) for e in events]==[('H-01',3),('H-02',8)]
    previous=8;seen=set()
    for _ in range(300):
        now[0]=m.next_event;m.advance()
        event=m.take_events()[0]
        assert 3 <= event['time']-previous <= 5
        previous=event['time'];seen.add(event['kind'])
        assert len(m.hostiles)<=2 and len(m.tracks())<=5
        for pulse in m.spot_pulses():
            assert pulse['id'] in m.hostiles
    assert seen=={'spot','lost'}


def test_loading_pause_and_loss_do_not_consume_cues():
    now=[0.0]
    m=DemoModel(lambda:now[0]);m.reset_scenario(ready=False);m.set_running(True)
    now[0]=20;m.advance();assert m.scenario_time==0 and not m.hostiles
    m.set_scene_ready();now[0]=22;m.advance();m.set_running(False)
    now[0]=40;m.advance();assert m.scenario_time==2 and not m.hostiles
    m.set_running(True);now[0]=41;m.advance();assert set(m.hostiles)=={'H-01'}
    m.set_mode('lost');frozen=m.tracks()
    now[0]=60;m.advance();assert m.tracks()==frozen and not m.spot_pulses()
    m.set_mode('position');now[0]=64.99;m.advance();assert 'H-02' not in m.hostiles
    now[0]=65;m.advance();assert 'H-02' in m.hostiles
    m.reset_scenario();assert not m.hostiles and m.scenario_time==0 and m.next_event==3


@pytest.mark.parametrize('site',SCENES)
def test_new_acquisition_has_no_old_trail_and_starts_outside_zone(site):
    now=[0.0]
    m=DemoModel(lambda:now[0]);m.site=site;m.set_running(True)
    for t,ident in [(3,'H-01'),(8,'H-02')]:
        now[0]=t;m.advance()
        d=next(d for d in m.tracks() if d['id']==ident)
        assert d['distance']>SCENES[site].zone
        assert m.trail(ident)==[d]
        assert any(p['id']==ident and p['age']==0 for p in m.spot_pulses())
    now[0]=10.41;m.advance();assert not m.spot_pulses()
