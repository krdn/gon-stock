"""Bounded, read-only prospective research collection; no order routes."""

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import duckdb

from gon_stock.cli import credentials
from gon_stock.data_cli import private_path
from gon_stock.data_quality import calendar_snapshot
from gon_stock.event_store import EventStore, instrument, utc
from gon_stock.kis import ConnectionFailure, KisReadClient
from gon_stock.market_ingest import normalize_bars


def next_poll(calendar, now):
    now = utc(now)
    for session in calendar['sessions']:
        first = utc(session['open']) + timedelta(minutes=1, seconds=20)
        last = utc(session['close']) + timedelta(minutes=1, seconds=20)
        candidate = max(first, now.replace(second=20, microsecond=0))
        if candidate < now:
            candidate += timedelta(minutes=1)
        if candidate <= last:
            return candidate
    return None


def recent_rows(rows):
    # Retain the current and previous bar, including uncertain-clock evidence.
    for row in rows:
        clock = row['source_clock']
        if not clock['source_date'] or not clock['source_time']:
            raise ValueError('missing_source_clock')
    return sorted(
        rows,
        key=lambda row: (row['source_clock']['source_date'], row['source_clock']['source_time']),
        reverse=True,
    )[:2]


def capture(client, store, target, *, now=lambda: datetime.now(UTC)):
    domestic = target['exchange'] == 'XKRX'
    operation = 'kr_bars' if domestic else 'us_bars'
    params = {'symbol': target['symbol']}
    if not domestic:
        params['exchange'] = {'XNAS': 'NAS', 'XNYS': 'NYS', 'XASE': 'AMS'}[target['exchange']]
    requested = now()
    fetched = client.fetch(operation, **params)
    rows = recent_rows(
        normalize_bars(
            fetched, operation, target, 'real', requested_at=requested, request_id=uuid4().hex
        )
    )
    for row in rows:
        store.append(row)
    return {
        'symbol': target['symbol'],
        'stored': len(rows),
        'verified': sum(row['clock_status'] == 'verified' for row in rows),
        'received_at': fetched.received_at.isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description='기한이 있는 읽기 전용 미래 분봉 수집')
    parser.add_argument('--exchange', choices=['XKRX', 'XNAS', 'XNYS', 'XASE'], required=True)
    parser.add_argument('--symbols', nargs='+', required=True)
    parser.add_argument('--db', required=True)
    parser.add_argument('--until', required=True)
    args = parser.parse_args()
    try:
        now, until = datetime.now(UTC), utc(args.until)
        if not now < until <= now + timedelta(days=7):
            raise ValueError('collection_horizon_1_to_7_days')
        if not 1 <= len(set(args.symbols)) == len(args.symbols) <= 4:
            raise ValueError('invalid_cohort_size')
        targets = [
            instrument(
                {
                    'exchange': args.exchange,
                    'symbol': symbol,
                    'currency': 'KRW' if args.exchange == 'XKRX' else 'USD',
                }
            )
            for symbol in args.symbols
        ]
        db = private_path(args.db)
        calendar = calendar_snapshot(
            args.exchange, now.date().isoformat(), until.date().isoformat()
        )
        metadata = private_path(str(db) + '.' + uuid4().hex + '.json')
        metadata.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with metadata.open('x') as stream:
            metadata.chmod(0o600)
            json.dump(
                {
                    'started_at': now.isoformat(),
                    'until': until.isoformat(),
                    'targets': targets,
                    'calendar': calendar,
                    'calendar_verified': False,
                },
                stream,
            )
        with EventStore(db) as store, KisReadClient(credentials('real'), 'real') as client:
            for target in targets:
                store.watch(target)
            print(
                json.dumps(
                    {
                        'status': 'scheduled',
                        'until': until.isoformat(),
                        'calendar_sha256': calendar['sha256'],
                    }
                ),
                flush=True,
            )
            while (due := next_poll(calendar, datetime.now(UTC))) is not None and due < until:
                while (delay := (due - datetime.now(UTC)).total_seconds()) > 0:
                    time.sleep(min(delay, 30))
                # Never backfill a delayed request with an invented receipt time.
                if datetime.now(UTC) >= until:
                    break
                if datetime.now(UTC) - due > timedelta(seconds=30):
                    continue
                for target in targets:
                    print(
                        json.dumps({'status': 'captured', **capture(client, store, target)}),
                        flush=True,
                    )
        print(json.dumps({'status': 'finished'}), flush=True)
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        OverflowError,
        duckdb.Error,
        ConnectionFailure,
    ):
        print(json.dumps({'status': 'failed', 'code': 'collection_stopped'}), flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
