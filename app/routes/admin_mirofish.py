"""Admin-only MiroFish mock endpoints."""

from flask import Blueprint, jsonify, request

from app.auth.decorators import admin_required
from app.services import mirofish


admin_mirofish_bp = Blueprint('admin_mirofish', __name__)


@admin_mirofish_bp.route('/status', methods=['GET'])
@admin_required
def status():
    return jsonify(mirofish.get_status())


@admin_mirofish_bp.route('/runs', methods=['POST'])
@admin_required
def create_run():
    try:
        run = mirofish.create_run(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify(run), 201


@admin_mirofish_bp.route('/runs', methods=['GET'])
@admin_required
def list_runs():
    try:
        limit = int(request.args.get('limit', 20))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 100))
    return jsonify({'runs': mirofish.list_runs(limit=limit)})


@admin_mirofish_bp.route('/runs/<run_id>', methods=['GET'])
@admin_required
def get_run(run_id):
    try:
        run = mirofish.read_run(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if run is None:
        return jsonify({'error': 'run not found'}), 404
    return jsonify(run)


@admin_mirofish_bp.route('/runs/<run_id>/graph', methods=['GET'])
@admin_required
def get_graph(run_id):
    try:
        graph = mirofish.get_graph(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if graph is None:
        return jsonify({'error': 'run not found'}), 404
    return jsonify(graph)


@admin_mirofish_bp.route('/runs/<run_id>/report', methods=['GET'])
@admin_required
def get_report(run_id):
    try:
        report = mirofish.get_report(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if report is None:
        return jsonify({'error': 'run not found'}), 404
    return jsonify(report)
