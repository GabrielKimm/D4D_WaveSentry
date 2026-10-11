from copy import deepcopy
import pytest
from d4d.survey_assessment import SurveyAssessment


def frame(t=100, regions=(), boxes=(), flags=()):
    return dict(generated_mono=t,phase='REVISIT',processed=12,visits=1,
        survey_ranges=((2400,2500),(5150,5890)),evidence_regions=list(regions),
        sweep=dict(quality_flags=[],seconds=.13),
        zoom=dict(center_mhz=5800,record=dict(last_mono=t),ended=t,observed_mono=t,
                  quality_flags=list(flags),boxes=list(boxes)))


def region(t=100, **kw):
    return dict(dict(id='RF-1',last_seen=t,score=2.0,episodes=4,supported=True,
        low_mhz=5790,high_mhz=5810),**kw)


def running():
    model=SurveyAssessment()
    model.set_lifecycle('READY')
    return model


def test_existing_supported_evidence_drives_alert_and_deduplicates_records():
    m=running()
    m.ingest(frame(regions=[region(),region()]))
    result=m.evaluate(100.3)
    assert result['state']=='DETECTED' and result['active_regions']==1
    assert [b['state'] for b in result['bands']]==['WAITING','DETECTED']
    assert result['score']==2 and result['episodes']==4


def test_score_alone_cannot_overrule_detector_supported_state():
    m=running()
    m.ingest(frame(regions=[region(score=3.9,supported=False)]))
    assert m.evaluate(100.2)['state']=='CANDIDATE'
    assert m.evaluate(100.2)['active_regions']==0


def test_real_observation_time_expires_even_with_fresh_heartbeat():
    m=running()
    m.ingest(frame(regions=[region()]))
    m.ingest(frame(t=107,regions=[region()]))
    result=m.evaluate(107)
    assert result['state']=='GAP' and result['active_regions']==0
    assert result['last_detection_age']==7


def test_frozen_capture_suppresses_alert_before_evidence_deadline():
    m=running()
    m.ingest(frame(regions=[region()]))
    assert m.evaluate(102.9)['state']=='DETECTED'
    result=m.evaluate(103.1)
    assert result['state']=='STALE' and result['active_regions'] is None


@pytest.mark.parametrize('state',['STOPPING','STOPPED','ERROR'])
def test_stop_or_error_immediately_suppresses_alarm_and_rejects_late_frames(state):
    m=running()
    m.ingest(frame(regions=[region()]))
    m.set_lifecycle(state)
    m.set_lifecycle('READY')  # An initialization signal already in the Qt queue can arrive late.
    m.ingest(frame(t=101,regions=[region(101)]))
    result=m.evaluate(101)
    assert result['state']==state and result['active_regions'] is None
    assert m.frame['generated_mono']==100
    m.reset()
    assert m.evaluate(102)['state']=='IDLE' and m.last_confirmed is None


def test_quality_hold_recovers_without_permanent_alarm_from_total_overruns():
    m=running()
    f=frame(regions=[region()],flags=['device_overrun'])
    f['runtime_overruns']=4
    m.ingest(f)
    assert m.evaluate(100.2)['state']=='QUALITY'
    f=frame(t=101,regions=[region(101)])
    f['runtime_overruns']=4
    m.ingest(f)
    assert m.evaluate(101.2)['state']=='DETECTED'


def test_empty_observation_is_no_evidence_never_confirmed_absence():
    m=running()
    m.ingest(frame())
    assert m.evaluate(100.2)['state']=='NO_EVIDENCE'
    m.ingest(dict(frame(t=101),processed=0,zoom=None))
    assert m.evaluate(101.2)['state']=='STARTING'


def test_edge_candidates_remain_unconfirmed_and_expire_without_refresh_from_old_zoom():
    m=running()
    box=dict(**{'class':'drone'},confidence=.95,low_mhz=5790,high_mhz=5810,in_target=False)
    f=frame(boxes=[box])
    m.ingest(f)
    assert m.evaluate(100.2)['state']=='CANDIDATE'
    assert m.evaluate(100.2)['score'] is None
    m.ingest(dict(f,generated_mono=107))
    assert m.evaluate(107)['state']=='NO_EVIDENCE'
    m=running()
    m.ingest(frame(boxes=[box],flags=['adc_clipping']))
    assert m.raw_candidates==[]


def test_outside_scope_model_box_cannot_create_candidate():
    m=running()
    m.ingest(frame(boxes=[dict(**{'class':'drone'},confidence=.95,low_mhz=800,high_mhz=820)]))
    assert m.evaluate(100.2)['state']=='NO_EVIDENCE'
