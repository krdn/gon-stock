import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from gon_stock.llm import ProxyClient, ProxyFailure


def load_settings(path: Path) -> tuple[str, str]:
    try:
        config = json.loads(path.read_text())
        if not isinstance(config, dict) or not isinstance(config.get('llm_proxy_base_url'), str):
            raise ProxyFailure('invalid_settings')
        result = subprocess.run(
            ['secret-tool', 'lookup', 'service', 'gon-stock-llm-proxy'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise ProxyFailure('credentials_missing')
        return config['llm_proxy_base_url'], result.stdout.rstrip('\n')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        failure = 'settings_unavailable'
    raise ProxyFailure(failure)


def main():
    parser = argparse.ArgumentParser(description='LLM 프록시 연결·반환 모델 확인')
    parser.add_argument('command', choices=['models', 'probe'])
    parser.add_argument('--settings', type=Path, default=Path('.private/operator-settings.json'))
    parser.add_argument('--model', action='append', default=[])
    args = parser.parse_args()
    if args.command == 'probe' and not args.model:
        parser.error('probe에는 --model이 필요합니다.')
    try:
        base_url, api_key = load_settings(args.settings)
        with ProxyClient(base_url, api_key) as client:
            if args.command == 'models':
                print(json.dumps({'models': client.models()}, ensure_ascii=False))
                return
            for model in args.model:
                result = client.probe(model)
                print(
                    json.dumps(
                        {**asdict(result), 'model_matches': result.model_matches},
                        ensure_ascii=False,
                    )
                )
                if not result.model_matches:
                    raise SystemExit(1)
    except (ProxyFailure, KeyboardInterrupt) as error:
        print(
            str(error) if isinstance(error, ProxyFailure) else '요청을 취소했습니다.',
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
