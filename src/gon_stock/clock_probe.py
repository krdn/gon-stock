import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gon_stock.cli import credentials
from gon_stock.kis import ConnectionFailure, KisReadClient
from gon_stock.market_clock import select_completed_domestic_bar


def observe_twice(client):
    samples = []
    for index in range(2):
        if index:
            time.sleep(70)
        before = datetime.now(UTC)
        local = before.astimezone(ZoneInfo('Asia/Seoul'))
        if local.weekday() >= 5 or not '09:05:00' <= local.time().isoformat() < '15:25:00':
            raise ConnectionFailure('outside_observation_window')
        result = client.fetch('kr_bars', symbol='005930')
        try:
            stamp = select_completed_domestic_bar(result.payload.get('output2'), before)
        except ValueError as error:
            raise ConnectionFailure(str(error)) from None
        if result.received_at < before:
            raise ConnectionFailure('clock_reversed')
        samples.append(
            {
                'requested_at': before.isoformat(),
                'received_at': result.received_at.isoformat(),
                'completed_bar_time': stamp.isoformat(),
                'positive_volume': True,
            }
        )
    first, second = samples
    elapsed = (
        datetime.fromisoformat(second['requested_at'])
        - datetime.fromisoformat(first['requested_at'])
    ).total_seconds()
    if elapsed < 60 or second['completed_bar_time'] <= first['completed_bar_time']:
        raise ConnectionFailure('clock_not_advanced')
    return samples


def main():
    parser = argparse.ArgumentParser(description='P1 국내 장중 분봉 시각 2회 검증')
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('기존 검증 파일을 덮어쓰지 않습니다.')
    result = {'status': 'FAIL', 'criteria': 'kr-bar-v1', 'environment': 'mock'}
    try:
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', 'src/gon_stock'])
        if sha != args.expected_sha or dirty.returncode != 0:
            raise ConnectionFailure('source_changed')
        result['source_sha'] = sha
        with KisReadClient(credentials('mock'), 'mock') as client:
            result['samples'] = observe_twice(client)
        result['status'] = 'PASS'
    except ConnectionFailure as error:
        result['code'] = error.code
    except (OSError, subprocess.SubprocessError):
        result['code'] = 'local_environment_error'
    result['checked_at'] = datetime.now(UTC).isoformat()
    try:
        with args.output.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    except OSError:
        print('검증 파일 저장 실패')
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False))
    if result['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
