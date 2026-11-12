import argparse
import json
from datetime import timedelta
from pathlib import Path

import duckdb

from gon_stock.backtest import STRATEGY_ID, backtest
from gon_stock.data_cli import private_path
from gon_stock.evaluation import evaluate
from gon_stock.event_store import canonical, digest, read_snapshot, utc

MANIFEST_FIELDS = {
    'schema_version',
    'strategy_id',
    'dataset_sha256',
    'universe',
    'benchmark',
    'costs',
    'calendar',
    'train_end',
    'calibration_end',
    'test_end',
    'source_kind',
    'environment',
    'verified',
}


def main():
    parser = argparse.ArgumentParser(description='비공개 장중 기준 전략·시점 분리 평가')
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        snapshot, manifest_path, output = [
            private_path(value) for value in (args.snapshot, args.manifest, args.output)
        ]
        if output.exists():
            raise FileExistsError('output_exists')
        manifest = json.loads(manifest_path.read_text())
        if (
            not isinstance(manifest, dict)
            or set(manifest) != MANIFEST_FIELDS
            or type(manifest['schema_version']) is not int
            or manifest['schema_version'] != 1
            or manifest['strategy_id'] != STRATEGY_ID
        ):
            raise ValueError('invalid_manifest')
        snapshot_meta = json.loads((snapshot / 'manifest.json').read_text())
        if snapshot_meta['sha256'] != manifest['dataset_sha256']:
            raise ValueError('dataset_hash_mismatch')
        cutoff = utc(manifest['test_end'] + 'T00:00:00+00:00') + timedelta(days=1)
        rows = read_snapshot(snapshot, cutoff - timedelta(microseconds=1))
        if any(row['environment'] != manifest['environment'] for row in rows):
            raise ValueError('environment_mismatch')
        simulation = backtest(
            rows,
            manifest['calendar'],
            manifest['universe'],
            manifest['benchmark'],
            manifest['costs'],
        )
        days = [row['date'] for row in manifest['calendar']['sessions']]
        assessment = evaluate(simulation, days, manifest)
        code_hash = digest(
            b''.join(
                path.name.encode() + path.read_bytes()
                for path in sorted(Path(__file__).parent.glob('*.py'))
            )
        )
        contract_hash = digest(canonical(manifest))
        ledger = private_path('.private/p3-runs.jsonl')
        prior = (
            [json.loads(line) for line in ledger.read_text().splitlines()]
            if ledger.exists()
            else []
        )
        holdout = digest(
            canonical(
                {
                    key: manifest[key]
                    for key in ('universe', 'benchmark', 'calibration_end', 'test_end')
                }
            )
        )
        used = [entry for entry in prior if entry['holdout_sha256'] == holdout]
        if used:
            assessment['blockers'].append('holdout_reused')
            assessment['status'] = 'BLOCKED'
            assessment['probabilities'] = {}
        report = {
            'strategy_id': STRATEGY_ID,
            'source_kind': manifest['source_kind'],
            'dataset_sha256': manifest['dataset_sha256'],
            'contract_sha256': contract_hash,
            'code_sha256': code_hash,
            'holdout_attempt': len(used) + 1,
            'evaluation': assessment,
            'simulation': simulation,
        }
        record = {
            'dataset_sha256': manifest['dataset_sha256'],
            'contract_sha256': contract_hash,
            'code_sha256': code_hash,
            'holdout_sha256': holdout,
            'status': assessment['status'],
        }
        with ledger.open('a') as stream:
            ledger.chmod(0o600)
            stream.write(canonical(record) + '\n')
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with output.open('x') as stream:
            output.chmod(0o600)
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print(
            json.dumps(
                {
                    'status': assessment['status'],
                    'sha256': digest(output.read_bytes()),
                    'counts': assessment['counts'],
                    'blockers': assessment['blockers'],
                }
            )
        )
    except (ValueError, TypeError, KeyError, OSError, OverflowError, duckdb.Error):
        print(json.dumps({'status': 'ERROR', 'code': 'research_operation_failed'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
