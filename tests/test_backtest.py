import importlib
from datetime import timedelta

import pytest
from test_event_store import event, stamp

from gon_stock.event_store import canonical, digest, validate_event


def api():
    try:
        return importlib.import_module('gon_stock.backtest')
    except ModuleNotFoundError:
        pytest.fail('P3 backtest is not implemented')


ASSET = {'exchange': 'XNAS', 'symbol': 'TEST', 'currency': 'USD'}
BENCHMARK = {'exchange': 'XNAS', 'symbol': 'BENCH', 'currency': 'USD'}
COSTS = {
    'commission_each': '1',
    'tax_sell': '2',
    'spread_each': '1',
    'slippage_each': '2',
    'fx_each': '0',
}


def fixture_rows(both_hit=True):
    rows = []
    start = stamp('2026-11-12T14:30:00Z')
    for minute in range(36):
        for target in (ASSET, BENCHMARK):
            price = 100 + minute * 0.02 if target == ASSET else 100
            values = {
                'open': f'{price:.2f}',
                'high': f'{price + 0.01:.2f}',
                'low': f'{price - 0.01:.2f}',
                'close': f'{price:.2f}',
                'volume': '2000' if minute == 20 and target == ASSET else '100',
            }
            if minute == 22 and target == ASSET and both_hit:
                values.update({'high': '103', 'low': '98'})
            source = event(
                f'{target["symbol"]}_{minute}',
                instrument=target,
                event_time=(start + timedelta(minutes=minute)).isoformat(),
                received_at=(start + timedelta(minutes=minute + 1, seconds=2)).isoformat(),
                data=values,
            )
            rows.append({'receipt_seq': len(rows) + 1, **validate_event(source)})
    calendar = {
        'schema_version': 1,
        'exchange': 'XNAS',
        'calendar': 'synthetic',
        'library_version': 'fixture',
        'start': '2026-11-12',
        'end': '2026-11-12',
        'sessions': [
            {
                'date': '2026-11-12',
                'open': start.isoformat(),
                'close': (start + timedelta(minutes=36)).isoformat(),
            }
        ],
    }
    calendar['sha256'] = digest(canonical(calendar))
    return rows, calendar


def test_next_open_and_stop_first_include_each_cost_component():
    rows, calendar = fixture_rows()
    result = api().backtest(rows, calendar, [ASSET], BENCHMARK, COSTS)
    assert len(result['trades']) == 1
    trade = result['trades'][0]
    assert trade['decision_at'] == '2026-11-12T14:51:02+00:00'
    assert trade['entry_at'] == '2026-11-12T14:52:00+00:00'
    assert trade['exit_reason'] == 'stop'
    assert trade['gross_return'] == pytest.approx(-0.01)
    assert trade['cost_return'] == pytest.approx(0.000994)
    assert trade['net_return'] == pytest.approx(-0.010994)
    assert trade['stress_return'] == pytest.approx(-0.011988)


def test_gap_below_stop_uses_worse_open():
    rows, calendar = fixture_rows(False)
    for row in rows:
        if row['id'] == 'TEST_23':
            row['data'] = {'open': '98', 'high': '99', 'low': '97', 'close': '98', 'volume': '100'}
    trade = api().backtest(rows, calendar, [ASSET], BENCHMARK, COSTS)['trades'][0]
    assert trade['exit_reason'] == 'stop'
    assert trade['gross_return'] < -0.02


def test_timeout_exits_before_session_end_and_no_overnight():
    rows, calendar = fixture_rows(False)
    trade = api().backtest(rows, calendar, [ASSET], BENCHMARK, COSTS)['trades'][0]
    assert trade['exit_reason'] == 'time'
    assert trade['exit_at'] == calendar['sessions'][0]['close']


def test_later_observation_cannot_change_prior_signal():
    rows, calendar = fixture_rows()
    original = api().backtest(rows, calendar, [ASSET], BENCHMARK, COSTS)['trades'][0]
    later = dict(next(row for row in rows if row['id'] == 'TEST_20'))
    later.update(
        {
            'id': 'later',
            'receipt_seq': 1000,
            'received_at': '2026-11-12T15:06:00+00:00',
            'data': {'open': '100', 'high': '100', 'low': '90', 'close': '90', 'volume': '1'},
        }
    )
    changed = api().backtest([*rows, later], calendar, [ASSET], BENCHMARK, COSTS)['trades'][0]
    assert changed == original


def test_future_received_history_creates_no_retrospective_trades():
    rows, calendar = fixture_rows()
    for row in rows:
        row['received_at'] = '2026-11-13T16:00:00+00:00'
    assert api().backtest(rows, calendar, [ASSET], BENCHMARK, COSTS)['trades'] == []


def test_missing_outcome_is_unresolved_not_profitable_trade():
    rows, calendar = fixture_rows(False)
    rows = [row for row in rows if row['id'] != 'TEST_23']
    result = api().backtest(rows, calendar, [ASSET], BENCHMARK, COSTS)
    assert result['trades'] == []
    assert result['unresolved'] == 1


def test_costs_reject_negative_nonfinite_and_unknown_fields():
    rows, calendar = fixture_rows()
    for costs in [
        {**COSTS, 'tax_sell': '-1'},
        {**COSTS, 'commission_each': 'NaN'},
        {**COSTS, 'unexpected': '1'},
    ]:
        with pytest.raises(ValueError):
            api().backtest(rows, calendar, [ASSET], BENCHMARK, costs)


def test_corrections_and_actions_are_not_silently_back_adjusted():
    rows, calendar = fixture_rows()
    rows[-1]['correction_of'] = 'BENCH_34'
    with pytest.raises(ValueError, match='unsupported_corporate_revision'):
        api().backtest(rows, calendar, [ASSET], BENCHMARK, COSTS)


def test_research_universe_cannot_use_benchmark_or_different_market():
    rows, calendar = fixture_rows()
    with pytest.raises(ValueError):
        api().backtest(rows, calendar, [BENCHMARK], BENCHMARK, COSTS)
