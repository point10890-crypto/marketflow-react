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

from flask import Blueprint, jsonify, request

from app.auth.decorators import admin_or_aibain_required
from app.services.mirofish import scanner_deepverify
from app.services.mirofish import store as mirofish_store
from app.services.mirofish.tradingagents import engine


admin_mirofish_tradingagents_bp = Blueprint('admin_mirofish_tradingagents', __name__)


@admin_mirofish_tradingagents_bp.route('/tradingagents/analyze', methods=['POST'])
@admin_or_aibain_required
def analyze():
    payload = request.get_json(silent=True) or {}
    target = (payload.get('name') or payload.get('symbol') or '').strip()
    if not target:
        return jsonify({'error': 'symbol or name required'}), 400
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
    try:
        ta = engine.run_deep_analysis(target, symbol=run.get('symbol'), brain=brain)
        mirofish_store.attach_tradingagents(run_id, ta)
        return jsonify(ta), 200
    except Exception as exc:  # pragma: no cover - defensive production boundary
        return jsonify({'error': str(exc), 'service': 'mirofish-tradingagents'}), 500


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
