"""Hermes sidecar endpoints for MiroFish.

URL prefix registered by app.routes: /api/admin/mirofish
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.auth.decorators import admin_required, admin_or_aibain_required
from app.services.mirofish import hermes_bridge


admin_mirofish_hermes_bp = Blueprint('admin_mirofish_hermes', __name__)


@admin_mirofish_hermes_bp.route('/hermes/status', methods=['GET'])
@admin_or_aibain_required
def hermes_status():
    return jsonify(hermes_bridge.build_hermes_bridge_status()), 200


@admin_mirofish_hermes_bp.route('/hermes/manifest', methods=['GET'])
@admin_required
def hermes_manifest():
    return jsonify(hermes_bridge.build_hermes_mcp_manifest()), 200


@admin_mirofish_hermes_bp.route('/hermes/runbook', methods=['GET'])
@admin_required
def hermes_runbook():
    return jsonify(hermes_bridge.build_hermes_runbook()), 200


@admin_mirofish_hermes_bp.route('/hermes/prompt-pack', methods=['GET'])
@admin_required
def hermes_prompt_pack():
    return jsonify(hermes_bridge.build_hermes_prompt_pack()), 200


@admin_mirofish_hermes_bp.route('/hermes/learning-task-pack', methods=['GET', 'POST'])
@admin_required
def hermes_learning_task_pack():
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
    else:
        payload = {
            'mode': request.args.get('mode'),
            'horizon_days': request.args.get('horizon_days'),
            'limit_workflows': request.args.get('limit_workflows'),
        }
    return jsonify(hermes_bridge.build_hermes_learning_task_pack(payload)), 200


@admin_mirofish_hermes_bp.route('/hermes/preview', methods=['POST'])
@admin_required
def hermes_preview():
    payload = request.get_json(silent=True) or {}
    return jsonify(hermes_bridge.preview_hermes_task(payload)), 200
