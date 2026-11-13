import argparse
import json

from gon_stock.data_cli import private_path
from gon_stock.event_store import canonical, digest
from gon_stock.portfolio import replay_ledger


def main():
    parser = argparse.ArgumentParser(description='비공개 가상 체결 원장 재생; 주문/전략 실행 없음')
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        source, output = private_path(args.input), private_path(args.output)
        data = json.loads(source.read_text())
        if data['kind'] != 'synthetic-ledger-v1':
            raise ValueError('synthetic_input_required')
        rows = replay_ledger(data['events'], capital=data['capital'], initial_fx=data['initial_fx'])
        result = dict(
            kind='synthetic-ledger-v1',
            source_sha256=digest(canonical(data)),
            rows=rows,
            actual_portfolio_performance='NOT_RUN',
            execution_enabled=False,
        )
        with output.open('x') as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        output.chmod(0o600)
        print(f'원장 {len(rows)}행 저장; 합성 검증, 실제 성과 NOT_RUN')
    except (ValueError, KeyError, TypeError, ArithmeticError, AttributeError, OSError) as exc:
        parser.exit(1, f'{type(exc).__name__}: 원장 입력/출력 실패\n')


if __name__ == '__main__':
    main()
