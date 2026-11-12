import copy
import hashlib
import importlib
from datetime import UTC, datetime, timedelta

import pytest


def api():
    try:
        return importlib.import_module('gon_stock.event_store')
    except ModuleNotFoundError:
        pytest.fail('P2 event store is not implemented')


def stamp(value):
    return datetime.fromisoformat(value).astimezone(UTC)


def event(identity='a', **changes):
    record = {
        'id': identity,
        'schema_version': 1,
        'instrument': {'exchange': 'NAS', 'symbol': 'TEST', 'currency': 'USD'},
        'kind': 'bar',
        'source': 'synthetic',
        'endpoint': 'us_bars',
        'tr_id': 'fixture',
        'environment': 'synthetic',
        'received_at': '2026-11-12T14:31:02Z',
        'event_time': '2026-11-12T14:30:00Z',
        'clock_status': 'verified',
        'source_clock': {
            'status': 'missing',
            'source_date': None,
            'source_time': None,
            'source_timezone': None,
        },
        'raw_sha256': hashlib.sha256(b'fixture').hexdigest(),
        'data': {'open': '10.00', 'high': '11', 'low': '9', 'close': '10.50', 'volume': '100'},
        'correction_of': None,
        'effective_at': None,
    }
    record.update(changes)
    return record


def test_persistence_replay_and_canonical_instrument(tmp_path):
    module = api()
    path = tmp_path / 'events.duckdb'
    with module.EventStore(path) as store:
        assert store.append(event()) == 1
    with module.EventStore(path) as store:
        rows = store.replay(stamp('2026-11-12T14:32:00Z'))
        assert [r['receipt_seq'] for r in rows] == [1]
        assert rows[0]['instrument'] == {'exchange': 'XNAS', 'symbol': 'TEST', 'currency': 'USD'}
        assert rows[0]['data']['open'] == '10.00'
        assert store.replay(stamp('2026-11-12T14:31:01Z')) == []


def test_duplicates_are_retained_but_id_conflict_is_atomic(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        assert store.append(event()) == store.append(event()) == 1
        assert store.append(event('repeat')) == 2
        bad = event(data={**event()['data'], 'close': '10.25'})
        with pytest.raises(ValueError, match='id_conflict'):
            store.append(bad)
        assert len(store.replay(stamp('2026-11-12T15:00:00Z'))) == 2
        assert store.append(event('next')) == 3


def test_late_event_preserves_receipt_order_and_no_future_leak(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        store.append(event('later', event_time='2026-11-12T14:31:00Z'))
        store.append(
            event('late', event_time='2026-11-12T14:30:00Z', received_at='2026-11-12T14:35:00Z')
        )
        assert [r['id'] for r in store.replay(stamp('2026-11-12T14:34:59Z'))] == ['later']
        assert [r['id'] for r in store.replay(stamp('2026-11-12T14:35:00Z'))] == ['later', 'late']


def test_correction_visible_only_after_receipt_and_original_preserved(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        store.append(event())
        store.append(
            event(
                'fix',
                correction_of='a',
                received_at='2026-11-12T14:35:00Z',
                data={**event()['data'], 'close': '10.25'},
            )
        )
        before = store.strategy_view(stamp('2026-11-12T14:34:00Z'), max_age=timedelta(minutes=10))
        after = store.strategy_view(stamp('2026-11-12T14:35:00Z'), max_age=timedelta(minutes=10))
        assert [r['id'] for r in before] == ['a']
        assert [r['id'] for r in after] == ['fix']
        assert len(store.replay(stamp('2026-11-12T14:35:00Z'))) == 2
        with pytest.raises(ValueError, match='invalid_correction'):
            store.append(event('wrong', correction_of='a', event_time='2026-11-12T14:29:00Z'))


def test_uncertain_future_and_stale_clocks_never_enter_strategy(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        store.append(event('unknown', event_time=None, clock_status='unverified'))
        store.append(event('future', event_time='2026-11-12T15:00:00Z', clock_status='future'))
        store.append(event('old'))
        cutoff = stamp('2026-11-12T14:35:00Z')
        assert len(store.replay(cutoff)) == 3
        assert store.strategy_view(cutoff, max_age=timedelta(seconds=30)) == []
        assert [r['id'] for r in store.strategy_view(cutoff, max_age=timedelta(minutes=10))] == [
            'old'
        ]


def test_split_does_not_leak_before_receipt_or_effective_date(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        store.append(
            event(
                'split',
                kind='split',
                endpoint='corporate_action',
                data={'ratio': '2'},
                effective_at='2026-11-13T14:30:00Z',
            )
        )
        assert store.strategy_view(stamp('2026-11-12T15:00:00Z'), max_age=timedelta(days=3)) == []
        assert [
            r['id']
            for r in store.strategy_view(stamp('2026-11-13T14:30:00Z'), max_age=timedelta(days=3))
        ] == ['split']
        assert store.replay(stamp('2026-11-12T14:31:00Z')) == []


@pytest.mark.parametrize(
    'changes',
    [
        {'data': {'account': '12345678'}},
        {'data': {**event()['data'], 'appsecret': 'never-store'}},
        {'data': {**event()['data'], 'close': float('nan')}},
        {'data': {**event()['data'], 'close': 'NaN'}},
        {'data': {**event()['data'], 'close': '100'}},
        {'data': {**event()['data'], 'volume': '-1'}},
        {'environment': 'unknown'},
        {'source': 'secret-key-value'},
        {'schema_version': 2},
        {'received_at': '2026-11-12T14:31:02'},
        {'event_time': '2026-11-12T15:00:00Z'},
        {'clock_status': 'verified', 'event_time': None},
        {'instrument': {'exchange': 'NAS', 'symbol': "x';DROP TABLE events;--", 'currency': 'USD'}},
        {'instrument': {'exchange': 'NAS', 'symbol': 'TEST', 'currency': 'KRW'}},
    ],
)
def test_invalid_input_never_reaches_storage(tmp_path, changes):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        with pytest.raises(ValueError):
            store.append(event(**changes))
        assert store.replay(stamp('2026-11-12T16:00:00Z')) == []


def test_unknown_fields_refused_and_input_not_mutated(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        original = event()
        before = copy.deepcopy(original)
        store.append(original)
        assert original == before
        with pytest.raises(ValueError):
            store.append({**event('secret'), 'authorization': 'never-store'})


def test_watchlist_normalizes_aliases_and_persists(tmp_path):
    path = tmp_path / 'events.duckdb'
    with api().EventStore(path) as store:
        store.watch({'exchange': 'NASD', 'symbol': 'TEST', 'currency': 'USD'})
        store.watch({'exchange': 'NAS', 'symbol': 'TEST', 'currency': 'USD'})
        assert store.watchlist() == [{'exchange': 'XNAS', 'symbol': 'TEST', 'currency': 'USD'}]
    with api().EventStore(path) as store:
        assert len(store.watchlist()) == 1
        store.unwatch({'exchange': 'XNAS', 'symbol': 'TEST', 'currency': 'USD'})
        assert store.watchlist() == []


def test_parquet_roundtrip_and_corruption_rejected(tmp_path):
    module = api()
    snapshot = tmp_path / 'snapshot'
    with module.EventStore(tmp_path / 'events.duckdb') as store:
        store.append(event())
        expected = store.replay(stamp('2026-11-12T15:00:00Z'))
        manifest = store.export(snapshot)
        assert manifest['row_count'] == 1
        with pytest.raises(FileExistsError):
            store.export(snapshot)
    assert module.read_snapshot(snapshot, stamp('2026-11-12T15:00:00Z')) == expected
    data = snapshot / 'events.parquet'
    data.write_bytes(data.read_bytes() + b'corruption')
    with pytest.raises(ValueError, match='snapshot_hash_mismatch'):
        module.read_snapshot(snapshot, stamp('2026-11-12T15:00:00Z'))


def test_tampered_database_fails_closed(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        store.append(event())
        store.connection.execute("UPDATE events SET body = '{}' WHERE id = 'a'")
        with pytest.raises(ValueError, match='event_hash_mismatch'):
            store.replay(stamp('2026-11-12T15:00:00Z'))


def test_strategy_refuses_mixed_environment_without_selection(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        store.append(event())
        store.append(event('other', source='kis', environment='real'))
        with pytest.raises(ValueError, match='mixed_streams'):
            store.strategy_view(stamp('2026-11-12T14:32:00Z'), max_age=timedelta(minutes=10))


def test_timestamp_offset_preserves_same_instant(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        store.append(
            event(received_at='2026-11-12T23:31:02+09:00', event_time='2026-11-12T09:30:00-05:00')
        )
        row = store.replay(stamp('2026-11-12T14:32:00Z'))[0]
        assert row['event_time'] == '2026-11-12T14:30:00+00:00'
        assert row['received_at'] == '2026-11-12T14:31:02+00:00'


def test_repeated_id_does_not_accept_corrupt_existing_record(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        store.append(event())
        store.connection.execute("UPDATE events SET body = '{}' WHERE id = 'a'")
        with pytest.raises(ValueError, match='event_hash_mismatch'):
            store.append(event())


def test_strategy_latest_uses_received_time_not_import_sequence(tmp_path):
    with api().EventStore(tmp_path / 'events.duckdb') as store:
        store.append(
            event(
                'new',
                received_at='2026-11-12T14:35:00Z',
                data={**event()['data'], 'close': '10.25'},
            )
        )
        store.append(event('old'))
        assert [r['id'] for r in store.replay(stamp('2026-11-12T14:36:00Z'))] == ['new', 'old']
        assert [
            r['id']
            for r in store.strategy_view(
                stamp('2026-11-12T14:36:00Z'), max_age=timedelta(minutes=10)
            )
        ] == ['new']
        snapshot = tmp_path / 'snapshot'
        store.export(snapshot)
        assert [r['id'] for r in api().read_snapshot(snapshot, stamp('2026-11-12T14:34:00Z'))] == [
            'old'
        ]
