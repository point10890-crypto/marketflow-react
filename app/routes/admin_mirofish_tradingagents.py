"""TradingAgents deep-verification endpoints.

URL prefix registered by app.routes: /api/admin/mirofish

On-demand multi-agent deep analysis (4 analysts → bull/bear debate → trader/risk/PM)
for a single target, plus run listing / retrieval / status. Read-only + on-demand
compute; gated by `admin_or_aibain_required` to match sibling analysis endpoints.
The engine itself does NOT check the kill switch — the admin endpoint may run on
demand regardless of MIROFISH_TRADINGAGENTS_DISABLED (that flag only gates the
automated workflow layer).
"""

from __future__ import annotations

import threading

from flask import Blueprint, jsonify, request

from app.auth.decorators import admin_or_aibain_required
from app.services.mirofish import decision_cache, decision_jobs
from app.services.mirofish import scanner_deepverify
from app.services.mirofish import store as mirofish_store
from app.services.mirofish.tradingagents import engine
from app.services.mirofish import multi_mcp_orchestrator


admin_mirofish_tradingagents_bp = Blueprint('admin_mirofish_tradingagents', __name__)

# 비관리자 동기 심층분석의 인플라이트 수 — decision_jobs 백그라운드 잡과 상한을 공유한다.
_SYNC_SLOT_LOCK = threading.Lock()
_sync_running = 0


def _metered_deep_run(run_fn):
    """비관리자(AI Brain 구독자) 호출에 /api/kr/decision/*/analyze 와 같은
    일일 쿼터·동시 상한을 적용해 run_fn() 을 실행한다.

    이 접두 경로가 신설 쿼터의 우회로가 되면 남용 차단이 무의미해진다(2026-09-02).
    관리자는 종전대로 무제한 — 기존 운영 사용을 깨지 않는다.
    """
    global _sync_running
    user = getattr(request, 'current_user', None)
    if user is None or getattr(user, 'is_admin', False):
        return run_fn()

    with _SYNC_SLOT_LOCK:
        cap = decision_jobs._max_concurrent()
        if decision_jobs.running_count() + _sync_running >= cap:
            return jsonify({'error': 'busy', 'max_concurrent': cap,
                            'detail': '동시에 실행 중인 심층 분석이 많습니다. 잠시 후 다시 시도해 주세요.'}), 429
        _sync_running += 1
    try:
        allowed, _remaining, limit = decision_cache.consume_deep_quota(user.id)
        if not allowed:
            return jsonify({'error': 'quota_exceeded', 'limit': limit, 'remaining': 0,
                            'detail': f'심층 분석 일일 한도({limit}회)를 모두 사용했습니다. 내일 다시 이용해 주세요.'}), 429
        return run_fn()
    finally:
        with _SYNC_SLOT_LOCK:
            _sync_running = max(0, _sync_running - 1)


@admin_mirofish_tradingagents_bp.route('/tradingagents/analyze', methods=['POST'])
@admin_or_aibain_required
def analyze():
    payload = request.get_json(silent=True) or {}
    target = (payload.get('name') or payload.get('symbol') or '').strip()
    if not target:
        return jsonify({'error': 'symbol or name required'}), 400

    def _run():
        try:
            rounds = payload.get('rounds')
            run = engine.run_deep_analysis(
                target,
                symbol=payload.get('symbol'),
                rounds=int(rounds) if rounds else None,
            )
            return jsonify(run), 200
        except Exception as exc:  # pragma: no cover - defensive production boundary
            return jsonify({'error': str(exc), 'service': 'mirofish-tradingagents'}), 500

    return _metered_deep_run(_run)


@admin_mirofish_tradingagents_bp.route('/tradingagents/runs', methods=['GET'])
@admin_or_aibain_required
def list_runs():
    try:
        limit = int(request.args.get('limit', 20))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 50))
    return jsonify({'runs': engine.list_runs(limit=limit)}), 200


@admin_mirofish_tradingagents_bp.route('/tradingagents/runs/<run_id>', methods=['GET'])
@admin_or_aibain_required
def get_run(run_id: str):
    run = engine.get_run(run_id)
    if run is None:
        return jsonify({'error': 'run not found'}), 404
    return jsonify(run), 200


@admin_mirofish_tradingagents_bp.route('/tradingagents/status', methods=['GET'])
@admin_or_aibain_required
def status():
    return jsonify(engine.get_status()), 200


@admin_mirofish_tradingagents_bp.route('/tradingagents/multi-mcp/architecture', methods=['GET'])
@admin_or_aibain_required
def multi_mcp_architecture():
    return jsonify(multi_mcp_orchestrator.architecture_manifest()), 200


@admin_mirofish_tradingagents_bp.route('/tradingagents/multi-mcp/analyze', methods=['POST'])
@admin_or_aibain_required
def multi_mcp_analyze():
    payload = request.get_json(silent=True) or {}
    candidates = payload.get('candidates')
    if candidates is not None and not isinstance(candidates, list):
        return jsonify({'error': 'candidates must be a list when provided'}), 400

    def _run():
        try:
            options = {
                'use_llm': bool(payload.get('use_llm', True)),
                'max_parallel': int(payload.get('max_parallel') or 3),
            }
            if candidates is None:
                result = multi_mcp_orchestrator.run_live_market_scan(**options)
            else:
                result = multi_mcp_orchestrator.run_multi_mcp_analysis(
                    candidates,
                    input_mode='authenticated_debug',
                    **options,
                )
            return jsonify(result), 200
        except Exception as exc:
            return jsonify({'error': str(exc), 'service': 'mirofish-multi-mcp'}), 500

    return _metered_deep_run(_run)


@admin_mirofish_tradingagents_bp.route('/runs/<run_id>/tradingagents', methods=['POST'])
@admin_or_aibain_required
def analyze_run(run_id: str):
    """라이브 run 의 Brain 13D 를 TradingAgents 딥검증에 주입하고 결과를 run 에 부착."""
    run = mirofish_store.read_run(run_id)
    if run is None:
        return jsonify({'error': 'run not found'}), 404
    target = (run.get('display_name') or run.get('target') or '').strip()
    if not target:
        return jsonify({'error': 'run has no target'}), 400
    brain = run.get('brain_summary') or None

    def _run():
        try:
            ta = engine.run_deep_analysis(target, symbol=run.get('symbol'), brain=brain)
            mirofish_store.attach_tradingagents(run_id, ta)
            return jsonify(ta), 200
        except Exception as exc:  # pragma: no cover - defensive production boundary
            return jsonify({'error': str(exc), 'service': 'mirofish-tradingagents'}), 500

    return _metered_deep_run(_run)


@admin_mirofish_tradingagents_bp.route('/scanner/tradingagents/history', methods=['GET'])
@admin_or_aibain_required
def scanner_history():
    """스캐너 이벤트 자동 딥검증 히스토리(최근순)."""
    try:
        limit = int(request.args.get('limit', 50))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 200))
    records = scanner_deepverify.history(limit=limit)
    return jsonify({'records': records, 'count': len(records)}), 200
