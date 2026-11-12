import hashlib
import json
import subprocess
import sys

from test_backtest import ASSET, BENCHMARK, COSTS, fixture_rows

from gon_stock.backtest import STRATEGY_ID
from gon_stock.event_store import EventStore


def inputs(tmp_path):
    private = tmp_path / '.private'
    private.mkdir()
    rows, calendar = fixture_rows()
    with EventStore(private / 'source.duckdb') as store:
        for row in rows:
            store.append({k: v for k, v in row.items() if k != 'receipt_seq'})
        snapshot = store.export(private / 'snapshot')
    manifest = {
        'schema_version': 1,
        'strategy_id': STRATEGY_ID,
        'dataset_sha256': snapshot['sha256'],
        'universe': [ASSET],
        'benchmark': BENCHMARK,
        'costs': COSTS,
        'calendar': calendar,
        'train_end': '2026-11-09',
        'calibration_end': '2026-11-10',
        'test_end': '2026-11-12',
        'source_kind': 'synthetic',
        'environment': 'synthetic',
        'verified': dict.fromkeys(
            ('bar_labels', 'calendar', 'coverage', 'corporate_actions', 'universe_pit', 'costs'),
            False,
        ),
    }
    (private / 'manifest.json').write_text(json.dumps(manifest))
    return private, manifest


def run(root, output='.private/result.json'):
    return subprocess.run(
        [
            sys.executable,
            '-m',
            'gon_stock.research_cli',
            '--snapshot',
            '.private/snapshot',
            '--manifest',
            '.private/manifest.json',
            '--output',
            output,
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )


def test_pipeline_saves_blocked_report_without_price_stdout(tmp_path):
    private, _ = inputs(tmp_path)
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary['status'] == 'BLOCKED'
    assert summary['sha256'] == hashlib.sha256((private / 'result.json').read_bytes()).hexdigest()
    assert 'entry_price' not in result.stdout
    report = json.loads((private / 'result.json').read_text())
    assert report['evaluation']['probabilities'] == {}
    assert report['simulation']['trades']
    assert len((private / 'p3-runs.jsonl').read_text().splitlines()) == 1
    assert run(tmp_path).returncode == 1


def test_manifest_data_mismatch_and_claimed_environment_are_refused(tmp_path):
    private, manifest = inputs(tmp_path)
    manifest['dataset_sha256'] = '0' * 64
    (private / 'manifest.json').write_text(json.dumps(manifest))
    assert run(tmp_path).returncode == 1
    assert not (private / 'result.json').exists()
    manifest['dataset_sha256'] = json.loads((private / 'snapshot/manifest.json').read_text())[
        'sha256'
    ]
    manifest['environment'] = 'real'
    (private / 'manifest.json').write_text(json.dumps(manifest))
    assert run(tmp_path).returncode == 1


def test_unknown_manifest_secret_is_not_logged(tmp_path):
    private, manifest = inputs(tmp_path)
    manifest['appsecret'] = 'do-not-emit'
    (private / 'manifest.json').write_text(json.dumps(manifest))
    result = run(tmp_path)
    assert result.returncode == 1
    assert 'do-not-emit' not in result.stdout + result.stderr
