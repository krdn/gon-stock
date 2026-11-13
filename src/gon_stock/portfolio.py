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
