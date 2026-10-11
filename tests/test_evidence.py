import pytest
from d4d.config import Settings
from d4d.band_scheduler import BandScheduler
from d4d.evidence import EvidenceBank, confirmation_candidate, confirmation_plan, paired_partial_evidence
from d4d.detection import detection_record
from d4d.survey import survey_boxes, Scheduler


def frames(t, score=.8, low=2444.5, high=2454.5, flags=(), count=6, positive=1):
    center = 2449.5
    raw = detection_record('drone', score, [10, (center+10-high)*32, 620, (center+10-low)*32])
    boxes = survey_boxes([raw], center, 1, 6000)
    return [dict(stamp=t+i*.02, boxes=boxes if i < positive else [], quality_flags=list(flags)) for i in range(count)]


def test_profiles_preserve_full_and_custom_but_default_to_antenna():
    assert Settings().survey_ranges == ((2400, 2500), (5150, 5890))
    assert Settings(survey_profile='full').survey_ranges == ((1, 6000),)
    assert Settings(survey_profile='custom', survey_low=800, survey_high=1000).survey_ranges == ((800, 1000),)
    with pytest.raises(ValueError):
        Settings(survey_profile='unknown')


def test_three_separate_visits_accumulate_single_frame_hits():
    bank = EvidenceBank()
    for episode, t in enumerate([1, 2, 3]):
        row = bank.observe(frames(t), t+.12, 'gain16', episode)[0]
        assert row['supported'] == (episode == 2)
    assert row['episodes'] == 3 and row['score'] >= 1.6
    assert not row['probability'] and row['device_identity'] is None


def test_same_burst_followups_are_one_episode_and_saturate():
    bank = EvidenceBank()
    for i in range(12):
        row = bank.observe(frames(1+i*.05, .99, positive=6), 1.2+i*.05, 'gain16', 'same')[0]
    assert row['episodes'] == 1 and row['score'] <= 1 and not row['supported']


def test_gaps_age_evidence_without_asserting_absence():
    bank = EvidenceBank()
    for i in range(3):
        bank.observe(frames(i+1), i+1.12, 'gain16', i)
    before = bank.view(4)[0]
    old = bank.view(20)[0]
    assert old['score'] < before['score'] and not old['supported']
    assert '미확인' in old['state']
    assert bank.view(40) == []


def test_stale_state_must_pass_entry_threshold_again():
    bank = EvidenceBank()
    for i in range(3):
        bank.observe(frames(i+1),i+1.12,'gain16',i)
    assert bank.view(4)[0]['supported']
    row = bank.observe(frames(20),20.12,'gain16',20)[0]
    assert row['score'] < bank.enter_score and not row['supported']


def test_invalid_edge_and_competing_class_do_not_accumulate():
    bank = EvidenceBank()
    assert bank.observe(frames(1, flags=['adc_clipping']), 1.2, 'gain16', 1) == []
    assert bank.observe(frames(2, low=2439.5, high=2454.5), 2.2, 'gain16', 2) == []
    ambiguous = frames(3)
    ambiguous[0]['boxes'].append(dict(ambiguous[0]['boxes'][0], **{'class':'wifi', 'confidence':.95}))
    assert bank.observe(ambiguous, 3.2, 'gain16', 3) == []


def test_gain_and_disjoint_frequency_do_not_merge():
    bank = EvidenceBank()
    a = bank.observe(frames(1, low=2441, high=2445), 1.2, 'gain16', 1)[0]
    b = bank.observe(frames(2, low=2453, high=2457), 2.2, 'gain16', 2)[0]
    c = bank.observe(frames(3, low=2441, high=2445), 3.2, 'gain24', 3)[0]
    assert len({a['id'], b['id'], c['id']}) == 3


def test_two_bands_have_blind_probes_even_without_power_candidates():
    s = BandScheduler(Settings().survey_ranges)
    for now in range(100):
        plan = s.plan([], now)
        assert len(plan) == 2
        assert {c['probe_band'] for c in plan} == {0,1}
        for c in plan:
            assert any(a <= c['center_mhz'] <= b for a,b in s.ranges)
            s.complete(c, now, 0)
    for grid in s.grids:
        assert max(b-a for a,b in zip(grid,grid[1:])) <= 8


def test_stale_score_expires_and_old_psd_candidate_cannot_return():
    s = BandScheduler(Settings().survey_ranges)
    c = dict(center_mhz=2450, low_mhz=2445, high_mhz=2455, priority=20,
             contrast_db=10, change_db=0, reason='test')
    s.complete(c, 1, .9)
    assert s.recent_hit(c, 2) == .9
    assert s.recent_hit(c, 6) == 0
    s.plan([c], 1)
    assert all(p['reason']=='blind_probe_no_power_gate' for p in s.plan([],5))
    legacy = Scheduler(1,6000)
    legacy.complete(c,1,.9)
    legacy.plan([],6)
    assert not legacy.hits


def test_edge_followup_recenters_within_profile_and_ignores_bad_input():
    c = dict(center_mhz=2449.5, reason='test')
    edge = frames(1, low=2439.5, high=2448.5)
    follow = confirmation_candidate(c, edge, Settings().survey_ranges)
    assert follow['reason'] == 'immediate_recenter'
    assert follow['center_mhz'] == 2444
    assert confirmation_candidate(c, frames(1, flags=['device_overrun']), Settings().survey_ranges) is None


def test_gap_boxes_are_outside_disjoint_profile():
    raw = [detection_record('drone',.9,[0,160,640,480])]
    box = survey_boxes(raw,4000,2400,5890,Settings().survey_ranges)[0]
    assert not box['in_target'] and box['gate_reason']=='outside_survey_scope'


def test_segment_merge_preserves_unknown_gap_and_requested_coverage():
    import numpy as np
    from d4d.survey_radio import merge_sweeps
    parts = [dict(low=a,high=b,power=np.full(b-a,-80.),stamps=np.ones(b-a)*i,
                  clips=np.zeros(b-a),quality={'overruns':0,'host_dropped_transfers':0},first=i,ended=i+.1)
             for i,(a,b) in enumerate([(2400,2500),(5150,5890)],1)]
    result = merge_sweeps(parts,[(2400,2500),(5150,5890)],.13)
    assert result['coverage_pct']==100
    assert np.isnan(result['power'][100:2750]).all()
    assert (result['stamps'][100:2750]==0).all()
    assert result['stamps'][0]==1 and result['stamps'][-1]==2
    parts[1]['power'][0]=np.nan
    result = merge_sweeps(parts,[(2400,2500),(5150,5890)],.13)
    assert result['coverage_pct'] < 100


def pair_visits(t=1, width=20):
    result=[]
    for side,fc,stamp in [('lower',2443.5,t),('upper',2455.5,t+.3)]:
        lo,hi=max(fc-10,2449.5-width/2),min(fc+10,2449.5+width/2)
        raw=detection_record('drone',.9,[0,(fc+10-hi)*32,640,(fc+10-lo)*32])
        boxes=survey_boxes([raw],fc,2400,5890,Settings().survey_ranges)
        result.append(dict(candidate=dict(center_mhz=fc,pair_side=side),frames=[
            dict(stamp=stamp+i*.02,boxes=boxes,quality_flags=[]) for i in range(3)]))
    return result


def test_20mhz_pairs_use_original_images_and_complementary_edges():
    visits=pair_visits()
    pair=paired_partial_evidence(visits)
    assert pair['bandwidth_mhz']==20 and not pair['simultaneous']
    assert all(not b['in_target'] for v in visits for f in v['frames'] for b in f['boxes'])
    bank=EvidenceBank()
    row=bank.observe_pair(pair,1.4,'gain16',1)[0]
    assert row['episodes']==1 and not row['supported']
    assert row['score']<=.75 and row['evidence_kinds']==['paired_partial']


def test_wrong_width_stale_one_sided_or_invalid_pair_cannot_confirm():
    assert paired_partial_evidence(pair_visits(width=28)) is None
    assert paired_partial_evidence(pair_visits()[:1]) is None
    late=pair_visits()
    for f in late[1]['frames']:
        f['stamp']+=2
    assert paired_partial_evidence(late) is None
    invalid=pair_visits()
    for f in invalid[0]['frames']:
        f['quality_flags']=['device_overrun']
    assert paired_partial_evidence(invalid) is None


def test_20mhz_both_edge_output_requests_two_bounded_windows():
    c=dict(center_mhz=2449.5,reason='test',episode=7)
    wide=frames(1,low=2439.5,high=2459.5,positive=3)
    plan=confirmation_plan(c,wide,Settings().survey_ranges,20)
    assert len(plan)==2 and all(p['episode']==7 for p in plan)
    assert [p['center_mhz'] for p in plan]==[2443.5,2455.5]
    assert confirmation_plan(c,wide,Settings().survey_ranges,10)==[]


def test_coherent_pair_gets_bounded_revisit_without_starving_band_probes():
    scheduler=BandScheduler(Settings().survey_ranges)
    scheduler.evidence=[dict(id='RF-1',low_mhz=5780,high_mhz=5800,score=.7,
        last_seen=1,evidence_kinds=['paired_partial'])]
    plan=scheduler.plan([],2)
    assert plan[0]['reason']=='evidence_revisit' and plan[0]['center_mhz']==5790
    assert {c['probe_band'] for c in plan if 'probe_band' in c}=={0,1}
    for c in plan:
        scheduler.complete(c,2,0)
    assert not any(c['reason']=='evidence_revisit' for c in scheduler.plan([],2.5))
    assert any(c['reason']=='evidence_revisit' for c in scheduler.plan([],4))
    # Scheduling and visiting cannot extend evidence freshness without another match.
    assert not any(c['reason']=='evidence_revisit' for c in scheduler.plan([],8))


def test_single_frame_model_output_cannot_seed_pair_revisit():
    scheduler=BandScheduler(Settings().survey_ranges)
    scheduler.evidence=[dict(id='RF-1',low_mhz=5780,high_mhz=5790,score=.9,
        last_seen=1,evidence_kinds=['single_window'])]
    assert all(c['reason']=='blind_probe_no_power_gate' for c in scheduler.plan([],2))
