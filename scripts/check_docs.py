"""Git에 등록한 Markdown의 로컬 링크와 코드블록을 검사한다."""

from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit


def check_document(path: Path, root: Path) -> list[str]:
    errors = []
    in_fence = False
    fence_character = ''
    fence_length = 0
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        fence = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                in_fence = False
            continue
        if in_fence:
            continue
        for target in re.findall(r'\]\(([^\s)]+)\)', line):
            parsed = urlsplit(target.strip('<>'))
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resolved = (path.parent / unquote(parsed.path)).resolve()
            if not resolved.is_relative_to(root) or not resolved.exists():
                errors.append(f'{path.relative_to(root)}:{number}: 로컬 링크 대상 없음: {target}')
    if in_fence:
        errors.append(f'{path.relative_to(root)}: 닫히지 않은 코드블록')
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ['git', 'ls-files', '-z', '--', '*.md'],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths = [root / name for name in result.stdout.decode().split('\0') if name]
    errors = [error for path in paths for error in check_document(path, root)]
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f'Markdown {len(paths)}개: 로컬 링크·코드블록 검사 통과 (외부 URL·앵커 제외)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
