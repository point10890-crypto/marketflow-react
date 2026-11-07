"""MarketFlow 운영 관제 센터 (Control Center).

앱 전체 운영 상태를 한 곳에서 본다: 모든 API 엔드포인트, 메뉴 화면, 데이터 신선도,
스케줄 작업, Windows 작업 스케줄러, 외부 API, 프로세스·포트, 호스트.

구조
- 감시 실행기(`python -m app.services.control_center run`)는 Flask 와 **별도 프로세스**다.
  Flask 가 죽어도 관제는 계속되고 그 사실을 기록·알림한다. `create_app()` 을 부르지 않는다.
- 결과는 `data/control_center/` 의 SQLite + `latest.json` 에 쌓이고,
  Flask 는 읽기 전용 API(`/api/admin/control-center/*`, 관리자 전용)로 보여 준다.
- 감시·판정·알림은 결정론적 코드가 한다. OpenClaw 같은 LLM 에이전트는 이 결과를
  읽기 전용 MCP 도구로 읽고 요약·분류·조치 제안만 한다 (docs/control_center_design_2026_11_07.md).

절대 규칙: 쓰기 HTTP 요청을 보내지 않는다(GET/HEAD 만). 8080 포트를 건드리지 않는다.
비밀값을 기록·출력하지 않는다(설정 여부만). 주문·매매 경로 없음.
"""
from __future__ import annotations

import os

from app.utils.paths import BASE_DIR, DATA_DIR, LOGS_DIR

CC_DIR = os.path.join(DATA_DIR, 'control_center')


def cc_dir() -> str:
    """관제 데이터 폴더 — CONTROL_CENTER_DIR 로 바꿀 수 있다(테스트·다른 드라이브)."""
    return os.environ.get('CONTROL_CENTER_DIR') or CC_DIR


CONTRACTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contracts.json')

__all__ = ['BASE_DIR', 'CC_DIR', 'CONTRACTS_PATH', 'DATA_DIR', 'LOGS_DIR', 'cc_dir']
