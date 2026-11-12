import math
import random
from collections import defaultdict
from datetime import date
from statistics import NormalDist, mean

from gon_stock.event_store import utc

VERIFICATIONS = {'bar_labels', 'calendar', 'coverage', 'corporate_actions', 'universe_pit', 'costs'}


def wilson(wins: int, count: int):
    if type(wins) is not int or type(count) is not int or not 0 <= wins <= count:
        raise ValueError('invalid_counts')
    if count == 0:
        return None
    z = NormalDist().inv_cdf(0.975)
    p = wins / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    radius = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [max(0, center - radius), min(1, center + radius)]


def split_trades(trades, session_days, manifest):
    days = sorted(set(session_days))
    if days != session_days or any(date.fromisoformat(day).isoformat() != day for day in days):
        raise ValueError('invalid_sessions')
    boundaries = [manifest[key] for key in ('train_end', 'calibration_end', 'test_end')]
    parsed = [date.fromisoformat(day) for day in boundaries]
    if not parsed[0] < parsed[1] < parsed[2]:
        raise ValueError('invalid_split')
    training, calibration, testing = boundaries
    train_days = {day for day in days if day <= training}
    calibration_days = {day for day in days if training < day <= calibration}
    calibration_days -= set(sorted(calibration_days)[:2])
    test_days = {day for day in days if calibration < day <= testing}
    test_days -= set(sorted(test_days)[:2])
    phases = {'train': train_days, 'calibration': calibration_days, 'test': test_days}
    result = {
        'train': [],
        'calibration': [],
        'test': [],
        'purged': 0,
        'test_days': sorted(test_days),
    }
    for trade in trades:
        decision, entry, exit_time = [
            utc(trade[key]) for key in ('decision_at', 'entry_at', 'exit_at')
        ]
        if not decision < entry < exit_time:
            raise ValueError('invalid_trade_times')
        trade_days = {stamp.date().isoformat() for stamp in (decision, entry, exit_time)}
        phase = next((key for key, allowed in phases.items() if trade_days <= allowed), None)
        if phase is None:
            result['purged'] += 1
        else:
            result[phase].append(trade)
    return result


def block_interval(trades, session_days):
    if not trades or not session_days:
        return None
    groups = defaultdict(list)
    for trade in trades:
        groups[utc(trade['exit_at']).date().isoformat()].append(trade['net_return'])
    days = [groups[day] for day in session_days]
    randomizer = random.Random(20261112)
    block = min(5, len(days))
    samples = []
    for _ in range(1000):
        draw = []
        while len(draw) < len(days):
            start = randomizer.randrange(len(days) - block + 1)
            draw.extend(days[start : start + block])
        values = [value for day in draw[: len(days)] for value in day]
        samples.append(mean(values) if values else 0.0)
    samples.sort()
    return [samples[24], samples[974]]


def _drawdown(trades):
    equity, peak, maximum = 1.0, 1.0, 0.0
    for trade in sorted(trades, key=lambda value: utc(value['exit_at'])):
        equity *= max(0.0, 1.0 + trade['net_return'])
        peak = max(peak, equity)
        maximum = max(maximum, 1 - equity / peak)
    return maximum


def evaluate(simulation, session_days, manifest):
    verified = manifest.get('verified')
    if (
        not isinstance(verified, dict)
        or set(verified) != VERIFICATIONS
        or any(type(value) is not bool for value in verified.values())
    ):
        raise ValueError('invalid_verifications')
    if manifest.get('source_kind') not in ('observed', 'vendor_history', 'synthetic'):
        raise ValueError('invalid_source_kind')
    if manifest.get('environment') not in ('mock', 'real', 'synthetic'):
        raise ValueError('invalid_environment')
    trades = simulation['trades']
    for trade in trades:
        if trade['strength'] not in ('weak', 'strong'):
            raise ValueError('invalid_strength')
        for key in ('net_return', 'stress_return', 'cost_return'):
            if type(trade[key]) not in (float, int) or not math.isfinite(trade[key]):
                raise ValueError('invalid_return')
        if trade['cost_return'] < 0 or trade['stress_return'] > trade['net_return']:
            raise ValueError('invalid_cost_return')
    parts = split_trades(trades, session_days, manifest)
    train, calibration, test = [parts[key] for key in ('train', 'calibration', 'test')]
    model = {}
    for group in ('weak', 'strong'):
        training = [trade for trade in train if trade['strength'] == group]
        fitting = [trade for trade in calibration if trade['strength'] == group]
        model[group] = {
            'train_count': len(training),
            'calibration_count': len(fitting),
            'raw_probability': (
                (sum(trade['net_return'] > 0 for trade in training) + 1) / (len(training) + 2)
            )
            if len(training) >= 30
            else None,
            'calibrated_probability': (
                (sum(trade['net_return'] > 0 for trade in fitting) + 1) / (len(fitting) + 2)
            )
            if len(training) >= 30 and len(fitting) >= 30
            else None,
        }
    test_trade_days = {utc(trade['entry_at']).date().isoformat() for trade in test}
    blockers = []
    if manifest['source_kind'] != 'observed' or manifest['environment'] != 'real':
        blockers.append('synthetic_or_unverified_history')
    blockers.extend('unverified_' + key for key in sorted(verified) if not verified[key])
    if len(test) < 100:
        blockers.append('insufficient_test_trades')
    if len(test_trade_days) < 20:
        blockers.append('insufficient_test_sessions')
    if simulation['unresolved']:
        blockers.append('unresolved_positions')
    if simulation['no_entry_bar']:
        blockers.append('missing_entry_bars')
    if any(model[trade['strength']]['calibrated_probability'] is None for trade in test):
        blockers.append('uncalibrated_groups')
    baseline = (sum(trade['net_return'] > 0 for trade in train) + 1) / (len(train) + 2)
    scored = [
        trade for trade in test if model[trade['strength']]['calibrated_probability'] is not None
    ]
    brier = (
        mean(
            (model[t['strength']]['calibrated_probability'] - (t['net_return'] > 0)) ** 2
            for t in scored
        )
        if scored
        else None
    )
    constant_brier = (
        mean((baseline - (t['net_return'] > 0)) ** 2 for t in scored) if scored else None
    )
    reliability = []
    calibration_mismatch = False
    for group in ('weak', 'strong'):
        selected = [trade for trade in scored if trade['strength'] == group]
        if not selected:
            continue
        wins = sum(trade['net_return'] > 0 for trade in selected)
        interval = wilson(wins, len(selected))
        predicted = model[group]['calibrated_probability']
        reliability.append(
            {
                'group': group,
                'count': len(selected),
                'predicted': predicted,
                'observed_frequency': wins / len(selected),
                'wilson95': interval,
            }
        )
        if len(selected) < 30:
            blockers.append('insufficient_reliability_' + group)
        elif not interval[0] <= predicted <= interval[1]:
            calibration_mismatch = True
    interval = block_interval(test, parts['test_days'])
    average = mean(t['net_return'] for t in test) if test else None
    stress = mean(t['stress_return'] for t in test) if test else None
    failures = []
    if average is not None and average <= 0:
        failures.append('nonpositive_net_expectancy')
    if stress is not None and stress <= 0:
        failures.append('nonpositive_stress_expectancy')
    if interval is not None and interval[0] <= 0:
        failures.append('uncertain_expectancy')
    if brier is not None and brier > constant_brier:
        failures.append('worse_brier')
    if calibration_mismatch:
        failures.append('calibration_mismatch')
    status = 'BLOCKED' if blockers else 'REJECTED' if failures else 'CANDIDATE_PASS'
    probabilities = (
        {row['group']: row['predicted'] for row in reliability}
        if status == 'CANDIDATE_PASS'
        else {}
    )
    return {
        'status': status,
        'blockers': blockers,
        'failures': failures,
        'counts': {
            'train': len(train),
            'calibration': len(calibration),
            'test': len(test),
            'test_sessions': len(test_trade_days),
            'purged': parts['purged'],
        },
        'calibration': model,
        'probabilities': probabilities,
        'reliability': reliability,
        'metrics': {
            'mean_net_return': average,
            'mean_stress_return': stress,
            'expectancy_block95': interval,
            'brier': brier,
            'constant_brier': constant_brier,
            'win_rate_wilson95': wilson(sum(t['net_return'] > 0 for t in test), len(test)),
            'unit_return_drawdown': _drawdown(test),
        },
    }
