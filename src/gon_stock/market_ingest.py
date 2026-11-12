from dataclasses import asdict
from datetime import timedelta

from gon_stock.event_store import canonical, digest, instrument, utc, validate_event
from gon_stock.kis import ROUTES, ReadResult
from gon_stock.market_clock import read_market_clock, select_completed_domestic_bar

PRICE_FIELDS = {
    'kr_bars': {
        'open': 'stck_oprc',
        'high': 'stck_hgpr',
        'low': 'stck_lwpr',
        'close': 'stck_prpr',
        'volume': 'cntg_vol',
    },
    'us_bars': {'open': 'open', 'high': 'high', 'low': 'low', 'close': 'last', 'volume': 'evol'},
}


def normalize_bars(
    result: ReadResult,
    operation: str,
    target: dict,
    environment: str,
    *,
    requested_at,
    request_id: str,
) -> list[dict]:
    target = instrument(target)
    requested_at = utc(requested_at)
    if operation not in PRICE_FIELDS or environment not in ('mock', 'real'):
        raise ValueError('unsupported_ingest')
    domestic = operation == 'kr_bars'
    if (target['exchange'] == 'XKRX') != domestic or (not domestic and environment != 'real'):
        raise ValueError('unsupported_ingest')
    if requested_at > result.received_at:
        raise ValueError('clock_reversed')
    rows = result.payload.get('output2')
    if not isinstance(rows, list):
        raise ValueError('invalid_bars')
    records = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('invalid_bars')
        clock = read_market_clock(operation, {'output2': [row]})
        event_time, status = None, 'unverified'
        if domestic:
            try:
                event_time = select_completed_domestic_bar([row], requested_at)
                status = 'verified'
            except ValueError:
                status = 'invalid' if clock.status == 'invalid' else 'unverified'
        elif clock.status == 'timestamped_bar':
            event_time = clock.event_time
            if event_time > result.received_at:
                status = 'future'
            elif event_time + timedelta(minutes=1) <= requested_at:
                status = 'verified'
        else:
            status = 'invalid' if clock.status in ('invalid', 'inconsistent') else 'unverified'
        records.append(
            validate_event(
                {
                    'id': f'{request_id}_{index}',
                    'schema_version': 1,
                    'instrument': target,
                    'kind': 'bar',
                    'source': 'kis',
                    'endpoint': operation,
                    'tr_id': ROUTES[operation][1],
                    'environment': environment,
                    'received_at': result.received_at.isoformat(),
                    'event_time': event_time.isoformat() if event_time else None,
                    'clock_status': status,
                    'source_clock': asdict(clock),
                    'raw_sha256': digest(canonical(row)),
                    'data': {key: row.get(field) for key, field in PRICE_FIELDS[operation].items()},
                    'correction_of': None,
                    'effective_at': None,
                }
            )
        )
    return records
