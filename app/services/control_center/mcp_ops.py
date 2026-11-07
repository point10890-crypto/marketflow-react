"""운영 관제 MCP 서버 — OpenClaw '운영 감독관' 에이전트 전용, 읽기 전용 도구 4개.

기존 MiroFish MCP(19개 읽기 전용 도구, 연구용 `marketflow` 에이전트)와 분리한 별도 서버다.
연구 에이전트의 검증된 도구 계약을 건드리지 않고, 운영 에이전트에게는 관제 결과만 보여 준다.

도구는 모두 data/control_center 의 기록을 읽기만 한다. 재시작·작업 실행·알림 발송·설정 변경 도구는 없다.
조치는 사람에게 '제안' 하는 문장(runbook)으로만 돌려준다.

  python -m app.services.control_center.mcp_ops                       # stdio (OpenClaw 가 실행)
  python -m app.services.control_center.mcp_ops --transport streamable-http --port 8767
"""
from __future__ import annotations

import argparse
import os
from typing import Any

TOOL_NAMES = ('get_control_center_summary', 'list_control_center_incidents',
              'get_control_center_check_history', 'get_control_center_runbook')

# 항목 종류별 사람용 조치 안내 — 에이전트는 이 문장을 근거로 '제안' 만 한다.
RUNBOOK: dict[str, dict[str, Any]] = {
    'port:flask_primary': {
        'meaning': '운영 API(5003)가 응답하지 않는다. 화면 전체가 데이터를 못 받는다.',
        'automatic': 'MarketFlow-Flask-Watchdog 가 5분마다 확인하고 재시작한다.',
        'human': ['watchdog:flask_primary 상태 확인 — 연속 실패면 자동 복구가 안 되는 중',
                  'logs/flask_watchdog.log, logs/flask_server.*.err.log 최근 오류 확인',
                  '필요 시 관리자 PowerShell: Start-ScheduledTask -TaskName MarketFlow-Flask'],
    },
    'heartbeat:scheduler': {
        'meaning': '스케줄러 데몬 하트비트가 멈췄다. 정해진 시각의 데이터 갱신이 돌지 않는다.',
        'automatic': 'MarketFlow-Scheduler-Watchdog 가 5분마다 재시작한다.',
        'human': ['logs/scheduler.log 마지막 오류 확인', 'job:* 항목 중 놓친 실행 확인',
                  '필요 시 관리자 PowerShell: Start-ScheduledTask -TaskName MarketFlow-Scheduler'],
    },
    'public:api_tunnel': {
        'meaning': '외부에서 API 에 닿지 않는다 (Cloudflare 터널). 내부 5003 이 정상이면 터널 문제다.',
        'automatic': 'MarketFlow-Tunnel-Watchdog 가 재시작한다 (30분 쿨다운).',
        'human': ['port:flask_primary 가 정상인지 먼저 확인', 'Windows 서비스 Cloudflared 상태 확인'],
    },
    'public:web': {
        'meaning': '웹 화면(Cloudflare Pages)이 응답하지 않는다.',
        'automatic': '없음',
        'human': ['Cloudflare Pages 프로젝트 bitman-marketflow 배포 상태 확인', '최근 npm run deploy 결과 확인'],
    },
    'security:': {
        'meaning': '보호되어야 할 API 가 토큰 없이 응답했다. 인증 회귀 — 데이터 노출 위험.',
        'automatic': '없음 (사람 판단 필요)',
        'human': ['해당 라우트의 인증 데코레이터·Pro 게이트 경로를 즉시 확인', '직전 배포 커밋 확인 후 되돌림 검토'],
    },
    'gate:': {
        'meaning': '라우트 상태 이상. 404 는 디스크의 코드와 실행 중인 서버가 다름(재시작 필요)을 뜻한다.',
        'automatic': '없음',
        'human': ['404 가 여러 개면 Flask 재시작 필요 여부 확인', '5xx 면 서버 오류 로그 확인'],
    },
    'endpoint:': {
        'meaning': '화면이 쓰는 데이터 API 가 실패하거나 느리거나 데이터가 오래됐다.',
        'automatic': '없음',
        'human': ['같은 화면의 data:* 항목(파일 신선도) 확인', '관련 job:* 항목에서 갱신 작업이 돌았는지 확인'],
    },
    'data:': {
        'meaning': '화면에 쓰이는 데이터 파일이 오래됐거나 없다.',
        'automatic': '스케줄러가 다음 일정에 갱신한다.',
        'human': ['관련 job:* 이 놓쳤으면 관리자 화면 > 잡 상태에서 재실행 (사람이 버튼으로)'],
    },
    'job:': {
        'meaning': '스케줄 작업이 정해진 시각에 성공 기록을 남기지 못했다.',
        'automatic': '스케줄러가 재시도(기본 2회)한다.',
        'human': ['logs/scheduler.log 에서 해당 작업 오류 확인', '관리자 화면 > 잡 상태에서 재실행 여부 판단'],
    },
    'task:': {
        'meaning': 'Windows 작업 스케줄러 작업이 비활성·실패·미등록 상태다.',
        'automatic': '없음',
        'human': ['관리자 PowerShell: Get-ScheduledTask -TaskName <이름> | Get-ScheduledTaskInfo',
                  '등록 스크립트(deploy/register_*.ps1)로 재등록 검토'],
    },
    'provider:': {
        'meaning': '외부 API(텔레그램·DART·KIS·LLM)가 응답하지 않거나 키가 무효다.',
        'automatic': '각 수집기의 재시도·폴백이 동작한다.',
        'human': ['키 만료·한도 초과 여부 확인 (키 값은 공유하지 않는다)'],
    },
    'host:': {
        'meaning': '디스크·메모리 부족 또는 하드웨어 오류(WHEA)·파이썬 비정상 종료 증가.',
        'automatic': '없음',
        'human': ['디스크: 로그·백업 정리', 'WHEA 증가: 배포·스트레스 작업 중단, 하드웨어 점검 (재부팅·BIOS 는 사람만)'],
    },
    'monitor:': {
        'meaning': '관제 실행기 자체의 문제. 다른 항목의 판정이 오래됐을 수 있다.',
        'automatic': '없음',
        'human': ['MarketFlow-ControlCenter-* 작업 상태 확인', 'python -m app.services.control_center status'],
    },
}


def runbook_for(check_id: str) -> dict[str, Any]:
    if check_id in RUNBOOK:
        return {'match': check_id, **RUNBOOK[check_id]}
    for key in sorted((k for k in RUNBOOK if k.endswith(':')), key=len, reverse=True):
        if check_id.startswith(key):
            return {'match': key, **RUNBOOK[key]}
    return {'match': None, 'meaning': '안내 없음', 'automatic': '없음', 'human': []}


def summary(max_items: int = 30) -> dict[str, Any]:
    from app.services.control_center.runner import read_snapshot

    snap = read_snapshot()
    n = max(1, min(int(max_items), 100))
    return {
        'schema': snap.get('schema'), 'generated_at': snap.get('generated_at'), 'overall': snap.get('overall'),
        'monitor': {k: v for k, v in (snap.get('monitor') or {}).items() if k != 'heartbeat'},
        'counts': snap.get('counts'),
        'families': {k: v.get('status') for k, v in (snap.get('families') or {}).items()},
        'critical_pages': [{'path': p['path'], 'label': p['label'], 'status': p['status']}
                           for p in snap.get('pages', []) if p.get('critical')],
        'failing': (snap.get('failing') or [])[:n],
        'warning': (snap.get('warning') or [])[:n],
        'open_incidents': [{k: i.get(k) for k in ('id', 'check_id', 'family', 'target', 'severity', 'opened_at',
                                                   'last_detail', 'occurrences', 'flapping')}
                           for i in (snap.get('open_incidents') or [])[:n]],
        'note': '읽기 전용 관측 결과. 조치는 사람에게 제안만 한다 (get_control_center_runbook).',
    }


def incidents(state: str = 'open', limit: int = 20) -> dict[str, Any]:
    from app.services.control_center import store

    limit = max(1, min(int(limit), 100))
    if state not in ('open', 'recent'):
        raise ValueError('state must be open or recent')
    with store.connect(read_only=True) as conn:
        rows = []
        if conn is not None:
            rows = store.open_incidents(conn, limit) if state == 'open' else store.recent_incidents(conn, limit)
    return {'state': state, 'incidents': rows}


def check_history(check_id: str, hours: float = 24) -> dict[str, Any]:
    from app.services.control_center import store

    hours = max(1.0, min(float(hours), 24 * 14))
    with store.connect(read_only=True) as conn:
        return {'check_id': check_id, 'state': store.get_state(conn, check_id) if conn is not None else None,
                'history': store.history(conn, check_id, hours=hours, limit=200) if conn is not None else []}


def create_server(host: str = '127.0.0.1', port: int = 8767, path: str = '/mcp') -> Any:
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP('MarketFlow Ops Control Center (read-only)', host=host, port=port, streamable_http_path=path,
                  stateless_http=True, json_response=True)

    @mcp.tool()
    def get_control_center_summary(max_items: int = 30) -> dict[str, Any]:
        """Return the latest read-only operations snapshot: overall status, monitor health, failing checks, critical pages, open incidents."""
        return summary(max_items)

    @mcp.tool()
    def list_control_center_incidents(state: str = 'open', limit: int = 20) -> dict[str, Any]:
        """List open (state='open') or recent (state='recent') operations incidents. Read-only."""
        return incidents(state, limit)

    @mcp.tool()
    def get_control_center_check_history(check_id: str, hours: float = 24) -> dict[str, Any]:
        """Return current state and recent observations for one check id (e.g. 'port:flask_primary'). Read-only."""
        return check_history(check_id, hours)

    @mcp.tool()
    def get_control_center_runbook(check_id: str) -> dict[str, Any]:
        """Return the human runbook for a check id: what it means, what recovers automatically, what a person should do. Never executes anything."""
        return runbook_for(check_id)

    return mcp


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description='MarketFlow Ops Control Center MCP (read-only)')
    ap.add_argument('--transport', choices=('stdio', 'streamable-http'), default=os.getenv('CONTROL_CENTER_MCP_TRANSPORT', 'stdio'))
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=int(os.getenv('CONTROL_CENTER_MCP_PORT', '8767')))
    args = ap.parse_args()
    if args.port == 8080:
        raise SystemExit('8080 은 다른 프로젝트 포트입니다')
    create_server(args.host, args.port).run(transport=args.transport)


if __name__ == '__main__':
    main()
