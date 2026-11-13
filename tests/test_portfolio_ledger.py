from copy import deepcopy
from decimal import Decimal as D

import pytest

from gon_stock import portfolio


def event(action='mark', at='2026-11-13T09:00:00+09:00', **kw):
    return dict(at=at, action=action, fx='1000', marks={}, **kw)


def run(events, **kw):
    fn = getattr(portfolio, 'replay_ledger', None)
    assert callable(fn), 'portfolio ledger replay must exist'
    return fn(events, capital='10000000', initial_fx='1000', **kw)


def buy(symbol='000660', price='100000', **kw):
    e = event(
        'buy', symbol=symbol, price=price, buy_rate='0.001', sell_rate='0.001', gates=True, **kw
    )
    e['marks'] = {symbol: price}
    return e


def test_cash_cost_nav_settlement_and_no_reuse():
    b = buy()
    s = event(
        'sell',
        at='2026-11-13T09:10:00+09:00',
        symbol='000660',
        price='101000',
        settlement_at='2026-11-17T09:00:00+09:00',
    )
    s['marks'] = {'000660': '101000'}
    r = run([b, s])
    assert r[0]['quantity'] == 24
    assert D(r[0]['nav']) == D('9997600')
    assert D(r[1]['nav']) == D('10019176')
    assert D(r[1]['cash']['KRW']) == D('2597600')
    assert D(r[1]['receivables']['KRW']) == D('2421576')
    assert D(r[1]['return']) == D('.0019176')


def test_fx_cash_loss_latches_daily_stop_after_recovery():
    loss = event()
    loss['fx'] = '970'
    r = run([loss, buy('NVDA', '100', at='2026-11-13T23:00:00+09:00')])
    assert D(r[0]['nav']) == D('9850000')
    assert r[1]['reason'] == 'loss_stop'
    assert r[1]['quantity'] == 0


def test_cross_market_and_missing_marks():
    b = buy()
    us = buy('NVDA', '100', at='2026-11-13T23:00:00+09:00')
    us['marks']['000660'] = '100000'
    assert run([b, us])[-1]['reason'] == 'other_market_open'
    del us['marks']['000660']
    with pytest.raises(ValueError, match='missing_mark'):
        run([b, us])


def test_integer_slot_and_risk_budget():
    b = buy(price='1254000')
    b['buy_rate'] = b['sell_rate'] = '0.00125'
    assert run([b])[0]['quantity'] == 1
    assert run([buy(price='3000000')])[0]['quantity'] == 0
    first = buy()
    second = buy('005380', '100000')
    second['marks']['000660'] = '100000'
    r = run([first, second])
    assert len(r[-1]['positions']) == 2
    assert D(r[-1]['remaining_risk']) == D('42448')


def test_day_boundary_required_and_settlement_conserves_nav():
    s = event('sell', symbol='000660', price='100000', settlement_at='2026-11-14T07:00:00+09:00')
    s['marks'] = {'000660': '100000'}
    next_day = event(at='2026-11-14T07:00:00+09:00')
    r = run([buy(), s, next_day])
    assert r[-1]['nav'] == r[-2]['nav']
    assert D(r[-1]['receivables']['KRW']) == 0
    assert D(r[-1]['daily_return']) == 0
    next_day['at'] = '2026-11-14T09:00:00+09:00'
    with pytest.raises(ValueError, match='risk_day_boundary'):
        run([buy(), s, next_day])


@pytest.mark.parametrize(
    'field,value', [('fx', 'NaN'), ('price', '-1'), ('buy_rate', '1'), ('gates', False)]
)
def test_invalid_or_unverified_entry(field, value):
    b = buy()
    b[field] = value
    if field == 'gates':
        assert run([b])[0]['reason'] == 'gates_unverified'
    else:
        with pytest.raises(ValueError):
            run([b])


def test_determinism_and_input_unchanged():
    data = [buy()]
    original = deepcopy(data)
    assert run(data) == run(data)
    assert data == original


def test_unsettled_proceeds_are_never_spendable():
    events = []
    for minute in ('00', '01', '02'):
        b = buy(at=f'2026-11-13T09:{minute}:00+09:00')
        s = event(
            'sell',
            at=f'2026-11-13T09:{minute}:30+09:00',
            symbol='000660',
            price='100000',
            settlement_at='2026-11-17T09:00:00+09:00',
        )
        s['marks'] = {'000660': '100000'}
        events.extend([b, s])
    r = run(events)
    assert [r[i]['quantity'] for i in (0, 2, 4)] == [24, 24, 1]
    assert D(r[-1]['cash']['KRW']) == D('95100')
    assert D(r[-1]['receivables']['KRW']) == D('4895100')


def test_common_kr_us_risk_budget_after_losses():
    b = buy()
    b['buy_rate'] = b['sell_rate'] = '0.00125'
    b2 = buy('005380')
    b2['buy_rate'] = b2['sell_rate'] = '0.00125'
    b2['marks']['000660'] = '100000'
    s1 = event('sell', symbol='000660', price='99000', settlement_at='2026-11-17T09:00:00+09:00')
    s1['marks'] = {'000660': '99000', '005380': '100000'}
    s2 = event('sell', symbol='005380', price='99000', settlement_at='2026-11-17T09:00:00+09:00')
    s2['marks'] = {'005380': '99000'}
    us1 = buy('NVDA', '100', at='2026-11-13T23:00:00+09:00')
    us2 = buy('AMZN', '100', at='2026-11-13T23:01:00+09:00')
    us2['marks']['NVDA'] = '100'
    r = run([b, b2, s1, s2, us1, us2])
    assert r[-2]['quantity'] == 24
    assert r[-1]['quantity'] == 9
    assert D(r[-1]['remaining_risk']) == D('493')


def test_cumulative_stop_survives_day_reset_and_unclosed_preserved():
    e = event()
    e['fx'] = '890'
    boundary = event(at='2026-11-14T07:00:00+09:00')
    assert run([e, boundary, buy(at='2026-11-14T09:00:00+09:00')])[-1]['reason'] == 'loss_stop'
    m = event(at='2026-11-13T15:30:00+09:00')
    m['marks'] = {'000660': '90000'}
    r = run([buy(), m])
    assert r[-1]['unclosed'] == ['000660']
    assert r[-1]['daily_stop'] is True


def test_stale_order_and_naive_timestamp_rejected():
    with pytest.raises(ValueError):
        run([event(at='2026-11-13T09:00:00')])
    with pytest.raises(ValueError, match='event_order'):
        run([event(), event(at='2026-11-13T08:00:00+09:00')])


def test_cli_private_replay_and_no_overwrite(tmp_path, monkeypatch):
    import json
    import sys

    from gon_stock.ledger_cli import main

    monkeypatch.chdir(tmp_path)
    private = tmp_path / '.private'
    private.mkdir()
    source, output = private / 'input.json', private / 'output.json'
    source.write_text(
        json.dumps(
            dict(kind='synthetic-ledger-v1', capital='10000000', initial_fx='1000', events=[buy()])
        )
    )
    monkeypatch.setattr(sys, 'argv', ['ledger', '--input', str(source), '--output', str(output)])
    main()
    result = json.loads(output.read_text())
    assert result['rows'][0]['nav'] == '9997600.000'
    assert result['actual_portfolio_performance'] == 'NOT_RUN'
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_existing_marked_position_above_thirty_percent_blocks_new_entry():
    second = buy('005380', at='2026-11-13T09:01:00+09:00')
    second['marks']['000660'] = '130000'
    assert run([buy(), second])[-1]['quantity'] == 0
    assert run([buy(), second])[-1]['reason'] == 'budget_or_cash'


@pytest.mark.parametrize('marks,fx', [([], '1000'), ({}, '1E+999999')])
def test_cli_malformed_input_exits_cleanly(tmp_path, monkeypatch, marks, fx):
    import json
    import sys

    from gon_stock.ledger_cli import main

    monkeypatch.chdir(tmp_path)
    private = tmp_path / '.private'
    private.mkdir()
    e = event()
    e.update(marks=marks, fx=fx)
    source, output = private / 'in.json', private / 'out.json'
    source.write_text(
        json.dumps(
            dict(kind='synthetic-ledger-v1', capital='10000000', initial_fx='1000', events=[e])
        )
    )
    monkeypatch.setattr(sys, 'argv', ['ledger', '--input', str(source), '--output', str(output)])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert not output.exists()


def test_us_holdings_and_receivables_fx_revaluation():
    b = buy('NVDA', '100')
    m = event()
    m.update(fx='1100', marks={'NVDA': '100'})
    s = event('sell', symbol='NVDA', price='100', settlement_at='2026-11-14T07:00:00+09:00')
    s.update(fx='1100', marks={'NVDA': '100'})
    after = event()
    after['fx'] = '1200'
    r = run([b, m, s, after])
    assert D(r[1]['nav']) == D('10497360')
    assert D(r[2]['nav']) == D('10494720')
    assert D(r[3]['nav']) == D('10994240')


def test_trade_risk_cap_and_overdue_duplicate_guards():
    b = buy()
    b['buy_rate'] = b['sell_rate'] = '0.006'
    assert run([b])[0]['quantity'] == 22
    assert run([buy(), buy()])[-1]['reason'] == 'position_limit'
    late = buy('005380', at='2026-11-13T09:30:00+09:00')
    late['marks']['000660'] = '100000'
    assert run([buy(), late])[-1]['reason'] == 'overdue_position'


@pytest.mark.parametrize(
    'kind', ['no_position', 'settlement_must_be_future', 'fill_mark_mismatch', 'risk_day_boundary']
)
def test_invalid_fill_or_boundary(kind):
    s = event('sell', symbol='000660', price='100000', settlement_at='2026-11-17T09:00:00+09:00')
    s['marks'] = {'000660': '100000'}
    data = [buy(), s]
    if kind == 'no_position':
        data = [s]
    elif kind == 'settlement_must_be_future':
        s['settlement_at'] = s['at']
    elif kind == 'fill_mark_mismatch':
        s['price'] = '100001'
    else:
        data = [event(), event(at='2026-11-15T07:00:00+09:00')]
    with pytest.raises(ValueError, match=kind):
        run(data)


def test_nonterminating_initial_fx_nav_precision():
    e = event()
    e['fx'] = '1361.89'
    result = portfolio.replay_ledger([e], capital='10000000', initial_fx='1361.89')
    assert abs(D(result[0]['nav']) - D('10000000')) < D('1e-15')


def test_incremental_ledger_matches_batch_and_stops_after_invalid_event():
    cls = getattr(portfolio, 'PortfolioLedger', None)
    assert cls is not None, 'incremental ledger required for historical execution feedback'
    ledger = cls(capital='10000000', initial_fx='1000')
    assert ledger.apply(buy()) == run([buy()])[0]
    invalid = event()
    invalid['marks'] = {}
    with pytest.raises(ValueError, match='missing_mark'):
        ledger.apply(invalid)
    with pytest.raises(ValueError, match='ledger_failed'):
        ledger.apply(event())
