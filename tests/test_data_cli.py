import json
import subprocess
import sys

from test_event_store import event


def invoke(root, *args):
    return subprocess.run(
        [sys.executable, '-m', 'gon_stock.data_cli', *args],
        cwd=root,
        capture_output=True,
        text=True,
    )


def test_cli_import_replay_export_and_watchlist(tmp_path):
    private = tmp_path / '.private'
    private.mkdir()
    events = private / 'events.jsonl'
    events.write_text(json.dumps(event()) + '\n')
    common = ['--db', '.private/research.duckdb']
    loaded = invoke(tmp_path, *common, 'import', '--input', str(events))
    assert loaded.returncode == 0, loaded.stderr
    assert json.loads(loaded.stdout)['imported'] == 1
    listed = invoke(tmp_path, *common, 'replay', '--at', '2026-11-12T14:32:00Z')
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)[0]['id'] == 'a'
    watch = invoke(
        tmp_path, *common, 'watch', '--exchange', 'NAS', '--symbol', 'TEST', '--currency', 'USD'
    )
    assert watch.returncode == 0
    assert json.loads(invoke(tmp_path, *common, 'watchlist').stdout)[0]['exchange'] == 'XNAS'
    export = invoke(tmp_path, *common, 'export', '--output', '.private/snapshot')
    assert export.returncode == 0, export.stderr
    assert json.loads(export.stdout)['row_count'] == 1
    assert (private / 'snapshot/manifest.json').exists()


def test_cli_refuses_public_path_and_hides_bad_input(tmp_path):
    result = invoke(tmp_path, '--db', 'public.duckdb', 'watchlist')
    assert result.returncode != 0
    assert not (tmp_path / 'public.duckdb').exists()
    private = tmp_path / '.private'
    private.mkdir()
    source = private / 'invalid.jsonl'
    source.write_text(json.dumps({**event(), 'appsecret': 'never-log-this-value'}))
    result = invoke(tmp_path, '--db', '.private/research.duckdb', 'import', '--input', str(source))
    assert result.returncode != 0
    assert 'never-log-this-value' not in result.stdout + result.stderr
    assert 'Traceback' not in result.stderr


def test_incomplete_snapshot_is_not_readable(tmp_path):
    from test_event_store import stamp

    from gon_stock.event_store import read_snapshot

    (tmp_path / 'events.parquet').write_bytes(b'partial')
    try:
        read_snapshot(tmp_path, stamp('2026-11-12T14:32:00Z'))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError('incomplete export was accepted')


def test_cli_quality_writes_calendar_snapshot_and_report(tmp_path):
    private = tmp_path / '.private'
    private.mkdir()
    source = private / 'events.jsonl'
    source.write_text(json.dumps(event()))
    common = ['--db', '.private/research.duckdb']
    assert invoke(tmp_path, *common, 'import', '--input', str(source)).returncode == 0
    result = invoke(
        tmp_path,
        *common,
        'quality',
        '--exchange',
        'NAS',
        '--symbol',
        'TEST',
        '--currency',
        'USD',
        '--start',
        '2026-11-12T14:30:00Z',
        '--end',
        '2026-11-12T14:33:00Z',
        '--at',
        '2026-11-12T14:35:00Z',
        '--output',
        '.private/quality.json',
        '--bar-label',
        'start',
    )
    assert result.returncode == 0, result.stderr
    saved = json.loads((private / 'quality.json').read_text())
    assert saved['report']['expected_count'] == 3
    assert len(saved['report']['gap_candidates']) == 2
    assert saved['calendar']['sha256'] == saved['report']['calendar_sha256']


def test_capture_rejects_invalid_market_before_credentials(tmp_path):
    result = invoke(
        tmp_path,
        '--db',
        '.private/research.duckdb',
        'capture',
        '--exchange',
        'NAS',
        '--symbol',
        'TEST',
        '--currency',
        'KRW',
        '--environment',
        'mock',
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)['code'] == 'data_operation_failed'
    assert not (tmp_path / '.private/research.duckdb').exists()


def test_replay_private_output_prints_only_count_and_hash(tmp_path):
    import hashlib

    private = tmp_path / '.private'
    private.mkdir()
    source = private / 'events.jsonl'
    source.write_text(json.dumps(event()))
    common = ['--db', '.private/research.duckdb']
    assert invoke(tmp_path, *common, 'import', '--input', str(source)).returncode == 0
    result = invoke(
        tmp_path,
        *common,
        'replay',
        '--at',
        '2026-11-12T14:32:00Z',
        '--output',
        '.private/replay.json',
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary['row_count'] == 1
    assert summary['sha256'] == hashlib.sha256((private / 'replay.json').read_bytes()).hexdigest()
    assert '10.50' not in result.stdout
    assert json.loads((private / 'replay.json').read_text())[0]['data']['close'] == '10.50'


def test_private_symlink_escape_and_extreme_age_fail_without_traceback(tmp_path):
    private = tmp_path / '.private'
    private.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (private / 'link').symlink_to(outside, target_is_directory=True)
    escaped = invoke(tmp_path, '--db', '.private/link/data.duckdb', 'watchlist')
    assert escaped.returncode == 1
    assert not (outside / 'data.duckdb').exists()
    huge = invoke(
        tmp_path,
        '--db',
        '.private/data.duckdb',
        'replay',
        '--at',
        '2026-11-12T14:32:00Z',
        '--max-age-seconds',
        '99999999999999999999',
    )
    assert huge.returncode == 1
    assert 'Traceback' not in huge.stderr


def test_empty_output_is_rejected_instead_of_printing_data(tmp_path):
    private = tmp_path / '.private'
    private.mkdir()
    source = private / 'events.jsonl'
    source.write_text(json.dumps(event()))
    common = ['--db', '.private/research.duckdb']
    assert invoke(tmp_path, *common, 'import', '--input', str(source)).returncode == 0
    for command in [
        ['replay', '--at', '2026-11-12T14:32:00Z'],
        [
            'quality',
            '--exchange',
            'NAS',
            '--symbol',
            'TEST',
            '--currency',
            'USD',
            '--start',
            '2026-11-12T14:30:00Z',
            '--end',
            '2026-11-12T14:32:00Z',
            '--at',
            '2026-11-12T14:32:00Z',
        ],
    ]:
        result = invoke(tmp_path, *common, *command, '--output', '')
        assert result.returncode == 1
        assert '10.50' not in result.stdout
