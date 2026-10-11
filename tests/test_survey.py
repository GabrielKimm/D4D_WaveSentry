import numpy as np
import pytest
from d4d.config import Settings
from d4d.detection import detection_record
from d4d.survey import find_candidates, Scheduler, Ledger, quality_flags, survey_boxes
from d4d.survey_radio import sweep_tiles, BLOCK


@pytest.mark.parametrize('kwargs', [dict(survey_low=0), dict(survey_high=6001),
    dict(survey_low=5000, survey_high=4000), dict(survey_low=1.5),
    dict(survey_zooms=1), dict(survey_threshold_db=0)])
def test_invalid_survey_settings(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_firmware_interleaved_frequency_coordinates():
    # Header low edge 2400 MHz, actual tuner 2407.5; a +5 MHz tone -> 2412.5 MHz.
    n = np.arange(8187)
    tone = 60 * np.exp(2j * np.pi * 0.25 * n)
    components = np.column_stack((tone.real, tone.imag)).astype(np.int8)
    raw = b'\x7f\x7f' + (2400000000).to_bytes(8, 'little') + components.tobytes()
    assert len(raw) == BLOCK
    edge, freq, db, clip = next(sweep_tiles(raw))
    assert edge == 2400
    assert freq[np.argmax(db)] == pytest.approx(2412.5)
    assert freq.min() == 2400 and freq.max() < 2415
    assert not np.any((freq >= 2405) & (freq < 2410))
    assert clip == 0
    with pytest.raises(ValueError):
        list(sweep_tiles(raw[:-2]))
    with pytest.raises(ValueError):
        list(sweep_tiles(b'\x00' * BLOCK))


def test_power_candidates_mixture_change_and_unknown_tiles():
    power = np.full(150, -90.0)
    power[20:30] = -65
    power[70:100] = -70
    power[130:135] = np.nan
    candidates = find_candidates(power, 2400)
    assert any(c['low_mhz'] <= 2420 and c['high_mhz'] >= 2430 for c in candidates)
    assert all(c['high_mhz'] - c['low_mhz'] <= 12 for c in candidates)
    assert not any(2530 <= c['center_mhz'] < 2535 for c in candidates)
    # Entire band rises: local contrast can be zero; same-frequency change still selects it.
    changed = find_candidates(np.full(100, -60.), 2400, previous=np.full(100, -80.))
    assert changed and max(c['change_db'] for c in changed) == 20
    assert find_candidates(np.full(50, np.nan), 1) == []
    assert find_candidates(np.full(50, -90.), 1) == []  # NOT a signal absence decision.


def candidate(center=2449.5):
    return dict(center_mhz=center, low_mhz=center - 5, high_mhz=center + 5,
                contrast_db=12, change_db=0, priority=30, peak_db=-60, reason='test')


def test_scheduler_fairness_blind_probe_and_bounded_grid():
    scheduler = Scheduler(1, 6000, slots=4)
    choices = [candidate(100 + i * 20) for i in range(20)]
    examined = set()
    for now in range(25):
        plan = scheduler.plan(choices, now)
        assert len(plan) <= 4 and plan[1]['reason'] == 'blind_probe_no_power_gate'
        for c in plan:
            examined.add(c['center_mhz'])
            scheduler.complete(c, now, 0.99)
    assert all(c['center_mhz'] in examined for c in choices)
    assert len(scheduler.visited) <= 1501
    assert scheduler.plan([], 50)[0]['reason'] == 'blind_probe_no_power_gate'


def frames(start, hit=True, flags=()):
    boxes = survey_boxes([detection_record('drone', .8, [0, 160, 640, 480])], 2449.5, 1, 6000) if hit else []
    return [dict(stamp=start + i * .02, quality_flags=list(flags), boxes=boxes,
                 signal=dict(rms_dbfs=-25 + i, clipped_pct=0)) for i in range(3)]


def test_observation_gaps_are_not_signal_duration_and_no_cross_gap_confirmation():
    ledger = Ledger('a', 0, 1000)
    first = ledger.observe(candidate(), frames(10), 10.1, 'gain16')
    assert first['observed_seconds'] == pytest.approx(.06)
    assert first['repeated_drone_shape'] and first['protocol_verified'] is False
    second = ledger.observe(candidate(), frames(20, hit=False), 20.1, 'gain16')
    assert second['id'] == first['id']  # same region, explicitly not same transmitter
    assert second['observed_seconds'] == pytest.approx(.12)
    assert second['gap_seconds'] > 9
    assert not second['repeated_drone_shape'] and second['drone_score'] == 0
    assert ledger.view(30)[0]['since_last_seconds'] > 9
    assert '미확인' in ledger.view(30)[0]['observation_state']


def test_quality_gain_and_frequency_changes_invalidate_power_comparison():
    ledger = Ledger('a', 0, 1000)
    first = ledger.observe(candidate(), frames(10), 10.1, 'gain16')
    invalid = ledger.observe(candidate(), frames(20, flags=['device_overrun']), 20.1, 'gain16')
    assert invalid['valid_seconds'] == pytest.approx(.06)
    assert invalid['observed_seconds'] == pytest.approx(.12)
    assert invalid['drone_score'] == 0
    assert invalid['power_delta_db'] is None
    changed = ledger.observe(candidate(), frames(30), 30.1, 'gain24')
    assert changed['id'] != first['id'] and changed['power_delta_db'] is None
    shifted = ledger.observe(candidate(2450.5), frames(40), 40.1, 'gain24')
    assert shifted['power_delta_db'] is None
    assert quality_flags(dict(overruns=1, stop_shortfalls=2), .2) == ['device_overrun', 'adc_clipping']
    assert quality_flags(dict(overruns=0, stop_shortfalls=2)) == []


def test_model_mapping_domains_edge_rejection_and_protocol_uncertainty():
    raw = [detection_record('drone', .9, [0, 160, 640, 480]),
           detection_record('drone', .99, [0, 0, 640, 640]),
           detection_record('wifi', .9, [0, 200, 600, 300])]
    boxes = survey_boxes(raw, 5800, 1, 6000)
    assert boxes[0]['low_mhz'] == 5795 and boxes[0]['high_mhz'] == 5805
    assert boxes[0]['in_target'] and boxes[0]['model_domain'] == 'unvalidated_frequency_domain'
    assert not boxes[1]['in_target'] and boxes[1]['edge_truncated']
    assert all(not b['protocol_verified'] for b in boxes)
    assert raw[0]['low_mhz'] == 2444.5  # fixed mode unaffected


def test_edge_refinement_cannot_starve_fairness_or_chain_forever():
    s = Scheduler(1, 6000, 4)
    raw = [detection_record('drone', .8, [0, 0, 640, 256])]
    boxes = survey_boxes(raw, 2449.5, 1, 6000)
    s.refine(candidate(), boxes, 1)
    assert len(s.refinements) == 1
    plan = s.plan([candidate()], 2)
    assert plan[0]['reason'] == 'fair_revisit'
    assert plan[1]['reason'] == 'blind_probe_no_power_gate'
    assert plan[2]['reason'] == 'edge_recenter'
    s.refine(plan[2], boxes, 3)
    assert not s.refinements


def test_changed_gain_creates_new_region_record_and_old_region_remains_unknown():
    ledger = Ledger('initial', 0, 1000)
    old = ledger.observe(candidate(), frames(5), 5.1, 'gain16')
    new = ledger.observe(candidate(), frames(7), 7.1, 'gain24')
    assert old['id'] != new['id']
    view = ledger.view(12)
    assert len(view) == 2
    assert all('공백' in row['observation_state'] for row in view)
    expired = ledger.observe(candidate(), frames(100), 100.1, 'gain24')
    assert expired['id'] != new['id']


def test_weak_5ghz_and_transient_candidate_are_not_starved_by_strong_24ghz():
    s = Scheduler(1, 6000, 4)
    strong = [dict(candidate(2410 + i * 12), priority=100) for i in range(6)]
    weak = dict(candidate(5820), priority=7)
    plan = s.plan(strong + [weak], 1)
    assert any(c['center_mhz'] == 5820 for c in plan)
    for c in plan:
        s.complete(c, 1, .9)
    # The brief 5GHz activity is still queued after the next scan misses it.
    plan = s.plan(strong, 3)
    assert any(c['center_mhz'] == 5820 for c in plan)
    assert any(c['reason'] == 'blind_probe_no_power_gate' for c in plan)
