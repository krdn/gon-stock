from gon_stock.market_clock import read_market_clock


def test_us_bar_timestamp_uses_explicit_korean_clock_across_dst():
    for date, hour, local_date, local_hour in [
        ('20261112', '002400', '20261111', '102400'),
        ('20260702', '002400', '20260701', '112400'),
    ]:
        clock = read_market_clock(
            'us_bars',
            {
                'output2': [
                    {
                        'kymd': date,
                        'khms': hour,
                        'xymd': local_date,
                        'xhms': local_hour,
                    }
                ]
            },
        )
        assert clock.status == 'timestamped_bar'
        assert clock.source_timezone == 'Asia/Seoul'
        assert clock.event_time.isoformat() == (
            '2026-11-11T15:24:00+00:00' if date == '20261112' else '2026-07-01T15:24:00+00:00'
        )


def test_us_bar_inconsistent_or_missing_local_clock_is_rejected():
    for fields in [
        {'kymd': '20261112', 'khms': '002400', 'xymd': '20261111', 'xhms': '112400'},
        {'kymd': '20261112', 'khms': '002400'},
        {'kymd': '20260230', 'khms': '002400', 'xymd': '20260228', 'xhms': '102400'},
    ]:
        clock = read_market_clock('us_bars', {'output2': [fields]})
        assert clock.status in ('invalid', 'inconsistent')
        assert clock.event_time is None


def test_us_bar_timezone_underflow_is_invalid_not_an_exception():
    clock = read_market_clock(
        'us_bars',
        {
            'output2': [
                {
                    'kymd': '00010101',
                    'khms': '000000',
                    'xymd': '00010101',
                    'xhms': '000000',
                }
            ]
        },
    )
    assert clock.status == 'invalid'
    assert clock.event_time is None


def test_bars_use_latest_dated_record_not_receive_date_or_array_order():
    clock = read_market_clock(
        'kr_bars',
        {
            'output2': [
                {'stck_bsop_date': '20261110', 'stck_cntg_hour': '153000'},
                {'stck_bsop_date': '20261111', 'stck_cntg_hour': '090100'},
                {'stck_bsop_date': '20261111', 'stck_cntg_hour': '090000'},
            ]
        },
    )
    assert clock.status == 'dated_bar'
    assert clock.source_date == '2026-11-11'
    assert clock.source_time == '09:01:00'


def test_empty_and_malformed_bars_do_not_claim_valid_time():
    assert read_market_clock('kr_bars', {'output2': []}).status == 'missing'
    for rows in [
        None,
        {},
        [None],
        [{}],
        [
            {'stck_bsop_date': '20260230', 'stck_cntg_hour': '090000'},
        ],
        [
            {'stck_bsop_date': '20261111', 'stck_cntg_hour': 'secret'},
        ],
    ]:
        clock = read_market_clock('kr_bars', {'output2': rows})
        assert clock.status == 'invalid'
        assert clock.source_date is None and clock.source_time is None


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
