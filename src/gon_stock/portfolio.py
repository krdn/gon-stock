import math
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import combinations
from statistics import correlation, median, stdev

from gon_stock.event_store import instrument


def _daily(rows, days):
    result = {}
    for row in rows:
        day = date.fromisoformat(row['date']).isoformat()
        if day not in days:
            continue
        if day in result:
            raise ValueError('duplicate_daily_date')
        values = {key: Decimal(str(row[key])) for key in ('open', 'high', 'low', 'close', 'volume')}
        if any(not value.is_finite() or value <= 0 for value in values.values()):
            raise ValueError('invalid_daily_number')
        if (
            not values['low']
            <= min(values['open'], values['close'])
            <= max(values['open'], values['close'])
            <= values['high']
        ):
            raise ValueError('invalid_daily_ohlc')
        result[day] = values
    if set(result) != set(days):
        raise ValueError('missing_daily_sessions')
    return result


def screen_market(candidates, raw, adjusted, session_dates, asof):
    cutoff = date.fromisoformat(asof).isoformat()
    dates = [date.fromisoformat(day).isoformat() for day in session_dates]
    if dates != sorted(set(dates)):
        raise ValueError('invalid_reference_sessions')
    dates = [day for day in dates if day <= cutoff][-61:]
    if len(dates) != 61:
        raise ValueError('insufficient_reference_sessions')
    symbols = [item['symbol'] for item in candidates]
    if len(set(symbols)) != len(symbols):
        raise ValueError('duplicate_candidates')
    for item in candidates:
        instrument({k: item[k] for k in ('exchange', 'symbol', 'currency')})
        if not isinstance(item['group'], str) or not item['group']:
            raise ValueError('invalid_concentration_group')
    stats, returns, excluded = [], {}, {}
    for item in candidates:
        symbol = item['symbol']
        try:
            prices = _daily(raw[symbol], dates)
            adj = _daily(adjusted[symbol], dates)
            changes = [
                float(adj[b]['close'] / adj[a]['close'] - 1)
                for a, b in zip(dates, dates[1:], strict=False)
            ]
            sigma = stdev(changes)
            if not math.isfinite(sigma) or sigma <= 0:
                raise ValueError('invalid_return_variance')
            stats.append(
                {
                    **item,
                    'last_close': str(prices[dates[-1]]['close']),
                    'median_turnover20': str(
                        median(prices[d]['close'] * prices[d]['volume'] for d in dates[-20:])
                    ),
                    'annualized_volatility60': sigma * math.sqrt(252),
                    'return_observations': len(changes),
                }
            )
            returns[symbol] = changes
        except (ValueError, KeyError, TypeError, InvalidOperation, OverflowError) as exc:
            excluded[symbol] = str(exc) if isinstance(exc, ValueError) else 'invalid_daily_input'
    stats.sort(key=lambda item: (-Decimal(item['median_turnover20']), item['symbol']))
    correlations = {
        '|'.join(sorted((a, b))): correlation(returns[a], returns[b])
        for a, b in combinations(returns, 2)
    }
    selected, reasons = [], {}
    for item in stats:
        symbol = item['symbol']
        if any(item['group'] == value['group'] for value in selected):
            reasons[symbol] = 'same_group'
        elif any(
            abs(correlations['|'.join(sorted((symbol, value['symbol'])))]) >= 0.8
            for value in selected
        ):
            reasons[symbol] = 'high_correlation'
        elif len(selected) == 2:
            reasons[symbol] = 'slots_full'
        else:
            selected.append(item)
            reasons[symbol] = 'selected'
    return {
        'asof': cutoff,
        'first_session': dates[0],
        'last_session': dates[-1],
        'session_count': len(dates),
        'statistics': stats,
        'correlations': correlations,
        'selected': [item['symbol'] for item in selected],
        'selection_reasons': reasons,
        'excluded': excluded,
        'status': 'RESEARCH_COMPOSITION_ONLY',
    }


def _money(value, *, zero=False):
    if not isinstance(value, str):
        raise ValueError('decimal_string_required')
    number = Decimal(value)
    if not number.is_finite() or number < 0 or (not zero and number == 0):
        raise ValueError('invalid_amount')
    return number


class PortfolioLedger:
    def __init__(self, *, capital, initial_fx):
        self._base, first_fx = _money(capital), _money(initial_fx)
        self._cash = {'KRW': self._base / 2, 'USD': self._base / 2 / first_fx}
        self._currencies = {'000660': 'KRW', '005380': 'KRW', 'NVDA': 'USD', 'AMZN': 'USD'}
        self._positions, self._pending = {}, []
        self._previous = self._day = None
        self._day_nav = self._base
        self._daily_stop = self._total_stop = self._failed = False

    def apply(self, event):
        if self._failed:
            raise ValueError('ledger_failed')
        try:
            return self._apply(event)
        except (ValueError, KeyError, TypeError, ArithmeticError, AttributeError):
            self._failed = True
            raise

    def _apply(self, event):
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        from gon_stock.event_store import utc

        at = utc(event['at'])
        if self._previous is not None and at < self._previous:
            raise ValueError('event_order')
        fx = _money(event['fx'])
        rates = {'KRW': Decimal(1), 'USD': fx}
        marks = {symbol: _money(price) for symbol, price in event['marks'].items()}
        if not self._positions.keys() <= marks.keys():
            raise ValueError('missing_mark')
        local = at.astimezone(ZoneInfo('Asia/Seoul'))
        risk_day = (local - timedelta(hours=7)).date()
        action = event['action']
        if action not in {'mark', 'buy', 'sell'}:
            raise ValueError('invalid_action')
        if self._day is not None and risk_day != self._day:
            if local.hour != 7 or local.minute or local.second or local.microsecond:
                raise ValueError('risk_day_boundary_required')
            if action != 'mark' or (risk_day - self._day).days != 1:
                raise ValueError('risk_day_boundary_required')
        for item in self._pending[:]:
            if item['at'] <= at:
                self._cash[item['currency']] += item['amount']
                self._pending.remove(item)

        def nav():
            return (
                sum(value * rates[currency] for currency, value in self._cash.items())
                + sum(item['amount'] * rates[item['currency']] for item in self._pending)
                + sum(
                    p['quantity'] * marks[s] * rates[p['currency']]
                    for s, p in self._positions.items()
                )
            )

        before = nav()
        if self._day is not None and risk_day != self._day:
            self._day_nav, self._daily_stop = before, False
        self._day = risk_day
        self._daily_stop |= self._day_nav - before >= self._base * Decimal('.01')
        self._total_stop |= self._base - before >= self._base * Decimal('.05')

        def remaining_risk():
            residual = sum(
                p['quantity']
                * max(Decimal(0), marks[s] - p['stop'] * (1 - p['sell_rate']))
                * rates[p['currency']]
                for s, p in self._positions.items()
            )
            return max(
                Decimal(0),
                self._base * Decimal('.01') - max(Decimal(0), self._day_nav - nav()) - residual,
            )

        quantity, reason = 0, 'marked'
        if action in {'buy', 'sell'}:
            symbol = event['symbol']
            if symbol not in self._currencies or symbol not in marks:
                raise ValueError('invalid_symbol_or_mark')
            currency = self._currencies[symbol]
            rate, price = rates[currency], _money(event['price'])
            if price != marks[symbol]:
                raise ValueError('fill_mark_mismatch')
            if action == 'buy':
                buy_rate = _money(event['buy_rate'], zero=True)
                sell_rate = _money(event['sell_rate'], zero=True)
                if buy_rate + sell_rate >= 1:
                    raise ValueError('invalid_cost_rate')
                stop = price * Decimal('.99')
                unit_cash = price * (1 + buy_rate)
                unit_risk = (unit_cash - stop * (1 - sell_rate)) * rate
                gross = sum(
                    p['quantity'] * marks[s] * rates[p['currency']]
                    for s, p in self._positions.items()
                )
                committed = sum(
                    p['quantity'] * p['unit_cash'] * rates[p['currency']]
                    for p in self._positions.values()
                )
                if event.get('gates') is not True:
                    reason = 'gates_unverified'
                elif self._daily_stop or self._total_stop:
                    reason = 'loss_stop'
                elif any(p['currency'] != currency for p in self._positions.values()):
                    reason = 'other_market_open'
                elif len(self._positions) >= 2 or symbol in self._positions:
                    reason = 'position_limit'
                elif any(
                    at - p['opened'] >= timedelta(minutes=30) for p in self._positions.values()
                ):
                    reason = 'overdue_position'
                else:
                    quantity = max(
                        0,
                        int(
                            min(
                                self._base * Decimal('.25') / (unit_cash * rate),
                                max(Decimal(0), self._base * Decimal('.50') - committed)
                                / (unit_cash * rate),
                                max(Decimal(0), self._base * Decimal('.60') - gross)
                                / (price * rate),
                                self._base * Decimal('.005') / unit_risk,
                                remaining_risk() / unit_risk,
                                self._cash[currency] / unit_cash,
                            )
                        ),
                    )
                    reason = 'filled' if quantity else 'budget_or_cash'
                    if quantity:
                        self._cash[currency] -= quantity * unit_cash
                        self._positions[symbol] = dict(
                            quantity=quantity,
                            currency=currency,
                            stop=stop,
                            sell_rate=sell_rate,
                            unit_cash=unit_cash,
                            opened=at,
                        )
            else:
                if symbol not in self._positions:
                    raise ValueError('no_position')
                settlement = utc(event['settlement_at'])
                if settlement <= at:
                    raise ValueError('settlement_must_be_future')
                p = self._positions.pop(symbol)
                quantity = p['quantity']
                self._pending.append(
                    dict(
                        currency=currency,
                        amount=quantity * price * (1 - p['sell_rate']),
                        at=settlement,
                    )
                )
                reason = 'sold_unsettled'
        value = nav()
        self._daily_stop |= self._day_nav - value >= self._base * Decimal('.01')
        self._total_stop |= self._base - value >= self._base * Decimal('.05')
        result = dict(
            at=at.isoformat(),
            action=action,
            quantity=quantity,
            reason=reason,
            nav=str(value),
            return_=str(value / self._base - 1),
            daily_return=str(value / self._day_nav - 1) if self._day_nav > 0 else None,
            cash={c: str(v) for c, v in self._cash.items()},
            receivables={
                c: str(sum((p['amount'] for p in self._pending if p['currency'] == c), Decimal(0)))
                for c in self._cash
            },
            positions={s: p['quantity'] for s, p in self._positions.items()},
            remaining_risk=str(remaining_risk()),
            daily_stop=self._daily_stop,
            total_stop=self._total_stop,
            unclosed=list(self._positions),
        )
        result['return'] = result.pop('return_')
        self._previous = at
        return result


def replay_ledger(events, *, capital, initial_fx):
    ledger = PortfolioLedger(capital=capital, initial_fx=initial_fx)
    return [ledger.apply(event) for event in events]
