from gon_stock.market_clock import read_market_clock


def test_quote_cannot_use_historical_high_date_as_event_time():
    clock = read_market_clock('kr_quote', {'output': {'w52_hgpr_date': '20261111'}})
    assert clock.status == 'missing'
    assert clock.source_date is None and clock.source_time is None


def test_domestic_time_without_date_remains_incomplete():
    clock = read_market_clock('kr_orderbook', {'output1': {'aspr_acpt_hour': '153000'}})
    assert clock.status == 'time_only'
    assert clock.source_time == '15:30:00'
    assert clock.source_date is None


def test_overseas_date_time_does_not_assume_timezone():
    clock = read_market_clock('us_orderbook', {'output1': {'dymd': '20261111', 'dhms': '232841'}})
    assert clock.status == 'timezone_unverified'
    assert clock.source_date == '2026-11-11'
    assert clock.source_time == '23:28:41'


def test_invalid_date_and_time_do_not_escape_as_raw_values():
    for fields in [
        {'dymd': '20260230', 'dhms': '120000'},
        {'dymd': '20261111', 'dhms': '250000'},
        {'dymd': '20261111', 'dhms': 'secret'},
        {'dymd': '20261111', 'dhms': '123'},
        {'dymd': '20261111'},
    ]:
        clock = read_market_clock('us_orderbook', {'output1': fields})
        assert clock.status == 'invalid'
        assert clock.source_date is None and clock.source_time is None
