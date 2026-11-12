import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import duckdb

from gon_stock.cli import credentials
from gon_stock.data_quality import calendar_snapshot, quality_report
from gon_stock.event_store import EventStore, digest, instrument, utc
from gon_stock.kis import ConnectionFailure, KisReadClient
from gon_stock.market_ingest import normalize_bars


def private_path(value):
    path = Path(value).resolve()
    root = (Path.cwd() / '.private').resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError('private_path_required')
    root.mkdir(mode=0o700, exist_ok=True)
    root.chmod(0o700)
    return path


def _instrument_arguments(parser):
    parser.add_argument('--exchange', required=True)
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--currency', choices=['KRW', 'USD'], required=True)


def main():
    parser = argparse.ArgumentParser(description='비공개 연구 데이터 저장·재생')
    parser.add_argument('--db', default='.private/research.duckdb')
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('watch', 'unwatch'):
        _instrument_arguments(commands.add_parser(command))
    commands.add_parser('watchlist')
    capture = commands.add_parser('capture')
    _instrument_arguments(capture)
    capture.add_argument('--environment', choices=['mock', 'real'], required=True)
    ingest = commands.add_parser('import')
    ingest.add_argument('--input', required=True)
    replay = commands.add_parser('replay')
    replay.add_argument('--at', required=True)
    replay.add_argument('--max-age-seconds', type=int)
    replay.add_argument('--output')
    export = commands.add_parser('export')
    export.add_argument('--output', required=True)
    quality = commands.add_parser('quality')
    _instrument_arguments(quality)
    quality.add_argument('--start', required=True)
    quality.add_argument('--end', required=True)
    quality.add_argument('--at', required=True)
    quality.add_argument('--bar-label', choices=['start', 'end'])
    quality.add_argument('--output', required=True)
    args = parser.parse_args()
    imported = 0
    try:
        db_path = private_path(args.db)
        target = None
        if hasattr(args, 'symbol'):
            target = instrument(
                {'exchange': args.exchange, 'symbol': args.symbol, 'currency': args.currency}
            )
        output = private_path(args.output) if getattr(args, 'output', None) is not None else None
        source = private_path(args.input) if hasattr(args, 'input') else None
        with EventStore(db_path) as store:
            if args.command in ('watch', 'unwatch'):
                getattr(store, args.command)(target)
                result = store.watchlist()
            elif args.command == 'watchlist':
                result = store.watchlist()
            elif args.command == 'capture':
                domestic = target['exchange'] == 'XKRX'
                if not domestic and args.environment != 'real':
                    raise ValueError('unsupported_environment')
                operation = 'kr_bars' if domestic else 'us_bars'
                params = {'symbol': target['symbol']}
                if not domestic:
                    params['exchange'] = {'XNAS': 'NAS', 'XNYS': 'NYS', 'XASE': 'AMS'}[
                        target['exchange']
                    ]
                with KisReadClient(credentials(args.environment), args.environment) as client:
                    requested = datetime.now(UTC)
                    fetched = client.fetch(operation, **params)
                records = normalize_bars(
                    fetched,
                    operation,
                    target,
                    args.environment,
                    requested_at=requested,
                    request_id=uuid4().hex,
                )
                for record in records:
                    store.append(record)
                    imported += 1
                if not records:
                    raise ValueError('no_bars')
                result = {
                    'status': 'ok',
                    'stored': imported,
                    'operation': operation,
                    'environment': args.environment,
                    'received_at': fetched.received_at.isoformat(),
                    'verified_clock_rows': sum(r['clock_status'] == 'verified' for r in records),
                }
            elif args.command == 'import':
                with source.open() as stream:
                    for line in stream:
                        if line.strip():
                            store.append(json.loads(line))
                            imported += 1
                result = {'status': 'ok', 'imported': imported}
            elif args.command == 'replay':
                at = utc(args.at)
                result = (
                    store.replay(at)
                    if args.max_age_seconds is None
                    else store.strategy_view(at, max_age=timedelta(seconds=args.max_age_seconds))
                )
            elif args.command == 'export':
                result = store.export(output)
            else:
                start, end, at = utc(args.start), utc(args.end), utc(args.at)
                calendar = calendar_snapshot(
                    target['exchange'], start.date().isoformat(), end.date().isoformat()
                )
                report = quality_report(
                    store.replay(at),
                    calendar,
                    target,
                    start=start,
                    end=end,
                    cutoff=at,
                    bar_label=args.bar_label,
                )
                result = {'calendar': calendar, 'report': report}
        if args.command in ('quality', 'replay') and output is not None:
            output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with output.open('x') as stream:
                output.chmod(0o600)
                json.dump(result, stream, ensure_ascii=False, indent=2)
            if args.command == 'replay':
                result = {'row_count': len(result), 'sha256': digest(output.read_bytes())}
        print(json.dumps(result, ensure_ascii=False))
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        OverflowError,
        duckdb.Error,
        ConnectionFailure,
    ):
        print(
            json.dumps(
                {
                    'status': 'failed',
                    'code': 'data_operation_failed',
                    'imported_before_failure': imported,
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
