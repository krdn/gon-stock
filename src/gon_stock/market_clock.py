import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MarketClock:
    status: str
    source_date: str | None = None
    source_time: str | None = None
    source_timezone: str | None = None

    @property
    def event_time(self) -> datetime | None:
        if self.status != 'timestamped_bar':
            return None
        return (
            datetime.fromisoformat(f'{self.source_date}T{self.source_time}')
            .replace(tzinfo=ZoneInfo(self.source_timezone))
            .astimezone(UTC)
        )


def _timestamp(date, hour):
    if (
        not isinstance(date, str)
        or not re.fullmatch(r'[0-9]{8}', date)
        or not isinstance(hour, str)
        or not re.fullmatch(r'[0-9]{6}', hour)
    ):
        raise ValueError('날짜·시각 형식 오류')
    return datetime.strptime(date + hour, '%Y%m%d%H%M%S')


def select_completed_domestic_bar(rows, requested_at: datetime) -> datetime:
    if not isinstance(rows, list) or requested_at.utcoffset() is None:
        raise ValueError('invalid_clock_sample')
    local = requested_at.astimezone(ZoneInfo('Asia/Seoul'))
    bound = local.replace(second=0, microsecond=0)
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid_clock_sample')
        volume = row.get('cntg_vol')
        if not isinstance(volume, str) or not re.fullmatch(r'[0-9]{1,20}', volume):
            raise ValueError('invalid_clock_sample')
        try:
            stamp = _timestamp(row.get('stck_bsop_date'), row.get('stck_cntg_hour')).replace(
                tzinfo=ZoneInfo('Asia/Seoul')
            )
        except ValueError:
            raise ValueError('invalid_clock_sample') from None
        if (
            stamp.date() == local.date()
            and '09:00:00' <= stamp.time().isoformat() <= '15:30:00'
            and stamp < bound
            and int(volume) > 0
        ):
            candidates.append(stamp)
    if not candidates:
        raise ValueError('no_completed_trade_bar')
    return max(candidates).astimezone(UTC)


def read_market_clock(operation: str, payload: dict) -> MarketClock:
    if operation in ('kr_bars', 'us_bars'):
        us = operation == 'us_bars'
        rows = payload.get('output2')
        if not isinstance(rows, list):
            return MarketClock('invalid')
        if not rows:
            return MarketClock('missing')
        stamps = []
        for row in rows:
            if not isinstance(row, dict):
                return MarketClock('invalid')
            try:
                stamp = _timestamp(
                    row.get('kymd' if us else 'stck_bsop_date'),
                    row.get('khms' if us else 'stck_cntg_hour'),
                )
                if us:
                    local = _timestamp(row.get('xymd'), row.get('xhms'))
                    ny = (
                        stamp.replace(tzinfo=ZoneInfo('Asia/Seoul'))
                        .astimezone(ZoneInfo('America/New_York'))
                        .replace(tzinfo=None)
                    )
                    if ny != local:
                        return MarketClock('inconsistent')
                stamps.append(stamp)
            except (ValueError, OverflowError):
                return MarketClock('invalid')
        latest = max(stamps)
        return MarketClock(
            'timestamped_bar' if us else 'dated_bar',
            latest.date().isoformat(),
            latest.time().isoformat(),
            'Asia/Seoul' if us else None,
        )
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
