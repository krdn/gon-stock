import re
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MarketClock:
    status: str
    source_date: str | None = None
    source_time: str | None = None


def read_market_clock(operation: str, payload: dict) -> MarketClock:
    if operation == 'kr_bars':
        rows = payload.get('output2')
        if not isinstance(rows, list):
            return MarketClock('invalid')
        if not rows:
            return MarketClock('missing')
        stamps = []
        for row in rows:
            if not isinstance(row, dict):
                return MarketClock('invalid')
            date, hour = row.get('stck_bsop_date'), row.get('stck_cntg_hour')
            if (
                not isinstance(date, str)
                or not re.fullmatch(r'[0-9]{8}', date)
                or not isinstance(hour, str)
                or not re.fullmatch(r'[0-9]{6}', hour)
            ):
                return MarketClock('invalid')
            try:
                stamps.append(datetime.strptime(date + hour, '%Y%m%d%H%M%S'))
            except ValueError:
                return MarketClock('invalid')
        latest = max(stamps)
        return MarketClock('dated_bar', latest.date().isoformat(), latest.time().isoformat())
    if operation not in ('kr_orderbook', 'us_orderbook'):
        return MarketClock('missing')
    fields = payload.get('output1')
    if not isinstance(fields, dict):
        return MarketClock('invalid')
    raw_time = fields.get('aspr_acpt_hour' if operation == 'kr_orderbook' else 'dhms')
    raw_date = fields.get('dymd') if operation == 'us_orderbook' else None
    if raw_time is None and raw_date is None:
        return MarketClock('missing')
    if not isinstance(raw_time, str) or not re.fullmatch(r'[0-9]{6}', raw_time):
        return MarketClock('invalid')
    try:
        source_time = datetime.strptime(raw_time, '%H%M%S').time().isoformat()
        if operation == 'kr_orderbook':
            return MarketClock('time_only', source_time=source_time)
        if not isinstance(raw_date, str) or not re.fullmatch(r'[0-9]{8}', raw_date):
            return MarketClock('invalid')
        source_date = datetime.strptime(raw_date, '%Y%m%d').date().isoformat()
        return MarketClock('timezone_unverified', source_date, source_time)
    except ValueError:
        return MarketClock('invalid')
