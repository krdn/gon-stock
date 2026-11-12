import argparse
import getpass
import json
import subprocess
import sys
from dataclasses import asdict

from gon_stock.kis import ROUTES, ConnectionFailure, Credentials, KisReadClient


def credentials(environment: str, *, register: bool = False) -> Credentials:
    attributes = ['service', 'gon-stock-kis', 'environment', environment]
    try:
        if register:
            if not sys.stdin.isatty():
                raise ConnectionFailure('terminal_required')
            values = Credentials(
                *(
                    getpass.getpass(label)
                    for label in (
                        'App Key: ',
                        'App Secret: ',
                        '계좌번호 앞 8자리: ',
                        '계좌상품코드 2자리: ',
                    )
                )
            )
            with KisReadClient(values, environment):
                pass
            command = ['secret-tool', 'store', '--label=gon-stock KIS', *attributes]
            result = subprocess.run(
                command,
                input=json.dumps(asdict(values)),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                raise ConnectionFailure('credential_store_failed')
            stored = credentials(environment)
            if stored != values:
                raise ConnectionFailure('credential_store_failed')
            return stored
        result = subprocess.run(
            ['secret-tool', 'lookup', *attributes], capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise ConnectionFailure('credentials_missing')
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or set(data) != {
            'app_key',
            'secret_key',
            'account',
            'product',
        }:
            raise ConnectionFailure('invalid_credentials')
        if any(not isinstance(v, str) for v in data.values()):
            raise ConnectionFailure('invalid_credentials')
        return Credentials(**data)
    except (OSError, subprocess.TimeoutExpired, ValueError, EOFError):
        failure = 'credential_store_failed'
    raise ConnectionFailure(failure)


def main():
    parser = argparse.ArgumentParser(description='KIS 읽기 전용 연결 확인')
    parser.add_argument('command', choices=['register', 'probe', *ROUTES])
    parser.add_argument('--environment', choices=['mock', 'real'], required=True)
    parser.add_argument('--symbol')
    parser.add_argument('--exchange')
    args = parser.parse_args()
    try:
        values = credentials(args.environment, register=args.command == 'register')
        if args.command == 'register':
            print('OS 인증 저장소 등록 및 재조회 확인 완료. API 인증은 아직 미검증입니다.')
            return
        params = {
            k: v
            for k, v in {'symbol': args.symbol, 'exchange': args.exchange}.items()
            if v is not None
        }
        operations = [(args.command, params)]
        if args.command == 'probe':
            if params:
                raise ConnectionFailure('invalid_request')
            operations = [
                ('kr_quote', {'symbol': '005930'}),
                ('kr_orderbook', {'symbol': '005930'}),
                ('us_quote', {'symbol': 'AAPL', 'exchange': 'NAS'}),
                ('us_orderbook', {'symbol': 'AAPL', 'exchange': 'NAS'}),
                ('kr_holdings', {}),
                ('us_holdings', {'exchange': 'NASD'}),
            ]
        failed = False
        with KisReadClient(values, args.environment) as client:
            for operation, params in operations:
                try:
                    pages = (
                        client.fetch_pages(operation, **params)
                        if operation.endswith('holdings')
                        else [client.fetch(operation, **params)]
                    )
                    result = {
                        'status': 'ok',
                        'pages': len(pages),
                        'received_at': pages[-1].received_at.isoformat(),
                        'event_time': (
                            pages[-1].event_time.isoformat() if pages[-1].event_time else None
                        ),
                        'clock': asdict(pages[-1].clock) if pages[-1].clock else None,
                        'freshness': 'unverified',
                        'more': pages[-1].more,
                    }
                except ConnectionFailure as error:
                    result = {'status': 'failed', 'code': error.code}
                    failed = True
                print(
                    json.dumps(
                        {'environment': args.environment, 'operation': operation, **result},
                        ensure_ascii=False,
                    )
                )
                if failed:
                    break
        if failed:
            raise SystemExit(1)
    except (ConnectionFailure, KeyboardInterrupt) as error:
        print(
            str(error) if isinstance(error, ConnectionFailure) else '입력을 취소했습니다.',
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
