"""miniPC env 가 로드된 상태에서 aibain helper + autonomous_mcp hook 검증."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# .env 강제 로드
env_path = ROOT / '.env'
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if k and v:
                os.environ.setdefault(k, v)


def main():
    from app.utils.aibain_notify import is_configured, send, send_scanner_alert, send_workflow_top3

    print('configured:', is_configured())
    if not is_configured():
        print('❌ env 미설정. AIBAIN_NOTIFY_ENABLED / TOKEN / CHAT_ID 확인 필요.')
        sys.exit(1)

    # 1) 기본 send
    ok1 = send('🧪 <b>AIbain helper</b> 직접 호출 테스트')
    print(f'send():                {ok1}')

    # 2) scanner alert mock
    ok2 = send_scanner_alert(
        '<b>스캐너 신규 후보</b>\n'
        '#1 한일단조 (024740) — Alpha 78 / Risk 32\n'
        '#2 대한전선 (001440) — Alpha 75 / Risk 41\n'
        '#3 실리콘투 (257720) — Alpha 73 / Risk 35'
    )
    print(f'send_scanner_alert():  {ok2}')

    # 3) workflow top3 mock
    ok3 = send_workflow_top3(
        '<b>MCP TOP 3 자동 분석</b>\n'
        '#1 현대차 BUY 75% (score 82)\n'
        '#2 현대무벡스 BUY 75% (score 77)\n'
        '#3 기아 BUY 75% (score 76)'
    )
    print(f'send_workflow_top3():  {ok3}')

    print()
    print('→ AIbain_bot 텔레그램에 3개 메시지 도착 확인하세요.')


if __name__ == '__main__':
    main()
