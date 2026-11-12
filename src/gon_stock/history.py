import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from gon_stock.event_store import canonical, digest, instrument, utc, validate_event
from gon_stock.kis import ROUTES
from gon_stock.market_clock import read_market_clock
from gon_stock.market_ingest import PRICE_FIELDS


def history_clock(row, target):
    domestic = target['exchange'] == 'XKRX'
    clock = read_market_clock('kr_bars' if domestic else 'us_bars', {'output2': [row]})
    if domestic and clock.status == 'dated_bar':
        return (
            datetime.fromisoformat(clock.source_date + 'T' + clock.source_time)
            .replace(tzinfo=ZoneInfo('Asia/Seoul'))
            .astimezone(UTC)
        )
    if not domestic and clock.status == 'timestamped_bar':
        return clock.event_time
    raise ValueError('invalid_history_clock')


def download_day(client, target, session, directory):
    target = instrument(target)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    domestic = target['exchange'] == 'XKRX'
    zone = ZoneInfo('Asia/Seoul' if domestic else 'America/New_York')
    operation = 'kr_history' if domestic else 'us_history'
    opened, cursor = utc(session['open']), utc(session['close'])
    pages = []
    for _ in range(8):
        before = cursor.astimezone(zone).strftime('%Y%m%d%H%M%S')
        args = {'symbol': target['symbol'], 'before': before}
        if not domestic:
            args['exchange'] = {'XNAS': 'NAS', 'XNYS': 'NYS', 'XASE': 'AMS'}[target['exchange']]
        path = directory / f'{target["exchange"]}-{target["symbol"]}-{before}.json'
        if path.exists():
            page = json.loads(path.read_text())
            if page['operation'] != operation or page['params'] != args:
                raise ValueError('page_request_mismatch')
            if digest(canonical(page['payload'])) != page['payload_sha256']:
                raise ValueError('page_hash_mismatch')
        else:
            response = client.fetch(operation, **args)
            page = {
                'operation': operation,
                'params': args,
                'received_at': response.received_at.isoformat(),
                'payload_sha256': digest(canonical(response.payload)),
                'payload': response.payload,
            }
            with path.open('x') as stream:
                path.chmod(0o600)
                stream.write(canonical(page))
        rows = page['payload']['output2']
        pages.append(page)
        if not rows:
            return pages
        clocks = [history_clock(row, target) for row in rows]
        if any(stamp > cursor for stamp in clocks):
            raise ValueError('history_cursor_not_respected')
        earliest = min(clocks)
        if earliest <= opened:
            return pages
        following = earliest - timedelta(minutes=1)
        if following >= cursor:
            raise ValueError('history_cursor_not_advancing')
        cursor = following
    raise ValueError('history_page_limit')


def history_events(page, target):
    target = instrument(target)
    operation = page['operation']
    expected = 'kr_history' if target['exchange'] == 'XKRX' else 'us_history'
    if operation != expected:
        raise ValueError('history_market_mismatch')
    clock_operation = operation.replace('_history', '_bars')
    received = utc(page['received_at'])
    records = []
    for index, row in enumerate(page['payload']['output2']):
        stamp = history_clock(row, target)
        clock = read_market_clock(clock_operation, {'output2': [row]})
        raw_hash = digest(canonical(row))
        record = {
            'id': digest(canonical([target, received.isoformat(), raw_hash, index])),
            'schema_version': 1,
            'instrument': target,
            'kind': 'bar',
            'source': 'kis',
            'endpoint': operation,
            'tr_id': ROUTES[operation][1],
            'environment': 'real',
            'received_at': received.isoformat(),
            'event_time': stamp.isoformat(),
            'clock_status': 'verified'
            if stamp + timedelta(minutes=1) <= received
            else 'unverified',
            'raw_sha256': raw_hash,
            'source_clock': asdict(clock),
            'data': {key: row.get(field) for key, field in PRICE_FIELDS[clock_operation].items()},
            'correction_of': None,
            'effective_at': None,
        }
        records.append(validate_event(record))
    return records


def reconcile(rows, calendar, targets=None):
    from gon_stock.backtest import _sessions

    sessions = _sessions(calendar, calendar['exchange'])
    targets = targets or [
        json.loads(key) for key in sorted({canonical(r['instrument']) for r in rows})
    ]
    expected = {
        (canonical(target), opened): set(
            opened + timedelta(minutes=i)
            for i in range(int((closed - opened).total_seconds() // 60))
        )
        for target in targets
        for opened, closed in sessions
    }
    observed = {key: set() for key in expected}
    chosen = {}
    duplicates = conflicts = outside = uncertain = 0
    for row in sorted(rows, key=lambda r: (utc(r['received_at']), r['id'])):
        if row['clock_status'] != 'verified' or row['event_time'] is None:
            uncertain += 1
            continue
        stamp = utc(row['event_time'])
        if stamp.second or stamp.microsecond:
            raise ValueError('unaligned_history_bar')
        opened = next((a for a, b in sessions if a <= stamp < b), None)
        if opened is None:
            outside += 1
            continue
        target = canonical(row['instrument'])
        key = target, stamp
        if key in chosen:
            duplicates += 1
            if chosen[key]['data'] != row['data']:
                conflicts += 1
        else:
            chosen[key] = row
        observed[target, opened].add(stamp)
    coverage = [
        {
            'instrument': json.loads(target),
            'session_open': opened.isoformat(),
            'expected_minutes_assuming_start_label': len(minutes),
            'observed_minutes': len(observed[target, opened]),
            'missing_minutes_assuming_start_label': len(minutes - observed[target, opened]),
        }
        for (target, opened), minutes in expected.items()
    ]
    records = [dict(row, receipt_seq=i + 1) for i, row in enumerate(chosen.values())]
    return records, {
        'observations': len(rows),
        'unique_regular_bars': len(records),
        'duplicates': duplicates,
        'conflicts': conflicts,
        'outside_requested_regular_sessions': outside,
        'uncertain': uncertain,
        'coverage': coverage,
        'bar_label_verified': False,
    }
