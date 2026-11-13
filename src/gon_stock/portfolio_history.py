import re
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from gon_stock.backtest import MINUTE, STRATEGY_ID, _bar_exit, _sessions, _signal_strength
from gon_stock.event_store import canonical, digest, utc, validate_event
from gon_stock.portfolio import PortfolioLedger, _money

MARKETS = {
    'XNAS': (('NVDA', 'AMZN'), 'SPY', 'USD'),
    'XKRX': (('000660', '005380'), '069500', 'KRW'),
}
KST = ZoneInfo('Asia/Seoul')


def _risk_day(at):
    return (at.astimezone(KST) - timedelta(hours=7)).date()


def _trading_periods(sessions, markets, interruptions):
    pauses = defaultdict(list)
    kinds = {
        'circuit_breaker',
        'volatility_interruption',
        'opening_volatility_interruption',
        'closing_auction',
    }
    fields = ('exchange', 'kind', 'start', 'resume', 'source', 'source_sha256')
    for event in interruptions:
        if (
            not isinstance(event, dict)
            or any(not isinstance(event.get(k), str) for k in fields)
            or not isinstance(event.get('symbols'), (list, tuple))
            or any(not isinstance(s, str) for s in event['symbols'])
        ):
            raise ValueError('invalid_interruption')
        exchange = event['exchange']
        symbols = event['symbols']
        start, resume = utc(event['start']), utc(event['resume'])
        kind = event['kind']
        if (
            exchange != 'XKRX'
            or exchange not in markets
            or kind not in kinds
            or not symbols
            or len(set(symbols)) != len(symbols)
            or not set(symbols) <= set(markets[exchange]['symbols'])
            or not event['source'].strip()
            or not re.fullmatch('[0-9a-f]{64}', event['source_sha256'])
            or start >= resume
        ):
            raise ValueError('invalid_interruption')
        session = next(
            ((a, b) for a, b, x, _ in sessions if x == exchange and a <= start < resume <= b), None
        )
        if session is None:
            raise ValueError('interruption_outside_session')
        opened, closed = session
        if kind in {'circuit_breaker', 'closing_auction'} and set(symbols) != set(
            markets[exchange]['symbols']
        ):
            raise ValueError('incomplete_market_interruption')
        if kind == 'closing_auction' and (resume != closed or start.second or start.microsecond):
            raise ValueError('invalid_closing_auction')
        if kind == 'opening_volatility_interruption' and start != opened:
            raise ValueError('invalid_opening_interruption')
        for symbol in symbols:
            pauses[symbol, opened].append((start, resume, kind))
    periods = {}
    for opened, closed, exchange, _ in sessions:
        for symbol in markets[exchange]['symbols']:
            windows = sorted(pauses[symbol, opened])
            if any(b[0] < a[1] for a, b in zip(windows, windows[1:], strict=False)):
                raise ValueError('overlapping_interruptions')
            at = opened
            while at < closed:
                segments = [(at, at + MINUTE)]
                for start, resume, _ in windows:
                    remaining = []
                    for lo, hi in segments:
                        if start >= hi or resume <= lo:
                            remaining.append((lo, hi))
                        else:
                            if lo < start:
                                remaining.append((lo, start))
                            if resume < hi:
                                remaining.append((resume, hi))
                    segments = remaining
                if len(segments) > 1:
                    raise ValueError('ambiguous_transition_bar')
                if segments:
                    lo, hi = segments[0]
                    resumption = any(resume == lo for _, resume, _ in windows)
                    periods[symbol, at] = (lo, hi, resumption, False)
                at += MINUTE
            if any(kind == 'closing_auction' for _, _, kind in windows):
                periods[symbol, closed] = (closed, closed, False, True)
    return periods


def _prepare(rows, markets, settlements, interruptions):
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
    periods = _trading_periods(sessions, markets, interruptions)
    if periods.keys() - bars.keys():
        raise ValueError('incomplete_history')
    if bars.keys() - periods.keys():
        raise ValueError('nontrading_history' if interruptions else 'out_of_session_history')
    for key, (_, _, _, auction) in periods.items():
        if auction and len({bars[key][k] for k in ('open', 'high', 'low', 'close')}) != 1:
            raise ValueError('invalid_auction_price')
    return bars, sessions, periods


def replay_history(
    rows, markets, settlements, *, capital, fixed_fx, roundtrip_bps, interruptions=()
):
    base = _money(capital)
    _money(fixed_fx)
    cost = _money(roundtrip_bps, zero=True) / 20000
    if cost * 2 >= 1:
        raise ValueError('invalid_cost_rate')
    interruptions = list(interruptions)
    bars, sessions, periods = _prepare(rows, markets, settlements, interruptions)
    ledger = PortfolioLedger(capital=capital, initial_fx=fixed_fx)
    history, daily, opened_positions = [], [], {}
    peak, drawdown = base, Decimal(0)
    mark_times = {}

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
        result['carried_marks'] = {
            s: mark_times[s].isoformat()
            for s in result['positions']
            if s in mark_times and mark_times[s] < at
        }
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
            marks, mark_times = {}, {}
            events = defaultdict(list)
            at = opened
            while at <= closed:
                for symbol in targets:
                    if (symbol, at) not in periods:
                        continue
                    lo, hi, resumed, auction = periods[symbol, at]
                    if auction:
                        events[lo, 'auction'].append((symbol, at, resumed))
                    else:
                        events[lo, 'open'].append((symbol, at, resumed))
                        events[hi, 'close'].append((symbol, at, resumed))
                at += MINUTE
            priority = {'close': 0, 'auction': 1, 'open': 2}
            for at, phase in sorted(events, key=lambda key: (key[0], priority[key[1]])):
                batch = events[at, phase]
                exits = {}
                for symbol, bar_at, resumed in batch:
                    data = bars[symbol, bar_at]
                    marks[symbol] = data['open'] if phase == 'open' else data['close']
                    mark_times[symbol] = at
                    if symbol not in opened_positions:
                        continue
                    entry_at, entry_price = opened_positions[symbol]
                    stop, target = entry_price * Decimal('.99'), entry_price * Decimal('1.015')
                    deadline = min(entry_at + 30 * MINUTE, closed)
                    reason, price = None, None
                    if phase == 'auction':
                        reason, price = 'closing_auction', data['close']
                    elif phase == 'open' and resumed:
                        reason = (
                            'resumption_stop'
                            if data['open'] <= stop
                            else 'resumption_target'
                            if data['open'] >= target
                            else 'resumption_time'
                            if at >= deadline
                            else None
                        )
                        price = data['open']
                    elif phase == 'close':
                        reason, price = _bar_exit(data, stop, target, at >= deadline)
                    if reason:
                        lo, hi, _, auction = periods[symbol, bar_at]
                        exits[symbol] = (
                            reason,
                            price,
                            {
                                'start': lo.isoformat(),
                                'end': (hi if phase == 'close' else at).isoformat(),
                                'end_exclusive': phase == 'close',
                            },
                        )
                        marks[symbol] = price
                apply(at, 'mark', marks)
                for symbol, (reason, price, window) in sorted(exits.items()):
                    result = apply(
                        at,
                        'sell',
                        marks,
                        symbol=symbol,
                        price=str(price),
                        settlement_at=settlement.isoformat(),
                    )
                    result.update(exit_reason=reason, fill_window=window)
                    del opened_positions[symbol]
                if phase != 'open':
                    continue
                latest = at - 2 * MINUTE
                if at.second or at.microsecond or latest - 20 * MINUTE < opened:
                    continue
                times = [latest - i * MINUTE for i in range(20, -1, -1)]
                for symbol, bar_at, _ in sorted(batch):
                    if bar_at != at or any(
                        (s, t) not in bars for s in (symbol, benchmark) for t in times
                    ):
                        continue
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
        'market_structure': {
            'interruptions_sha256': digest(canonical(interruptions)),
            'events': len(interruptions),
            'valuation': 'last_observation_carry_not_tradable',
            'time_model': 'bar_interval_bounds_with_nominal_auction_resume',
        },
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
        first = next(
            (
                at
                for s, at in sorted(periods)
                if s == benchmark and selected[0][0] <= at < selected[0][1]
            ),
            None,
        )
        if first is None:
            raise ValueError('missing_reference_open')
        closed = selected[-1][1]
        last = closed if (benchmark, closed) in periods else closed - MINUTE
        if (benchmark, last) not in bars or periods[benchmark, last][1] != closed:
            raise ValueError('missing_reference_close')
        price, final_price = bars[benchmark, first]['open'], bars[benchmark, last]['close']
        rate = Decimal(fixed_fx) if currency == 'USD' else Decimal(1)
        quantity = int(base / 2 / (price * (1 + cost) * rate))
        ending = base + quantity * (final_price * (1 - cost) - price * (1 + cost)) * rate
        references[exchange] = dict(
            symbol=benchmark,
            quantity=quantity,
            ending_nav=str(ending),
            entry_at=periods[benchmark, first][0].isoformat(),
            exit_at=periods[benchmark, last][1].isoformat(),
            entry_price=str(price),
            exit_price=str(final_price),
            mode='50_percent_budget_buy_hold_plus_cash_no_risk_stops',
        )
        references[exchange]['return'] = str(ending / base - 1)
    result['references'] = references
    result['summary']['return'] = result['summary'].pop('return_')
    return result
