from copy import deepcopy
from datetime import timedelta
from decimal import Decimal as D

import pytest
from test_portfolio_history import fixture

from gon_stock.event_store import canonical, digest, utc
from gon_stock.portfolio_history import replay_history


def kr_fixture(minutes=66):
    source, markets, _ = fixture()
    mapping = {'NVDA': '000660', 'AMZN': '005380', 'SPY': '069500'}
    rows = []
    for row in source:
        r = deepcopy(row)
        r['instrument'].update(
            exchange='XKRX', currency='KRW', symbol=mapping[r['instrument']['symbol']]
        )
        for key in ('event_time', 'received_at'):
            r[key] = (utc(r[key]) - timedelta(hours=14, minutes=30)).isoformat()
        r['endpoint'] = 'kr_history'
        if utc(r['event_time']) >= utc('2026-11-12T00:21:00Z'):
            r['data'].update(open='100.5', high='100.6', low='100.4', close='100.5', volume='1')
        rows.append(r)
    for minute in range(36, minutes):
        for row in rows[105:108]:
            r = deepcopy(row)
            for key in ('event_time', 'received_at'):
                r[key] = (utc(row[key]) + timedelta(minutes=minute - 35)).isoformat()
            r['id'] += f'-{minute}'
            rows.append(r)
    calendar = deepcopy(markets['XNAS']['calendar'])
    calendar.pop('sha256')
    calendar['exchange'] = 'XKRX'
    calendar['sessions'][0].update(
        open='2026-11-12T00:00:00+00:00',
        close=(utc('2026-11-12T00:00:00Z') + timedelta(minutes=minutes)).isoformat(),
    )
    calendar['sha256'] = digest(canonical(calendar))
    return (
        rows,
        {'XKRX': {'symbols': list(mapping.values()), 'calendar': calendar}},
        {'XKRX': {'2026-11-12': '2026-11-17T22:00:00Z'}},
    )


def pause(start, resume, kind='circuit_breaker', symbols=None):
    return dict(
        exchange='XKRX',
        symbols=symbols or ['000660', '005380', '069500'],
        kind=kind,
        start=f'2026-11-12T00:{start}Z',
        resume=f'2026-11-12T{resume}Z',
        source='fixture official market event',
        source_sha256=digest('fixture'),
    )


def remove_nontrading(rows, event):
    start, resume = utc(event['start']), utc(event['resume'])
    return [
        r
        for r in rows
        if not (
            r['instrument']['symbol'] in event['symbols']
            and start <= utc(r['event_time'])
            and utc(r['event_time']) + timedelta(minutes=1) <= resume
        )
    ]


def run(rows, markets, settlements, events):
    return replay_history(
        rows,
        markets,
        settlements,
        capital='10000000',
        fixed_fx='1000',
        roundtrip_bps='0',
        interruptions=events,
    )


def test_halt_crossing_deadline_sells_at_reopening_gap_price_not_stale_stop():
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '01:00:10')
    rows = remove_nontrading(rows, event)
    for row in rows:
        if row['event_time'].startswith('2026-11-12T01:00'):
            row['data'].update(open='98', high='98.1', low='97.9', close='98')
    r = run(rows, markets, settlements, [event])
    sells = [x for x in r['ledger'] if x['action'] == 'sell']
    assert len(sells) == 2
    assert all(
        x['at'] == '2026-11-12T01:00:10+00:00'
        and x['price'] == '98'
        and x['exit_reason'] == 'resumption_stop'
        for x in sells
    )
    assert not any(
        utc(event['start']) < utc(x['at']) < utc(event['resume'])
        for x in r['ledger']
        if x['action'] in ('buy', 'sell')
    )
    buys = [x for x in r['ledger'] if x['action'] == 'buy' and x['quantity']]
    assert D(r['summary']['ending_nav']) == D('10000000') + sum(
        D(x['quantity']) * (D('98') - D('100.5')) for x in buys
    )
    assert r['summary']['unclosed'] == []


def test_expired_exit_uses_reopening_open_even_when_price_recovers():
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '01:00:10')
    r = run(remove_nontrading(rows, event), markets, settlements, [event])
    sells = [x for x in r['ledger'] if x['action'] == 'sell']
    assert len(sells) == 2
    assert all(x['exit_reason'] == 'resumption_time' and x['price'] == '100.5' for x in sells)


@pytest.mark.parametrize('minutes', [36, 56])
def test_closing_auction_is_single_price_exit_and_not_a_new_entry(minutes):
    rows, markets, settlements = kr_fixture(minutes)
    event = pause(f'{minutes - 10}:00', f'00:{minutes}:00', 'closing_auction')
    rows = remove_nontrading(rows, event)
    for source in rows[-3:]:
        r = deepcopy(source)
        r.update(
            id=r['id'] + '-closing', event_time=event['resume'], received_at='2026-11-12T01:00:00Z'
        )
        r['data'].update(open='102', high='102', low='102', close='102', volume='20000')
        rows.append(r)
    result = run(rows, markets, settlements, [event])
    sells = [x for x in result['ledger'] if x['action'] == 'sell']
    assert len(sells) == 2
    assert all(
        x['exit_reason'] == 'closing_auction'
        and x['price'] == '102'
        and utc(x['at']) == utc(event['resume'])
        for x in sells
    )
    assert not any(
        utc(x['at']) >= utc(event['start']) for x in result['ledger'] if x['action'] == 'buy'
    )
    assert result['references']['XKRX']['exit_price'] == '102'
    with pytest.raises(ValueError, match='incomplete_history'):
        run(rows[:-1], markets, settlements, [event])
    rows[-1]['data']['high'] = '103'
    with pytest.raises(ValueError, match='invalid_auction_price'):
        run(rows, markets, settlements, [event])


def test_partial_halt_start_bar_uses_end_exclusive_execution_bound():
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '01:00:10')
    rows = remove_nontrading(rows, event)
    for row in rows:
        if row['event_time'].startswith('2026-11-12T00:25'):
            row['data']['low'] = '98'
    r = run(rows, markets, settlements, [event])
    sells = [x for x in r['ledger'] if x['action'] == 'sell']
    assert len(sells) == 2
    assert all(utc(x['at']) == utc(event['start']) for x in sells)
    assert all(x['fill_window']['end_exclusive'] is True for x in sells)


def test_one_symbol_vi_does_not_stop_other_symbol_or_forward_fill_signal():
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '00:30:10', 'volatility_interruption', ['000660'])
    rows = remove_nontrading(rows, event)
    for row in rows:
        if row['instrument']['symbol'] == '005380' and row['event_time'].startswith(
            '2026-11-12T00:27'
        ):
            row['data']['low'] = '98'
    r = run(rows, markets, settlements, [event])
    sells = [x for x in r['ledger'] if x['action'] == 'sell']
    assert any(x['symbol'] == '005380' and x['at'] == '2026-11-12T00:28:00+00:00' for x in sells)
    assert not any(
        x['symbol'] == '000660' and utc(event['start']) < utc(x['at']) < utc(event['resume'])
        for x in sells
    )
    assert any(
        '000660' in x['carried_marks']
        for x in r['ledger']
        if utc(event['start']) < utc(x['at']) < utc(event['resume'])
    )
    assert all(
        utc(x['signal_bar_at']) < utc(event['start'])
        for x in r['ledger']
        if x['action'] == 'buy' and x['symbol'] == '000660'
    )


def test_ordinary_missing_and_trade_inside_documented_pause_reject():
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '01:00:10')
    good = remove_nontrading(rows, event)
    with pytest.raises(ValueError, match='incomplete_history'):
        run(good[1:], markets, settlements, [event])
    with pytest.raises(ValueError, match='nontrading_history'):
        run(rows, markets, settlements, [event])


def test_bad_or_overlapping_event_evidence_rejects():
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '01:00:10')
    good = remove_nontrading(rows, event)
    with pytest.raises(ValueError, match='overlapping_interruptions'):
        run(good, markets, settlements, [event, event])
    event['source_sha256'] = ''
    with pytest.raises(ValueError, match='invalid_interruption'):
        run(good, markets, settlements, [event])


def test_opening_vi_requires_first_reopening_bar_and_blocks_early_signal():
    rows, markets, settlements = kr_fixture()
    event = pause('00:00', '00:02:27', 'opening_volatility_interruption', ['000660'])
    rows = remove_nontrading(rows, event)
    result = run(rows, markets, settlements, [event])
    assert not any(x['symbol'] == '000660' for x in result['ledger'] if x['action'] == 'buy')
    without_resume = [
        x
        for x in rows
        if not (
            x['instrument']['symbol'] == '000660' and x['event_time'].startswith('2026-11-12T00:02')
        )
    ]
    with pytest.raises(ValueError, match='incomplete_history'):
        run(without_resume, markets, settlements, [event])


def test_halted_until_close_cannot_fake_exit_at_last_mark():
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '01:06:00')
    with pytest.raises(ValueError, match='unclosed_session'):
        run(remove_nontrading(rows, event), markets, settlements, [event])


def test_future_resumption_price_cannot_change_pre_halt_entries():
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '01:00:10')
    rows = remove_nontrading(rows, event)
    original = run(rows, markets, settlements, [event])
    changed = deepcopy(rows)
    for row in changed:
        if utc(row['event_time']) >= utc('2026-11-12T01:00:00Z'):
            row['data'].update(open='200', high='200', low='200', close='200', volume='999999')
    other = run(changed, markets, settlements, [event])

    def before(r):
        return [x for x in r['ledger'] if utc(x['at']) < utc(event['start'])]

    assert before(original) == before(other)
    assert all(
        x['price'] == '200' and x['exit_reason'] == 'resumption_target'
        for x in other['ledger']
        if x['action'] == 'sell'
    )


def test_interruption_iterator_preserves_schedule_and_provenance():
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '01:00:10')
    rows = remove_nontrading(rows, event)
    assert run(rows, markets, settlements, iter([event])) == run(
        rows, markets, settlements, [event]
    )


@pytest.mark.parametrize('change', [{'source_sha256': None}, {'symbols': '000660'}, {'kind': []}])
def test_malformed_interruption_raises_validation_error(change):
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '01:00:10')
    event.update(change)
    with pytest.raises(ValueError, match='invalid_interruption'):
        run(rows, markets, settlements, [event])


@pytest.mark.parametrize(
    'event,error',
    [
        (
            pause('25:10', '00:25:30', 'volatility_interruption', ['000660']),
            'ambiguous_transition_bar',
        ),
        (pause('25:00', '00:30:00', 'closing_auction'), 'invalid_closing_auction'),
        (
            pause('01:00', '00:02:00', 'opening_volatility_interruption', ['000660']),
            'invalid_opening_interruption',
        ),
        (pause('25:00', '00:30:00', symbols=['000660']), 'incomplete_market_interruption'),
        (pause('25:00', '02:00:00'), 'interruption_outside_session'),
    ],
)
def test_invalid_schedule_rejected_before_replay(event, error):
    with pytest.raises(ValueError, match=error):
        run(*kr_fixture(), [event])


def test_kr_halt_gap_loss_blocks_later_us_entries_in_same_risk_day():
    rows, markets, settlements = kr_fixture()
    event = pause('25:15', '01:00:10')
    rows = remove_nontrading(rows, event)
    for row in rows:
        if row['event_time'].startswith('2026-11-12T01:00'):
            row['data'].update(open='98', high='98.1', low='97.9', close='98')
    us_rows, us_markets, us_settlements = fixture()
    result = run(rows + us_rows, markets | us_markets, settlements | us_settlements, [event])
    buys = [r for r in result['ledger'] if r['action'] == 'buy' and r['symbol'] in ('NVDA', 'AMZN')]
    assert len(buys) == 2
    assert all(r['reason'] == 'loss_stop' and r['quantity'] == 0 and r['daily_stop'] for r in buys)
    assert result['summary']['filled_entries'] == 2
    assert result['summary']['unclosed'] == []
