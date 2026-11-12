import importlib
from datetime import date, timedelta

import pytest


def api():
    try:
        return importlib.import_module('gon_stock.evaluation')
    except ModuleNotFoundError:
        pytest.fail('P3 evaluation is not implemented')


def synthetic_trades():
    days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(90)]
    trades = []
    for index, day in enumerate(days):
        for sample in range(5):
            net = 0.012 if sample < (3 if index < 30 else 4) else -0.011
            trades.append(
                {
                    'decision_at': day + 'T14:31:02+00:00',
                    'entry_at': day + f'T{15 + sample:02}:00:00+00:00',
                    'exit_at': day + f'T{15 + sample:02}:01:00+00:00',
                    'strength': 'weak',
                    'net_return': net,
                    'stress_return': net - 0.001,
                    'cost_return': 0.001,
                }
            )
    manifest = {
        'train_end': days[29],
        'calibration_end': days[59],
        'test_end': days[-1],
        'source_kind': 'synthetic',
        'environment': 'synthetic',
        'verified': {
            'bar_labels': False,
            'calendar': False,
            'coverage': False,
            'corporate_actions': False,
            'universe_pit': False,
            'costs': False,
        },
    }
    return trades, days, manifest


def test_wilson_matches_nist_reference():
    lower, upper = api().wilson(8, 30)
    assert lower == pytest.approx(0.141827, abs=0.000001)
    assert upper == pytest.approx(0.444480, abs=0.000001)
    assert api().wilson(0, 0) is None


def test_embargo_and_boundary_purge():
    trades, days, manifest = synthetic_trades()
    crossing = dict(trades[149])
    crossing['exit_at'] = days[30] + 'T15:00:00+00:00'
    trades[149] = crossing
    parts = api().split_trades(trades, days, manifest)
    assert len(parts['train']) == 149
    assert len(parts['calibration']) == 140
    assert len(parts['test']) == 140
    assert parts['purged'] == 21


def test_calibration_uses_no_test_labels_and_reports_reliability():
    trades, days, manifest = synthetic_trades()
    original = api().evaluate(
        {'trades': trades, 'unresolved': 0, 'no_entry_bar': 0}, days, manifest
    )
    assert original['status'] == 'BLOCKED'
    assert 'synthetic_or_unverified_history' in original['blockers']
    assert original['probabilities'] == {}
    assert original['metrics']['brier'] < original['metrics']['constant_brier']
    assert original['counts']['test'] == 140
    assert original['reliability'][0]['observed_frequency'] == 0.8
    for trade in trades[-140:]:
        trade['net_return'] = -0.02
        trade['stress_return'] = -0.03
    changed = api().evaluate({'trades': trades, 'unresolved': 0, 'no_entry_bar': 0}, days, manifest)
    assert changed['calibration'] == original['calibration']
    assert changed['metrics']['mean_net_return'] < 0


def test_insufficient_sample_never_emits_usable_probability():
    trades, days, manifest = synthetic_trades()
    result = api().evaluate(
        {'trades': trades[:10], 'unresolved': 0, 'no_entry_bar': 0}, days, manifest
    )
    assert result['status'] == 'BLOCKED'
    assert result['probabilities'] == {}
    assert 'insufficient_test_trades' in result['blockers']


def test_block_bootstrap_is_deterministic_and_nonpositive_for_losses():
    trades, days, _ = synthetic_trades()
    first = api().block_interval(trades, days)
    assert first == api().block_interval(trades, days)
    for trade in trades:
        trade['net_return'] = -0.01
    lower, upper = api().block_interval(trades, days)
    assert lower == pytest.approx(-0.01)
    assert upper == pytest.approx(-0.01)


def test_real_declarations_cannot_override_missing_outcomes():
    trades, days, manifest = synthetic_trades()
    manifest.update({'source_kind': 'observed', 'environment': 'real'})
    manifest['verified'] = dict.fromkeys(manifest['verified'], True)
    result = api().evaluate({'trades': trades, 'unresolved': 1, 'no_entry_bar': 0}, days, manifest)
    assert result['status'] == 'BLOCKED'
    assert 'unresolved_positions' in result['blockers']


def test_negative_cost_stress_is_rejected_when_evidence_is_complete():
    trades, days, manifest = synthetic_trades()
    manifest.update({'source_kind': 'observed', 'environment': 'real'})
    manifest['verified'] = dict.fromkeys(manifest['verified'], True)
    for trade in trades:
        trade['stress_return'] = -0.02
    result = api().evaluate({'trades': trades, 'unresolved': 0, 'no_entry_bar': 0}, days, manifest)
    assert result['status'] == 'REJECTED'
    assert 'nonpositive_stress_expectancy' in result['failures']
    assert result['probabilities'] == {}


def test_nonfinite_returns_and_overlapping_boundaries_are_refused():
    trades, days, manifest = synthetic_trades()
    trades[0]['net_return'] = float('nan')
    with pytest.raises(ValueError):
        api().evaluate({'trades': trades, 'unresolved': 0, 'no_entry_bar': 0}, days, manifest)
    manifest['train_end'] = manifest['test_end']
    with pytest.raises(ValueError):
        api().split_trades([], days, manifest)


def test_probability_excludes_group_without_holdout_observations():
    trades, days, manifest = synthetic_trades()
    # Strong has ample train/calibration samples but no holdout evidence.
    trades += [{**trade, 'strength': 'strong'} for trade in trades[:300]]
    manifest.update({'source_kind': 'observed', 'environment': 'real'})
    manifest['verified'] = dict.fromkeys(manifest['verified'], True)
    result = api().evaluate({'trades': trades, 'unresolved': 0, 'no_entry_bar': 0}, days, manifest)
    assert result['status'] == 'CANDIDATE_PASS'
    assert set(result['probabilities']) == {'weak'}
