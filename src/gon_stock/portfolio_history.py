from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from gon_stock.backtest import MINUTE, STRATEGY_ID, _bar_exit, _sessions, _signal_strength
from gon_stock.event_store import utc, validate_event
from gon_stock.portfolio import PortfolioLedger, _money

MARKETS = {
    'XNAS': (('NVDA', 'AMZN'), 'SPY', 'USD'),
    'XKRX': (('000660', '005380'), '069500', 'KRW'),
}
KST = ZoneInfo('Asia/Seoul')


def _risk_day(at):
    return (at.astimezone(KST) - timedelta(hours=7)).date()


def _prepare(rows, markets, settlements):
    bars, sessions, sources = {}, [], {}
    if not markets or set(markets) - MARKETS.keys():
        raise ValueError('invalid_markets')
    expected = {}
    for exchange, config in markets.items():
        targets, benchmark, currency = MARKETS[exchange]
        if set(config['symbols']) != {*targets, benchmark} or len(config['symbols']) != 3:
            raise ValueError('invalid_universe')
        expected.update({symbol: (exchange, currency) for symbol in config['symbols']})
        calendar = config['calendar']
        for session, (opened, closed) in zip(
            calendar['sessions'], _sessions(calendar, exchange), strict=True
        ):
            if (closed - opened).total_seconds() % 60 or _risk_day(opened) != _risk_day(closed):
                raise ValueError('invalid_session')
            try:
                settlement = utc(settlements[exchange][session['date']])
            except (KeyError, TypeError, ValueError):
                raise ValueError('missing_settlement') from None
            if settlement <= closed:
                raise ValueError('invalid_settlement')
            sessions.append((opened, closed, exchange, settlement))
    sessions.sort()
    if not sessions or any(a[1] > b[0] for a, b in zip(sessions, sessions[1:], strict=False)):
        raise ValueError('overlapping_or_empty_sessions')
    for raw in rows:
        row = validate_event({k: v for k, v in raw.items() if k != 'receipt_seq'})
        target = row['instrument']
        symbol = target['symbol']
        if symbol not in expected or (target['exchange'], target['currency']) != expected[symbol]:
            raise ValueError('invalid_instrument')
        if row['kind'] != 'bar' or row['correction_of'] is not None:
            raise ValueError('unsupported_corporate_revision')
        if row['endpoint'] not in ('kr_history', 'us_history', 'alpaca_history'):
            raise ValueError('history_only')
        if row['clock_status'] != 'verified' or row['event_time'] is None:
            raise ValueError('unverified_history_clock')
        at = utc(row['event_time'])
        if at.second or at.microsecond:
            raise ValueError('unaligned_history')
        key = (symbol, at)
        if key in bars:
            raise ValueError('duplicate_bar')
        values = {k: Decimal(v) for k, v in row['data'].items()}
        if values['volume'] <= 0:
            raise ValueError('zero_volume_history')
        bars[key] = values
        sources.setdefault(target['exchange'], set()).add((row['source'], row['environment']))
    if any(len(values) != 1 for values in sources.values()):
        raise ValueError('mixed_history_streams')
    expected_count = 0
    for opened, closed, exchange, _ in sessions:
        targets, benchmark, _ = MARKETS[exchange]
        at = opened
        while at < closed:
            for symbol in (*targets, benchmark):
                expected_count += 1
                if (symbol, at) not in bars:
                    raise ValueError('incomplete_history')
            at += MINUTE
    if len(bars) != expected_count:
        raise ValueError('out_of_session_history')
    return bars, sessions


def replay_history(rows, markets, settlements, *, capital, fixed_fx, roundtrip_bps):
    base = _money(capital)
    _money(fixed_fx)
    cost = _money(roundtrip_bps, zero=True) / 20000
    if cost * 2 >= 1:
        raise ValueError('invalid_cost_rate')
    bars, sessions = _prepare(rows, markets, settlements)
    ledger = PortfolioLedger(capital=capital, initial_fx=fixed_fx)
    history, daily, opened_positions = [], [], {}
    peak, drawdown = base, Decimal(0)

    def apply(at, action, marks, **extra):
        nonlocal peak, drawdown
        event = dict(
            at=at.isoformat(),
            action=action,
            fx=fixed_fx,
            marks={s: str(v) for s, v in marks.items()},
            **extra,
        )
        result = ledger.apply(event)
        result.update({k: event[k] for k in ('symbol', 'price') if k in event})
        result['fx'] = fixed_fx
        history.append(result)
        value = Decimal(result['nav'])
        peak = max(peak, value)
        drawdown = max(drawdown, 1 - value / peak)
        return result

    day, last_day = _risk_day(sessions[0][0]), _risk_day(sessions[-1][1])
    while day <= last_day:
        apply(datetime.combine(day, time(7), KST), 'mark', {})
        for opened, closed, exchange, settlement in sessions:
            if _risk_day(opened) != day:
                continue
            targets, benchmark, _ = MARKETS[exchange]
            at = opened
            while at < closed:
                marks = {s: bars[s, at]['open'] for s in targets}
                apply(at, 'mark', marks)
                latest = at - 2 * MINUTE
                if latest - 20 * MINUTE >= opened:
                    times = [latest - i * MINUTE for i in range(20, -1, -1)]
                    for symbol in sorted(targets):
                        values = [bars[symbol, t] for t in times]
                        strength = _signal_strength(
                            [b['close'] for b in values],
                            [bars[benchmark, t]['close'] for t in times],
                            [b['volume'] for b in values],
                        )
                        if strength is None:
                            continue
                        result = apply(
                            at,
                            'buy',
                            marks,
                            symbol=symbol,
                            price=str(marks[symbol]),
                            buy_rate=str(cost),
                            sell_rate=str(cost),
                            gates=True,
                        )
                        result.update(
                            signal_bar_at=latest.isoformat(),
                            decision_at=(latest + timedelta(seconds=80)).isoformat(),
                            strength=strength,
                        )
                        if result['quantity']:
                            opened_positions[symbol] = (at, marks[symbol])
                end = at + MINUTE
                marks = {s: bars[s, at]['close'] for s in targets}
                exits = {}
                for symbol, (entry_at, entry_price) in opened_positions.items():
                    reason, price = _bar_exit(
                        bars[symbol, at],
                        entry_price * Decimal('.99'),
                        entry_price * Decimal('1.015'),
                        end == min(entry_at + 30 * MINUTE, closed),
                    )
                    if reason:
                        exits[symbol] = (reason, price)
                        marks[symbol] = price
                apply(end, 'mark', marks)
                for symbol, (reason, price) in sorted(exits.items()):
                    result = apply(
                        end,
                        'sell',
                        marks,
                        symbol=symbol,
                        price=str(price),
                        settlement_at=settlement.isoformat(),
                    )
                    result['exit_reason'] = reason
                    del opened_positions[symbol]
                at = end
            if opened_positions:
                raise ValueError('unclosed_session')
        daily.append({**history[-1], 'risk_day': day.isoformat()})
        day += timedelta(days=1)
    counts = Counter(row['reason'] for row in history if row['action'] == 'buy')
    last = history[-1]
    result = {
        'status': 'EXPLORATORY_ONLY',
        'strategy_id': STRATEGY_ID,
        'availability_mode': 'historical_assumption_80_seconds',
        'fx_mode': 'fixed_reference_not_historical_fx',
        'execution_enabled': False,
        'assumptions': {
            'out_of_sample': False,
            'settlement': 'supplied_unverified_schedule',
            'execution': 'immediate_full_fill_assumed_gates',
            'order_state': 'entry_time_after_same_time_exits',
            'signal_priority': 'symbol_alphabetical',
            'market_key': 'US_session_group_not_listing_exchange',
        },
        'summary': dict(
            starting_nav=str(base),
            ending_nav=last['nav'],
            return_=last['return'],
            max_drawdown=str(drawdown),
            filled_entries=counts['filled'],
            rejected_entries=sum(counts.values()) - counts['filled'],
            rejection_reasons={k: v for k, v in counts.items() if k != 'filled'},
            unclosed=last['unclosed'],
            cash=last['cash'],
            receivables=last['receivables'],
        ),
        'ledger': history,
        'daily': daily,
    }
    references = {'cash': {'ending_nav': str(base), 'return': '0', 'fx_mode': 'fixed_reference'}}
    for exchange in markets:
        _, benchmark, currency = MARKETS[exchange]
        selected = [s for s in sessions if s[2] == exchange]
        first, last = selected[0][0], selected[-1][1] - MINUTE
        price, final_price = bars[benchmark, first]['open'], bars[benchmark, last]['close']
        rate = Decimal(fixed_fx) if currency == 'USD' else Decimal(1)
        quantity = int(base / 2 / (price * (1 + cost) * rate))
        ending = base + quantity * (final_price * (1 - cost) - price * (1 + cost)) * rate
        references[exchange] = dict(
            symbol=benchmark,
            quantity=quantity,
            ending_nav=str(ending),
            entry_at=first.isoformat(),
            exit_at=(last + MINUTE).isoformat(),
            entry_price=str(price),
            exit_price=str(final_price),
            mode='50_percent_budget_buy_hold_plus_cash_no_risk_stops',
        )
        references[exchange]['return'] = str(ending / base - 1)
    result['references'] = references
    result['summary']['return'] = result['summary'].pop('return_')
    return result
