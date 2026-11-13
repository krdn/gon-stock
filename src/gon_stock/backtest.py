import re
from datetime import timedelta
from decimal import Decimal
from itertools import groupby

from gon_stock.event_store import canonical, digest, instrument, utc, validate_event

STRATEGY_ID = 'relative-volume-intraday-v1'
COST_FIELDS = {'commission_each', 'tax_sell', 'spread_each', 'slippage_each', 'fx_each'}
MINUTE = timedelta(minutes=1)


def roundtrip_cost(value: dict, exit_ratio=Decimal(1)) -> Decimal:
    if not isinstance(value, dict) or set(value) != COST_FIELDS:
        raise ValueError('invalid_costs')
    for number in value.values():
        if not isinstance(number, str) or not re.fullmatch(r'[0-9]{1,5}(\.[0-9]{1,6})?', number):
            raise ValueError('invalid_costs')
    buy = sum(Decimal(number) for key, number in value.items() if key != 'tax_sell') / 10000
    sell = buy + Decimal(value['tax_sell']) / 10000
    if buy + sell >= 1:
        raise ValueError('invalid_costs')
    return buy + exit_ratio * sell


def _sessions(calendar, exchange):
    content = {key: value for key, value in calendar.items() if key != 'sha256'}
    if digest(canonical(content)) != calendar.get('sha256') or calendar['exchange'] != exchange:
        raise ValueError('invalid_calendar')
    result = [(utc(row['open']), utc(row['close'])) for row in calendar['sessions']]
    if any(opened >= closed for opened, closed in result):
        raise ValueError('invalid_calendar')
    if any(current[0] < previous[1] for previous, current in zip(result, result[1:], strict=False)):
        raise ValueError('invalid_calendar')
    return result


def _outcome(outcomes, entry_at, closed, costs):
    first = outcomes.get(entry_at)
    if first is None:
        return None
    entry = Decimal(first['data']['open'])
    stop, target = entry * Decimal('.99'), entry * Decimal('1.015')
    deadline = min(entry_at + 30 * MINUTE, closed)
    current = entry_at
    while current < deadline:
        row = outcomes.get(current)
        if row is None:
            return None
        data = {key: Decimal(value) for key, value in row['data'].items()}
        reason, price = None, None
        if data['open'] <= stop:
            reason, price = 'stop', data['open']
        elif data['low'] <= stop:
            reason, price = 'stop', stop
        elif data['high'] >= target:
            reason, price = 'target', target
        elif current + MINUTE == deadline:
            reason, price = 'time', data['close']
        if reason:
            gross = price / entry - 1
            cost = roundtrip_cost(costs, price / entry)
            return {
                'entry_at': entry_at.isoformat(),
                'exit_at': (current + MINUTE).isoformat(),
                'entry_price': str(entry),
                'exit_price': str(price),
                'exit_reason': reason,
                'gross_return': float(gross),
                'cost_return': float(cost),
                'net_return': float(gross - cost),
                'stress_return': float(gross - 2 * cost),
            }
        current += MINUTE
    return None


def backtest(rows, calendar, universe, benchmark, costs, *, historical_delay_seconds=None):
    if historical_delay_seconds is not None and (
        type(historical_delay_seconds) is not int or not 60 <= historical_delay_seconds <= 120
    ):
        raise ValueError('invalid_history_delay')
    cost = roundtrip_cost(costs)
    benchmark = instrument(benchmark)
    universe = [instrument(value) for value in universe]
    benchmark_key = canonical(benchmark)
    targets = sorted({canonical(value) for value in universe})
    if (
        not targets
        or benchmark_key in targets
        or len(targets) != len(universe)
        or any(value['exchange'] != benchmark['exchange'] for value in universe)
    ):
        raise ValueError('invalid_universe')
    sessions = _sessions(calendar, benchmark['exchange'])
    required = set(targets) | {benchmark_key}
    observations = []
    for row in rows:
        value = validate_event({key: item for key, item in row.items() if key != 'receipt_seq'})
        if type(row.get('receipt_seq')) is not int or row['receipt_seq'] < 1:
            raise ValueError('invalid_receipt_seq')
        if canonical(value['instrument']) not in required:
            continue
        if value['kind'] == 'split' or value['correction_of'] is not None:
            raise ValueError('unsupported_corporate_revision')
        if value['kind'] != 'bar':
            continue
        if historical_delay_seconds is not None:
            if value['endpoint'] not in ('kr_history', 'us_history', 'alpaca_history'):
                raise ValueError('history_only')
            if value['event_time'] is not None:
                value['received_at'] = (
                    utc(value['event_time']) + timedelta(seconds=historical_delay_seconds)
                ).isoformat()
        observations.append({'receipt_seq': row['receipt_seq'], **value})
    if len({(row['source'], row['environment']) for row in observations}) > 1:
        raise ValueError('mixed_streams')
    observations.sort(key=lambda row: (utc(row['received_at']), row['receipt_seq']))
    outcomes = {key: {} for key in required}
    for row in observations:
        if row['clock_status'] != 'verified' or row['event_time'] is None:
            continue
        event = utc(row['event_time'])
        received = utc(row['received_at'])
        if event.second or event.microsecond or not MINUTE <= received - event <= 2 * MINUTE:
            continue
        key = canonical(row['instrument'])
        outcomes[key].setdefault(event, row)
    known = {key: {} for key in required}
    attempted, trades = set(), []
    unresolved, no_entry = 0, 0
    blocked_until = None
    for received, batch in groupby(observations, key=lambda row: utc(row['received_at'])):
        for row in batch:
            if row['clock_status'] != 'verified' or row['event_time'] is None:
                continue
            event = utc(row['event_time'])
            if event.second or event.microsecond or event + MINUTE > received:
                continue
            known[canonical(row['instrument'])][event] = row
        if blocked_until and received < blocked_until:
            continue
        session = next(
            ((opened, closed) for opened, closed in sessions if opened <= received < closed), None
        )
        if session is None:
            continue
        opened, closed = session
        for key in targets:
            if not known[key]:
                continue
            latest = max(known[key])
            if (key, latest) in attempted or received - latest > 2 * MINUTE:
                continue
            times = [latest - MINUTE * offset for offset in range(20, -1, -1)]
            if times[0] < opened or any(
                time not in known[key] or time not in known[benchmark_key] for time in times
            ):
                continue
            attempted.add((key, latest))
            prices = [Decimal(known[key][time]['data']['close']) for time in times]
            reference = [Decimal(known[benchmark_key][time]['data']['close']) for time in times]
            volume = [Decimal(known[key][time]['data']['volume']) for time in times]
            relative = prices[-1] / prices[0] - reference[-1] / reference[0]
            mean_volume = sum(volume[:-1]) / 20
            if (
                relative < Decimal('.001')
                or mean_volume == 0
                or volume[-1] < mean_volume * Decimal('1.5')
            ):
                continue
            entry_at = received.replace(second=0, microsecond=0) + MINUTE
            if entry_at >= closed:
                continue
            if entry_at not in outcomes[key]:
                no_entry += 1
                continue
            outcome = _outcome(outcomes[key], entry_at, closed, costs)
            if outcome is None:
                unresolved += 1
                blocked_until = closed
                break
            trades.append(
                {
                    'instrument': known[key][latest]['instrument'],
                    'decision_at': received.isoformat(),
                    'signal_bar_at': latest.isoformat(),
                    'strength': 'strong' if relative >= Decimal('.005') else 'weak',
                    **outcome,
                }
            )
            blocked_until = utc(outcome['exit_at'])
            break
    return {
        'strategy_id': STRATEGY_ID,
        'availability_mode': 'historical_assumption'
        if historical_delay_seconds is not None
        else 'observed_receipt',
        'assumed_delay_seconds': historical_delay_seconds,
        'trades': trades,
        'unresolved': unresolved,
        'no_entry_bar': no_entry,
        'flat_price_cost_return': float(cost),
    }
