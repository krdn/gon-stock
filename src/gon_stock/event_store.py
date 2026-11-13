import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

EXCHANGES = {
    'KRX': ('XKRX', 'KRW'),
    'XKRX': ('XKRX', 'KRW'),
    'NAS': ('XNAS', 'USD'),
    'NASD': ('XNAS', 'USD'),
    'XNAS': ('XNAS', 'USD'),
    'NYS': ('XNYS', 'USD'),
    'NYSE': ('XNYS', 'USD'),
    'XNYS': ('XNYS', 'USD'),
    'AMS': ('XASE', 'USD'),
    'AMEX': ('XASE', 'USD'),
    'XASE': ('XASE', 'USD'),
}
FIELDS = {
    'id',
    'schema_version',
    'instrument',
    'kind',
    'source',
    'endpoint',
    'tr_id',
    'environment',
    'received_at',
    'event_time',
    'clock_status',
    'raw_sha256',
    'data',
    'correction_of',
    'effective_at',
    'source_clock',
}
DATA_FIELDS = {
    'bar': {'open', 'high', 'low', 'close', 'volume'},
    'quote': {'bid', 'ask', 'bid_size', 'ask_size'},
    'split': {'ratio'},
}
ENDPOINTS = {
    'bar': {'kr_bars', 'us_bars', 'kr_history', 'us_history', 'alpaca_history'},
    'quote': {'kr_orderbook', 'us_orderbook'},
    'split': {'corporate_action'},
}


def utc(value: datetime | str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(parsed, datetime) or parsed.utcoffset() is None:
            raise ValueError('invalid_timestamp')
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        raise ValueError('invalid_timestamp') from None


def canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False
    )


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def instrument(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {'exchange', 'symbol', 'currency'}:
        raise ValueError('invalid_instrument')
    exchange = EXCHANGES.get(value['exchange']) if isinstance(value['exchange'], str) else None
    if exchange is None or value['currency'] != exchange[1]:
        raise ValueError('invalid_instrument')
    symbol = value['symbol']
    pattern = r'[0-9]{6}' if exchange[0] == 'XKRX' else r'[A-Z][A-Z0-9.-]{0,14}'
    if not isinstance(symbol, str) or not re.fullmatch(pattern, symbol):
        raise ValueError('invalid_instrument')
    return {'exchange': exchange[0], 'symbol': symbol, 'currency': exchange[1]}


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise ValueError('invalid_identifier')
    return value


def validate_event(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('invalid_event_fields')
    result = dict(value)
    _identifier(result['id'])
    if result['correction_of'] is not None:
        _identifier(result['correction_of'])
    result['instrument'] = instrument(result['instrument'])
    kind = result['kind']
    if not isinstance(kind, str) or kind not in DATA_FIELDS:
        raise ValueError('invalid_kind')
    if type(result['schema_version']) is not int or result['schema_version'] != 1:
        raise ValueError('unsupported_schema')
    if result['source'] not in ('kis', 'synthetic', 'alpaca_sip'):
        raise ValueError('invalid_source')
    if result['environment'] not in ('mock', 'real', 'synthetic'):
        raise ValueError('invalid_environment')
    if (result['source'] == 'synthetic') != (result['environment'] == 'synthetic'):
        raise ValueError('invalid_source_environment')
    if result['endpoint'] not in ENDPOINTS[kind]:
        raise ValueError('invalid_endpoint')
    if (result['source'] == 'alpaca_sip') != (result['endpoint'] == 'alpaca_history'):
        raise ValueError('invalid_source_endpoint')
    _identifier(result['tr_id'])
    raw_hash = result['raw_sha256']
    if not isinstance(raw_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', raw_hash):
        raise ValueError('invalid_raw_hash')
    clock = result['source_clock']
    if not isinstance(clock, dict) or set(clock) != {
        'status',
        'source_date',
        'source_time',
        'source_timezone',
    }:
        raise ValueError('invalid_source_clock')
    if clock['status'] not in (
        'missing',
        'invalid',
        'inconsistent',
        'future',
        'timestamped_bar',
        'dated_bar',
        'time_only',
        'timezone_unverified',
    ):
        raise ValueError('invalid_source_clock')
    for field, pattern in (
        ('source_date', r'[0-9]{4}-[0-9]{2}-[0-9]{2}'),
        ('source_time', r'[0-9]{2}:[0-9]{2}:[0-9]{2}'),
    ):
        if clock[field] is not None and (
            not isinstance(clock[field], str) or not re.fullmatch(pattern, clock[field])
        ):
            raise ValueError('invalid_source_clock')
    if clock['source_timezone'] not in (None, 'UTC', 'Asia/Seoul', 'America/New_York'):
        raise ValueError('invalid_source_clock')
    result['source_clock'] = dict(clock)
    data = result['data']
    if not isinstance(data, dict) or set(data) != DATA_FIELDS[kind]:
        raise ValueError('invalid_data_fields')
    numbers = {}
    for key, number in data.items():
        if not isinstance(number, str) or not re.fullmatch(r'[0-9]{1,20}(\.[0-9]{1,12})?', number):
            raise ValueError('invalid_decimal')
        numbers[key] = Decimal(number)
        if key in ('volume', 'bid_size', 'ask_size'):
            if numbers[key] != numbers[key].to_integral_value():
                raise ValueError('invalid_size')
        elif numbers[key] <= 0:
            raise ValueError('invalid_price')
    if kind == 'bar' and not (
        numbers['low']
        <= min(numbers['open'], numbers['close'])
        <= max(numbers['open'], numbers['close'])
        <= numbers['high']
    ):
        raise ValueError('invalid_ohlc')
    if kind == 'quote' and numbers['bid'] > numbers['ask']:
        raise ValueError('crossed_quote')
    result['data'] = dict(data)
    received = utc(result['received_at'])
    event = utc(result['event_time']) if result['event_time'] is not None else None
    status = result['clock_status']
    if status not in ('verified', 'unverified', 'invalid', 'future'):
        raise ValueError('invalid_clock_status')
    if status == 'verified' and (event is None or event > received):
        raise ValueError('invalid_verified_clock')
    if kind == 'split':
        result['effective_at'] = utc(result['effective_at']).isoformat()
    elif result['effective_at'] is not None:
        raise ValueError('unexpected_effective_time')
    result['received_at'] = received.isoformat()
    result['event_time'] = event.isoformat() if event else None
    return result


def _decode(rows):
    result = []
    for seq, identity, received, event, body, checksum in rows:
        if digest(body) != checksum:
            raise ValueError('event_hash_mismatch')
        value = validate_event(json.loads(body))
        if (
            value['id'] != identity
            or utc(value['received_at']) != received
            or (utc(value['event_time']) if value['event_time'] else None) != event
        ):
            raise ValueError('event_metadata_mismatch')
        result.append({'receipt_seq': seq, **value})
    return result


def strategy_view(rows, cutoff: datetime, *, max_age: timedelta):
    cutoff = utc(cutoff)
    if not isinstance(max_age, timedelta) or max_age < timedelta(0):
        raise ValueError('invalid_max_age')
    streams = {
        (row['source'], row['environment']) for row in rows if utc(row['received_at']) <= cutoff
    }
    if len(streams) > 1:
        raise ValueError('mixed_streams')
    latest = {}
    for row in sorted(rows, key=lambda row: (utc(row['received_at']), row['receipt_seq'])):
        if utc(row['received_at']) > cutoff:
            continue
        key = (
            canonical(row['instrument']),
            row['source'],
            row['environment'],
            row['kind'],
            row['event_time'],
            row['effective_at'],
        )
        latest[key] = row
    result = []
    for row in latest.values():
        if row['clock_status'] != 'verified' or row['event_time'] is None:
            continue
        event = utc(row['event_time'])
        if event > cutoff:
            continue
        if row['kind'] == 'split':
            if utc(row['effective_at']) > cutoff:
                continue
        elif cutoff - event > max_age:
            continue
        if row['kind'] == 'bar' and event + timedelta(minutes=1) > utc(row['received_at']):
            continue
        result.append(row)
    return sorted(result, key=lambda row: row['receipt_seq'])


class EventStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.connection = duckdb.connect(str(self.path))
        os.chmod(self.path, 0o600)
        self.connection.execute("""CREATE TABLE IF NOT EXISTS events (
            receipt_seq BIGINT PRIMARY KEY, id VARCHAR UNIQUE NOT NULL,
            received_at TIMESTAMPTZ NOT NULL, event_time TIMESTAMPTZ,
            body VARCHAR NOT NULL, sha256 VARCHAR NOT NULL)""")
        self.connection.execute("""CREATE TABLE IF NOT EXISTS watchlist (
            exchange VARCHAR, symbol VARCHAR, currency VARCHAR,
            PRIMARY KEY(exchange, symbol, currency))""")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    def append(self, value: dict) -> int:
        value = validate_event(value)
        body = canonical(value)
        checksum = digest(body)
        db = self.connection
        db.execute('BEGIN TRANSACTION')
        try:
            existing = db.execute('SELECT * FROM events WHERE id = ?', [value['id']]).fetchone()
            if existing:
                _decode([existing])
                if existing[5] != checksum:
                    raise ValueError('id_conflict')
                db.execute('COMMIT')
                return existing[0]
            if value['correction_of']:
                target = db.execute(
                    'SELECT * FROM events WHERE id = ?', [value['correction_of']]
                ).fetchall()
                if not target:
                    raise ValueError('invalid_correction')
                old = _decode(target)[0]
                keys = ('instrument', 'kind', 'source', 'environment', 'event_time', 'effective_at')
                if any(old[k] != value[k] for k in keys) or utc(value['received_at']) < utc(
                    old['received_at']
                ):
                    raise ValueError('invalid_correction')
            seq = db.execute('SELECT COALESCE(MAX(receipt_seq), 0) + 1 FROM events').fetchone()[0]
            db.execute(
                'INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)',
                [
                    seq,
                    value['id'],
                    utc(value['received_at']),
                    utc(value['event_time']) if value['event_time'] else None,
                    body,
                    checksum,
                ],
            )
            db.execute('COMMIT')
            return seq
        except Exception:
            db.execute('ROLLBACK')
            raise

    def replay(self, cutoff: datetime):
        return _decode(
            self.connection.execute(
                'SELECT * FROM events WHERE received_at <= ? ORDER BY receipt_seq', [utc(cutoff)]
            ).fetchall()
        )

    def strategy_view(self, cutoff: datetime, *, max_age: timedelta):
        return strategy_view(self.replay(cutoff), cutoff, max_age=max_age)

    def watch(self, value: dict):
        value = instrument(value)
        self.connection.execute(
            'INSERT INTO watchlist VALUES (?, ?, ?) ON CONFLICT DO NOTHING',
            [value['exchange'], value['symbol'], value['currency']],
        )

    def unwatch(self, value: dict):
        value = instrument(value)
        self.connection.execute(
            'DELETE FROM watchlist WHERE exchange=? AND symbol=? AND currency=?',
            [value['exchange'], value['symbol'], value['currency']],
        )

    def watchlist(self):
        return [
            dict(zip(('exchange', 'symbol', 'currency'), row, strict=True))
            for row in self.connection.execute(
                'SELECT * FROM watchlist ORDER BY 1, 2, 3'
            ).fetchall()
        ]

    def export(self, directory: Path):
        directory = Path(directory)
        directory.mkdir(mode=0o700)
        target = directory / 'events.parquet'
        rows = self.connection.execute('SELECT * FROM events ORDER BY receipt_seq').fetchall()
        _decode(rows)
        self.connection.execute(
            'COPY (SELECT * FROM events ORDER BY receipt_seq) TO ? (FORMAT PARQUET)', [str(target)]
        )
        os.chmod(target, 0o600)
        manifest = {
            'schema_version': 1,
            'row_count': len(rows),
            'sha256': digest(target.read_bytes()),
            'duckdb_version': duckdb.__version__,
        }
        temporary = directory / 'manifest.tmp'
        temporary.write_text(canonical(manifest))
        os.chmod(temporary, 0o600)
        temporary.replace(directory / 'manifest.json')
        return manifest


def read_snapshot(directory: Path, cutoff: datetime):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    target = directory / 'events.parquet'
    if digest(target.read_bytes()) != manifest['sha256']:
        raise ValueError('snapshot_hash_mismatch')
    if manifest['schema_version'] != 1:
        raise ValueError('unsupported_schema')
    with duckdb.connect() as db:
        rows = db.execute(
            'SELECT * FROM read_parquet(?) ORDER BY receipt_seq', [str(target)]
        ).fetchall()
    if len(rows) != manifest['row_count']:
        raise ValueError('snapshot_count_mismatch')
    decoded = _decode(rows)
    return [row for row in decoded if utc(row['received_at']) <= utc(cutoff)]
