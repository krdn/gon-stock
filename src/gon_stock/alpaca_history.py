import argparse
import getpass
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from gon_stock.data_cli import private_path
from gon_stock.event_store import canonical, digest, utc


def validate_keys(keys):
    if not isinstance(keys, dict) or set(keys) != {'key_id', 'secret_key'}:
        raise ValueError('invalid_credentials')
    if any(
        not isinstance(v, str)
        or not v
        or not v.isascii()
        or any(not 33 <= ord(c) <= 126 for c in v)
        for v in keys.values()
    ):
        raise ValueError('invalid_credentials')
    return keys


def credentials(register=False):
    attributes = ['service', 'gon-stock-alpaca']
    if register:
        if not sys.stdin.isatty():
            raise ValueError('terminal_required')
        keys = validate_keys(
            {
                'key_id': getpass.getpass('Alpaca key ID: '),
                'secret_key': getpass.getpass('Alpaca secret key: '),
            }
        )
        result = subprocess.run(
            ['secret-tool', 'store', '--label=gon-stock Alpaca data', *attributes],
            input=canonical(keys),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode or credentials() != keys:
            raise ValueError('credential_store_failed')
        return keys
    result = subprocess.run(
        ['secret-tool', 'lookup', *attributes], capture_output=True, text=True, timeout=30
    )
    if result.returncode or not result.stdout.strip():
        raise ValueError('credentials_missing')
    return validate_keys(json.loads(result.stdout))


def download(keys, symbols, start, end, directory, *, transport=None):
    keys = validate_keys(keys)
    if not 1 <= len(set(symbols)) == len(symbols) <= 4 or any(
        not isinstance(s, str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,15}', s) for s in symbols
    ):
        raise ValueError('invalid_symbols')
    first, last = utc(start), utc(end)
    if not first < last <= datetime.now(UTC) - timedelta(minutes=15) or last - first > timedelta(
        days=366
    ):
        raise ValueError('invalid_historical_window')
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    params = {
        'symbols': ','.join(symbols),
        'timeframe': '1Min',
        'start': start,
        'end': end,
        'feed': 'sip',
        'adjustment': 'raw',
        'asof': '-',
        'limit': 10000,
        'sort': 'asc',
    }
    counts, tokens, pages = dict.fromkeys(symbols, 0), set(), []
    with httpx.Client(
        base_url='https://data.alpaca.markets',
        timeout=30,
        follow_redirects=False,
        trust_env=False,
        transport=transport,
        headers={'APCA-API-KEY-ID': keys['key_id'], 'APCA-API-SECRET-KEY': keys['secret_key']},
    ) as client:
        for index in range(1000):
            if index:
                time.sleep(0.35)
            response = client.get('/v2/stocks/bars', params=params)
            if response.status_code != 200:
                raise ValueError(f'alpaca_http_{response.status_code}')
            received = datetime.now(UTC).isoformat()
            payload = response.json()
            if not isinstance(payload, dict) or 'next_page_token' not in payload:
                raise ValueError('invalid_response')
            bars, token = payload.get('bars'), payload.get('next_page_token')
            if not isinstance(bars, dict) or set(bars) - set(symbols):
                raise ValueError('invalid_bars')
            for symbol, rows in bars.items():
                if not isinstance(rows, list) or any(
                    not first <= utc(r['t']) <= last for r in rows
                ):
                    raise ValueError('invalid_bar_window')
                counts[symbol] += len(rows)
            page = {
                'source': 'alpaca_sip',
                'params': dict(params),
                'received_at': received,
                'payload_sha256': digest(canonical(payload)),
                'payload': payload,
            }
            path = directory / f'{index:04d}.json'
            with path.open('x') as stream:
                path.chmod(0o600)
                stream.write(canonical(page))
            pages.append({'file': path.name, 'sha256': digest(path.read_bytes())})
            if token is None:
                if not all(counts.values()):
                    raise ValueError('missing_requested_symbol')
                result = {
                    'source': 'alpaca_sip',
                    'counts': counts,
                    'pages': pages,
                    'acceptance': 'NOT_EVALUATED',
                }
                with (directory / 'manifest.json').open('x') as stream:
                    (directory / 'manifest.json').chmod(0o600)
                    stream.write(canonical(result))
                return result
            if not isinstance(token, str) or not token or token in tokens:
                raise ValueError('repeated_page_token')
            tokens.add(token)
            params['page_token'] = token
    raise ValueError('page_limit')


def main():
    parser = argparse.ArgumentParser(description='Alpaca SIP 과거 분봉 원본 확보; 주문·평가 없음')
    parser.add_argument('--register', action='store_true')
    parser.add_argument('--plan')
    parser.add_argument('--output')
    args = parser.parse_args()
    try:
        keys = credentials(register=args.register)
        if args.register and not args.plan and not args.output:
            print('OS 인증 저장소 등록 및 재조회 완료; API 접근은 미검증')
            return
        plan = json.loads(private_path(args.plan).read_text())
        config = plan['markets']['XNAS']
        sessions = config['calendar']['sessions']
        result = download(
            keys,
            config['symbols'],
            sessions[0]['open'],
            (utc(sessions[-1]['close']) - timedelta(microseconds=1)).isoformat(),
            private_path(args.output),
        )
        print(
            json.dumps(
                {
                    'status': 'DOWNLOADED',
                    'counts': result['counts'],
                    'acceptance': result['acceptance'],
                }
            )
        )
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        EOFError,
        httpx.HTTPError,
        subprocess.TimeoutExpired,
    ):
        print(json.dumps({'status': 'ERROR', 'code': 'alpaca_acquisition_failed'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
