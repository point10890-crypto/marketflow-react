"""K-Analyst analysis endpoints for MiroFish.

URL prefix registered by app.routes: /api/admin/mirofish
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.auth.decorators import admin_or_aibain_required
from app.services.mirofish import k_analyst_engine


admin_mirofish_analysis_bp = Blueprint('admin_mirofish_analysis', __name__)


@admin_mirofish_analysis_bp.route('/tech-engine/analyze', methods=['POST'])
@admin_or_aibain_required
def analyze_tech_engine():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(k_analyst_engine.analyze_technical_packet(payload)), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive production boundary
        return jsonify({'error': str(exc), 'service': 'mirofish-k-analyst-tech-engine'}), 500


@admin_mirofish_analysis_bp.route('/analysis/readiness', methods=['POST'])
@admin_or_aibain_required
def analyze_readiness():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(k_analyst_engine.assess_analysis_readiness(payload)), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:  # pragma: no cover
        return jsonify({'error': str(exc), 'service': 'mirofish-k-analyst-readiness'}), 500


@admin_mirofish_analysis_bp.route('/analysis/bayesian-verdict', methods=['POST'])
@admin_or_aibain_required
def analyze_bayesian_verdict():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(k_analyst_engine.build_bayesian_verdict(payload)), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:  # pragma: no cover
        return jsonify({'error': str(exc), 'service': 'mirofish-k-analyst-bayesian'}), 500


@admin_mirofish_analysis_bp.route('/scanner/runs/<run_id>/k-analyst', methods=['GET'])
@admin_or_aibain_required
def scanner_run_k_analyst(run_id: str):
    try:
        limit = int(request.args.get('limit', 5))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    result = k_analyst_engine.build_scanner_run_k_analyst(run_id, limit=limit)
    status_code = 404 if result.get('status') == 'scanner_run_not_found' else 200
    return jsonify(result), status_code
