import importlib
from datetime import timedelta

import pytest
from test_event_store import event, stamp


def api():
    try:
        return importlib.import_module('gon_stock.data_quality')
    except ModuleNotFoundError:
        pytest.fail('P2 quality checks are not implemented')


def test_calendar_dst_holiday_and_early_close():
    module = api()
    summer = module.calendar_snapshot('XNAS', '2026-03-09', '2026-03-09')
    winter = module.calendar_snapshot('XNYS', '2026-03-06', '2026-03-06')
    assert summer['sessions'][0]['open'] == '2026-03-09T13:30:00+00:00'
    assert winter['sessions'][0]['open'] == '2026-03-06T14:30:00+00:00'
    holiday = module.calendar_snapshot('XNYS', '2026-11-26', '2026-11-27')
    assert [s['date'] for s in holiday['sessions']] == ['2026-11-27']
    assert holiday['sessions'][0]['close'] == '2026-11-27T18:00:00+00:00'
    assert len(holiday['sha256']) == 64
    assert holiday['library_version']


def test_domestic_calendar_weekend_and_known_holiday():
    module = api()
    calendar = module.calendar_snapshot('XKRX', '2026-10-09', '2026-10-12')
    assert [s['date'] for s in calendar['sessions']] == ['2026-10-12']
    assert calendar['sessions'][0]['open'] == '2026-10-12T00:00:00+00:00'


def test_gap_candidates_only_in_declared_coverage_and_trading_session(tmp_path):
    from gon_stock.event_store import EventStore

    module = api()
    calendar = module.calendar_snapshot('XNAS', '2026-11-12', '2026-11-12')
    with EventStore(tmp_path / 'events.duckdb') as store:
        store.append(event('first'))
        store.append(
            event('third', event_time='2026-11-12T14:32:00Z', received_at='2026-11-12T14:33:01Z')
        )
        rows = store.replay(stamp('2026-11-12T14:35:00Z'))
    report = module.quality_report(
        rows,
        calendar,
        event()['instrument'],
        start=stamp('2026-11-12T14:30:00Z'),
        end=stamp('2026-11-12T14:33:00Z'),
        cutoff=stamp('2026-11-12T14:35:00Z'),
        bar_label='start',
    )
    assert report['gap_candidates'] == ['2026-11-12T14:31:00+00:00']
    assert report['expected_count'] == 3
    assert report['missing_status'] == 'candidates_only'
    holiday = module.calendar_snapshot('XNAS', '2026-11-26', '2026-11-26')
    report = module.quality_report(
        [],
        holiday,
        event()['instrument'],
        start=stamp('2026-11-26T00:00:00Z'),
        end=stamp('2026-11-27T00:00:00Z'),
        cutoff=stamp('2026-11-27T00:00:00Z'),
        bar_label='start',
    )
    assert report['gap_candidates'] == []
    assert report['expected_count'] == 0


def test_duplicate_reverse_and_unverified_are_reported_without_drop(tmp_path):
    from gon_stock.event_store import EventStore

    module = api()
    with EventStore(tmp_path / 'events.duckdb') as store:
        store.append(
            event('first', event_time='2026-11-12T14:31:00Z', received_at='2026-11-12T14:32:00Z')
        )
        store.append(event('late', received_at='2026-11-12T14:33:00Z'))
        store.append(event('repeat', received_at='2026-11-12T14:34:00Z'))
        store.append(
            event(
                'unknown',
                event_time=None,
                clock_status='unverified',
                received_at='2026-11-12T14:34:30Z',
            )
        )
        rows = store.replay(stamp('2026-11-12T14:35:00Z'))
    report = module.quality_report(
        rows,
        module.calendar_snapshot('XNAS', '2026-11-12', '2026-11-12'),
        event()['instrument'],
        start=stamp('2026-11-12T14:30:00Z'),
        end=stamp('2026-11-12T14:35:00Z'),
        cutoff=stamp('2026-11-12T14:35:00Z'),
    )
    assert report['observation_count'] == 4
    assert report['duplicate_candidates'] == ['repeat']
    assert report['reverse_event_time'] == ['late']
    assert report['uncertain_clock'] == ['unknown']
    assert report['missing_status'] == 'bar_label_unverified'


def test_calendar_hash_and_coverage_fail_closed():
    module = api()
    calendar = module.calendar_snapshot('XNAS', '2026-11-12', '2026-11-12')
    calendar['sessions'][0]['open'] = '2026-11-12T00:00:00+00:00'
    with pytest.raises(ValueError, match='calendar_hash_mismatch'):
        module.quality_report(
            [],
            calendar,
            event()['instrument'],
            start=stamp('2026-11-12T14:30:00Z'),
            end=stamp('2026-11-12T14:35:00Z'),
            cutoff=stamp('2026-11-12T14:35:00Z'),
        )


def test_partial_bar_is_not_eligible_even_when_replayed_later(tmp_path):
    from gon_stock.event_store import EventStore

    with EventStore(tmp_path / 'events.duckdb') as store:
        store.append(event(event_time='2026-11-12T14:31:00Z'))
        assert (
            store.strategy_view(stamp('2026-11-12T14:32:00Z'), max_age=timedelta(minutes=10)) == []
        )


def test_gap_report_refuses_mixed_source_environments(tmp_path):
    from gon_stock.event_store import EventStore

    module = api()
    with EventStore(tmp_path / 'events.duckdb') as store:
        store.append(event())
        store.append(event('other', source='kis', environment='real'))
        with pytest.raises(ValueError, match='mixed_streams'):
            module.quality_report(
                store.replay(stamp('2026-11-12T14:32:00Z')),
                module.calendar_snapshot('XNAS', '2026-11-12', '2026-11-12'),
                event()['instrument'],
                start=stamp('2026-11-12T14:30:00Z'),
                end=stamp('2026-11-12T14:32:00Z'),
                cutoff=stamp('2026-11-12T14:32:00Z'),
                bar_label='start',
            )


def test_descending_batch_and_repeated_capture_are_not_late_arrival(tmp_path):
    from gon_stock.event_store import EventStore

    module = api()
    with EventStore(tmp_path / 'events.duckdb') as store:
        for received, prefix, minutes in [
            ('14:35:00', 'first', [33, 32, 31]),
            ('14:36:00', 'again', [34, 33, 32]),
        ]:
            for minute in minutes:
                store.append(
                    event(
                        f'{prefix}_{minute}',
                        received_at=f'2026-11-12T{received}Z',
                        event_time=f'2026-11-12T14:{minute}:00Z',
                    )
                )
        report = module.quality_report(
            store.replay(stamp('2026-11-12T14:37:00Z')),
            module.calendar_snapshot('XNAS', '2026-11-12', '2026-11-12'),
            event()['instrument'],
            start=stamp('2026-11-12T14:30:00Z'),
            end=stamp('2026-11-12T14:37:00Z'),
            cutoff=stamp('2026-11-12T14:37:00Z'),
        )
    assert report['reverse_event_time'] == []
    assert report['duplicate_candidates'] == ['again_33', 'again_32']


def test_late_first_observations_use_prior_batch_high_watermark(tmp_path):
    from gon_stock.event_store import EventStore

    module = api()
    with EventStore(tmp_path / 'events.duckdb') as store:
        for index, minute in enumerate([35, 31, 33]):
            store.append(
                event(
                    f'item{index}',
                    event_time=f'2026-11-12T14:{minute}:00Z',
                    received_at=f'2026-11-12T14:{36 + index}:00Z',
                )
            )
        report = module.quality_report(
            store.replay(stamp('2026-11-12T14:39:00Z')),
            module.calendar_snapshot('XNAS', '2026-11-12', '2026-11-12'),
            event()['instrument'],
            start=stamp('2026-11-12T14:30:00Z'),
            end=stamp('2026-11-12T14:39:00Z'),
            cutoff=stamp('2026-11-12T14:39:00Z'),
        )
    assert report['reverse_event_time'] == ['item1', 'item2']


def test_unknown_clock_different_source_minutes_are_not_duplicates(tmp_path):
    from gon_stock.event_store import EventStore

    module = api()
    with EventStore(tmp_path / 'events.duckdb') as store:
        for minute in (30, 31):
            store.append(
                event(
                    f'm{minute}',
                    event_time=None,
                    clock_status='unverified',
                    source_clock={
                        'status': 'dated_bar',
                        'source_date': '2026-11-12',
                        'source_time': f'14:{minute}:00',
                        'source_timezone': None,
                    },
                )
            )
        report = module.quality_report(
            store.replay(stamp('2026-11-12T14:39:00Z')),
            module.calendar_snapshot('XNAS', '2026-11-12', '2026-11-12'),
            event()['instrument'],
            start=stamp('2026-11-12T14:30:00Z'),
            end=stamp('2026-11-12T14:39:00Z'),
            cutoff=stamp('2026-11-12T14:39:00Z'),
        )
    assert report['duplicate_candidates'] == []
