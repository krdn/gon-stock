import importlib
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D

import pytest
from test_backtest import fixture_rows

from gon_stock.event_store import canonical, digest, utc


def api():
    try:
        return importlib.import_module('gon_stock.portfolio_history')
    except ModuleNotFoundError:
        pytest.fail('historical portfolio replay required')


def fixture():
    original, calendar = fixture_rows()
    rows = []
    for row in original:
        symbols = ['NVDA', 'AMZN'] if row['instrument']['symbol'] == 'TEST' else ['SPY']
        for symbol in symbols:
            r = deepcopy(row)
            r['instrument']['symbol'] = symbol
            r.update(id=f'{symbol}-{len(rows)}', endpoint='us_history', receipt_seq=len(rows) + 1)
            rows.append(r)
    markets = {'XNAS': {'symbols': ['NVDA', 'AMZN', 'SPY'], 'calendar': calendar}}
    settlements = {'XNAS': {'2026-11-12': '2026-11-16T22:00:00Z'}}
    return rows, markets, settlements


def replay(rows, markets, settlements, cost='25'):
    return api().replay_history(
        rows, markets, settlements, capital='10000000', fixed_fx='1000', roundtrip_bps=cost
    )


def test_two_slots_stop_first_and_capital_return():
    r = replay(*fixture())
    buys = [row for row in r['ledger'] if row['action'] == 'buy' and row['quantity']]
    sells = [row for row in r['ledger'] if row['action'] == 'sell']
    assert len(buys) == len(sells) == 2
    assert {row['symbol'] for row in buys} == {'NVDA', 'AMZN'}
    assert all(row['at'] == '2026-11-12T14:52:00+00:00' for row in buys)
    assert all(row['exit_reason'] == 'stop' for row in sells)
    assert r['summary']['filled_entries'] == 2
    assert r['summary']['unclosed'] == []
    q = buys[0]['quantity']
    loss = 2 * q * D('100.44') * (D('.01') + D('.00125') * D('1.99')) * 1000
    assert D(r['summary']['ending_nav']) == D('10000000') - loss
    assert D(r['summary']['return']) == -loss / D('10000000')
    assert r['status'] == 'EXPLORATORY_ONLY'


def test_missing_or_duplicate_history_rejects_entire_run():
    rows, markets, settlements = fixture()
    with pytest.raises(ValueError, match='incomplete_history'):
        replay(rows[:-1], markets, settlements)
    with pytest.raises(ValueError, match='duplicate_bar'):
        replay([*rows, rows[-1]], markets, settlements)


def test_future_prices_cannot_change_entry_quantity_or_signal():
    rows, markets, settlements = fixture()
    original = replay(rows, markets, settlements)
    changed = deepcopy(rows)
    for row in changed:
        if utc(row['event_time']) >= utc('2026-11-12T14:52:00Z'):
            row['data']['high'] = '500'
            row['data']['low'] = '1'
    result = replay(changed, markets, settlements)

    def first_buys(r):
        return [(x['symbol'], x['quantity'], x['at']) for x in r['ledger'] if x['action'] == 'buy']

    assert first_buys(result) == first_buys(original)


def test_risk_day_marks_and_funding_conservation_over_weekend():
    rows, markets, settlements = fixture()
    first_day = markets['XNAS']['calendar']['sessions'][0]
    second_day = {
        k: (utc(v) + timedelta(days=4)).isoformat() if k in ('open', 'close') else '2026-11-16'
        for k, v in first_day.items()
    }
    calendar = markets['XNAS']['calendar']
    calendar['sessions'].append(second_day)
    calendar.pop('sha256')
    calendar['sha256'] = digest(canonical(calendar))
    later = deepcopy(rows)
    for row in later:
        row['event_time'] = (utc(row['event_time']) + timedelta(days=4)).isoformat()
        row['received_at'] = (utc(row['received_at']) + timedelta(days=4)).isoformat()
        row['id'] += '-later'
    settlements['XNAS']['2026-11-16'] = '2026-11-18T22:00:00Z'
    result = replay([*rows, *later], markets, settlements)
    assert len(result['daily']) == 5
    assert all(row['unclosed'] == [] for row in result['daily'])
    assert result['summary']['filled_entries'] == 3
    later_buys = [
        r for r in result['ledger'] if r['action'] == 'buy' and r['at'].startswith('2026-11-16')
    ]
    assert [r['quantity'] for r in later_buys] == [1, 0]
    assert result['summary']['rejected_entries'] == 1


def test_missing_settlement_and_non_history_source_rejected():
    rows, markets, settlements = fixture()
    with pytest.raises(ValueError, match='settlement'):
        replay(rows, markets, {})
    rows[0]['endpoint'] = 'us_bars'
    with pytest.raises(ValueError, match='history_only'):
        replay(rows, markets, settlements)


def test_target_exit_is_valued_at_fill_not_later_bar_close():
    rows, markets, settlements = fixture()
    for row in rows:
        if row['instrument']['symbol'] != 'SPY' and row['event_time'].startswith(
            '2026-11-12T14:52'
        ):
            row['data'].update(high='103', low='100', close='100')
    result = replay(rows, markets, settlements, cost='0')
    assert D(result['summary']['max_drawdown']) == 0
    assert all(
        row['exit_reason'] == 'target' for row in result['ledger'] if row['action'] == 'sell'
    )


def test_cash_and_passive_reference_use_same_capital_fx_and_costs():
    result = replay(*fixture())
    assert result['references']['cash']['return'] == '0'
    ref = result['references']['XNAS']
    assert ref['symbol'] == 'SPY'
    assert ref['quantity'] == 49
    assert D(ref['ending_nav']) == D('9987750')
    assert D(ref['return']) == D('-.001225')


def test_two_markets_share_daily_loss_budget():
    rows, markets, settlements = fixture()
    kr = deepcopy(rows)
    mapping = {'NVDA': '000660', 'AMZN': '005380', 'SPY': '069500'}
    for row in kr:
        row['instrument'].update(
            exchange='XKRX', currency='KRW', symbol=mapping[row['instrument']['symbol']]
        )
        row['event_time'] = (utc(row['event_time']) - timedelta(hours=14, minutes=30)).isoformat()
        row['received_at'] = (utc(row['received_at']) - timedelta(hours=14, minutes=30)).isoformat()
        row['endpoint'] = 'kr_history'
        row['id'] += '-kr'
    calendar = deepcopy(markets['XNAS']['calendar'])
    calendar.pop('sha256')
    calendar['exchange'] = 'XKRX'
    for session in calendar['sessions']:
        for k in ('open', 'close'):
            session[k] = (utc(session[k]) - timedelta(hours=14, minutes=30)).isoformat()
    calendar['sha256'] = digest(canonical(calendar))
    markets['XKRX'] = dict(symbols=['000660', '005380', '069500'], calendar=calendar)
    settlements['XKRX'] = {'2026-11-12': '2026-11-17T22:00:00Z'}
    r = replay([*kr, *rows], markets, settlements)
    assert r['summary']['filled_entries'] == 4
    assert D(r['summary']['ending_nav']) >= D('9900000')
    us_buys = [x for x in r['ledger'] if x['action'] == 'buy' and x['symbol'] in ('NVDA', 'AMZN')]
    assert us_buys[1]['quantity'] < 24


def test_output_carries_counterfactual_assumptions():
    r = replay(*fixture())
    assert r['assumptions']['out_of_sample'] is False
    assert r['assumptions']['settlement'] == 'supplied_unverified_schedule'
    assert r['assumptions']['execution'] == 'immediate_full_fill_assumed_gates'
    assert r['assumptions']['order_state'] == 'entry_time_after_same_time_exits'


def test_session_close_liquidates_and_future_close_volume_cannot_change_first_entry():
    rows, markets, settlements = fixture()
    for row in rows:
        if utc(row['event_time']) >= utc('2026-11-12T14:51:00Z'):
            row['data'].update(open='100.5', high='100.6', low='100.4', close='100.5', volume='1')
    r = replay(rows, markets, settlements)
    first = [e for e in r['ledger'] if e['action'] == 'buy' and e['quantity']]
    assert len(first) == 2
    assert all(e['signal_bar_at'] == '2026-11-12T14:50:00+00:00' for e in first)
    exits = [e for e in r['ledger'] if e['action'] == 'sell']
    assert all(
        e['exit_reason'] == 'time'
        and e['at'] == markets['XNAS']['calendar']['sessions'][0]['close']
        for e in exits
    )
    changed = deepcopy(rows)
    for row in changed:
        if utc(row['event_time']) >= utc('2026-11-12T14:51:00Z'):
            row['data'].update(high='500', low='1', close='400', volume='99999999')
    other = replay(changed, markets, settlements)
    other_first = [e for e in other['ledger'] if e['action'] == 'buy' and e['quantity']][:2]
    assert [(e['symbol'], e['quantity'], e['signal_bar_at']) for e in first] == [
        (e['symbol'], e['quantity'], e['signal_bar_at']) for e in other_first
    ]


def test_thirty_minute_expiry_before_session_close():
    rows, markets, settlements = fixture()
    for row in rows:
        if utc(row['event_time']) >= utc('2026-11-12T14:51:00Z'):
            row['data'].update(open='100.5', high='100.6', low='100.4', close='100.5', volume='1')
    originals = deepcopy(rows[-3:])
    for offset in range(1, 31):
        for row in originals:
            r = deepcopy(row)
            r['event_time'] = (utc(row['event_time']) + timedelta(minutes=offset)).isoformat()
            r['received_at'] = (utc(row['received_at']) + timedelta(minutes=offset)).isoformat()
            r['id'] += f'-{offset}'
            rows.append(r)
    calendar = markets['XNAS']['calendar']
    calendar['sessions'][0]['close'] = '2026-11-12T15:36:00+00:00'
    calendar.pop('sha256')
    calendar['sha256'] = digest(canonical(calendar))
    r = replay(rows, markets, settlements)
    exits = [e for e in r['ledger'] if e['action'] == 'sell']
    assert len(exits) == 2
    assert all(e['exit_reason'] == 'time' and e['at'] == '2026-11-12T15:22:00+00:00' for e in exits)
