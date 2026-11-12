from datetime import date, timedelta
from itertools import groupby

import exchange_calendars

from gon_stock.event_store import EXCHANGES, canonical, digest, instrument, utc

CALENDAR_NAMES = {'XKRX': 'XKRX', 'XNAS': 'XNYS', 'XNYS': 'XNYS', 'XASE': 'XNYS'}


def calendar_snapshot(exchange: str, start: str, end: str) -> dict:
    if exchange not in EXCHANGES:
        raise ValueError('invalid_exchange')
    market = EXCHANGES[exchange][0]
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or (last - first).days > 366:
        raise ValueError('invalid_calendar_range')
    calendar = exchange_calendars.get_calendar(
        CALENDAR_NAMES[market], start=first - timedelta(days=7), end=last + timedelta(days=7)
    )
    sessions = [
        {
            'date': index.date().isoformat(),
            'open': row['open'].isoformat(),
            'close': row['close'].isoformat(),
        }
        for index, row in calendar.schedule.loc[start:end].iterrows()
    ]
    value = {
        'schema_version': 1,
        'exchange': market,
        'calendar': calendar.name,
        'library_version': exchange_calendars.__version__,
        'start': start,
        'end': end,
        'sessions': sessions,
    }
    return {**value, 'sha256': digest(canonical(value))}


def quality_report(rows, calendar: dict, target: dict, *, start, end, cutoff, bar_label=None):
    target = instrument(target)
    start, end, cutoff = utc(start), utc(end), utc(cutoff)
    if start >= end or end > cutoff or end - start > timedelta(days=366):
        raise ValueError('invalid_coverage')
    if bar_label not in (None, 'start', 'end'):
        raise ValueError('invalid_bar_label')
    content = {key: value for key, value in calendar.items() if key != 'sha256'}
    if digest(canonical(content)) != calendar.get('sha256'):
        raise ValueError('calendar_hash_mismatch')
    if calendar['schema_version'] != 1 or calendar['exchange'] != target['exchange']:
        raise ValueError('calendar_market_mismatch')
    calendar_start = utc(calendar['start'] + 'T00:00:00+00:00')
    calendar_end = utc(calendar['end'] + 'T00:00:00+00:00') + timedelta(days=1)
    if start < calendar_start or end > calendar_end:
        raise ValueError('calendar_coverage_missing')
    selected = [
        row for row in rows if row['instrument'] == target and utc(row['received_at']) <= cutoff
    ]
    selected.sort(key=lambda row: (utc(row['received_at']), row['receipt_seq']))
    if len({(row['source'], row['environment']) for row in selected}) > 1:
        raise ValueError('mixed_streams')
    uncertain, reversed_times, duplicates, off_session = [], [], [], []
    seen, observed = set(), set()
    high, known = {}, set()
    sessions = [(utc(session['open']), utc(session['close'])) for session in calendar['sessions']]
    for _, batch in groupby(selected, key=lambda row: utc(row['received_at'])):
        peaks = {}
        for row in batch:
            identity = row['id']
            signature = canonical(
                {
                    key: row[key]
                    for key in (
                        'instrument',
                        'kind',
                        'source',
                        'environment',
                        'event_time',
                        'source_clock',
                        'data',
                        'effective_at',
                    )
                }
            )
            if signature in seen:
                duplicates.append(identity)
            seen.add(signature)
            if row['clock_status'] != 'verified' or row['event_time'] is None:
                uncertain.append(identity)
                continue
            event = utc(row['event_time'])
            stream = (row['source'], row['environment'], row['kind'])
            if stream in high and event < high[stream] and (stream, event) not in known:
                reversed_times.append(identity)
            known.add((stream, event))
            peaks[stream] = max(peaks.get(stream, event), event)
            if row['kind'] != 'bar' or not start <= event < end:
                continue
            observed.add(event)
            if not any(opened <= event <= closed for opened, closed in sessions):
                off_session.append(identity)
        for stream, peak in peaks.items():
            high[stream] = max(high.get(stream, peak), peak)
    expected = set()
    if bar_label is not None:
        for opened, closed in sessions:
            minute = opened + (timedelta(minutes=1) if bar_label == 'end' else timedelta(0))
            stop = closed + (timedelta(minutes=1) if bar_label == 'end' else timedelta(0))
            while minute < stop:
                if start <= minute < end:
                    expected.add(minute)
                minute += timedelta(minutes=1)
    return {
        'calendar_sha256': calendar['sha256'],
        'instrument': target,
        'observation_count': len(selected),
        'duplicate_candidates': duplicates,
        'reverse_event_time': reversed_times,
        'uncertain_clock': uncertain,
        'off_session': off_session,
        'missing_status': 'candidates_only' if bar_label else 'bar_label_unverified',
        'expected_count': len(expected) if bar_label else None,
        'gap_candidates': [value.isoformat() for value in sorted(expected - observed)],
    }
