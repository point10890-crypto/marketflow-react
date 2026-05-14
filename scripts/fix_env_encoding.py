"""`.env` 의 깨진 비-UTF-8 한글 주석 라인을 제거하고 UTF-8 로 재저장.

PowerShell `Set-Content` (ANSI default) 으로 한글 주석이 깨졌을 때 응급 복구.
환경변수 라인 (KEY=VALUE) 은 ASCII 이므로 보존됨.

사용:
    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python.exe scripts\\fix_env_encoding.py
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(ROOT, '.env')
BACKUP_PATH = os.path.join(ROOT, '.env.broken.bak')


def main() -> int:
    if not os.path.isfile(ENV_PATH):
        print(f'.env not found at {ENV_PATH}')
        return 1

    # 1) raw bytes 읽기 + backup
    with open(ENV_PATH, 'rb') as f:
        raw = f.read()
    shutil.copy(ENV_PATH, BACKUP_PATH)
    print(f'backup: {BACKUP_PATH} ({len(raw)} bytes)')

    # 2) errors='replace' 로 decode → 깨진 부분은 U+FFFD 로
    text = raw.decode('utf-8', errors='replace')

    # 3) 라인별 검사: 깨진 chr 포함된 라인 제거 (주석 한글이 대부분)
    in_lines = text.splitlines()
    kept: list[str] = []
    removed: list[str] = []
    for line in in_lines:
        if '�' in line:
            removed.append(line[:80])
            continue
        kept.append(line)

    # 4) 환경변수 보존 확인
    kept_text = '\n'.join(kept).rstrip() + '\n'

    # 5) UTF-8 (no BOM) 으로 다시 쓰기
    with open(ENV_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(kept_text)

    print(f'kept {len(kept)} lines, removed {len(removed)} broken lines')
    for r in removed:
        print(f'  removed: {r}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
