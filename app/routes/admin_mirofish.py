"""Admin-only MiroFish live endpoints."""

from flask import Blueprint, Response, jsonify, request

from app.auth.decorators import admin_required
from app.services import mirofish
from app.services.mirofish import events as mf_events


admin_mirofish_bp = Blueprint('admin_mirofish', __name__)


@admin_mirofish_bp.route('/status', methods=['GET'])
@admin_required
def status():
    return jsonify(mirofish.get_status())


@admin_mirofish_bp.route('/data-sources', methods=['GET'])
@admin_required
def data_sources():
    return jsonify(mirofish.get_data_sources())


@admin_mirofish_bp.route('/targets/resolve', methods=['GET'])
@admin_required
def resolve_target():
    target = request.args.get('target', '')
    try:
        snapshot = mirofish.resolve_target_snapshot(target)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify(snapshot)


@admin_mirofish_bp.route('/targets/search', methods=['GET'])
@admin_required
def search_targets():
    target = request.args.get('target', '')
    try:
        limit = int(request.args.get('limit', 16))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    return jsonify(mirofish.search_target_candidates(target, limit=limit))


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


@admin_mirofish_bp.route('/runs/<run_id>/events', methods=['GET'])
@admin_required
def get_events(run_id):
    """Polling-based events tail. ?since=N&limit=M."""
    try:
        since = int(request.args.get('since', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'since must be integer'}), 400
    try:
        limit = int(request.args.get('limit', 200))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be integer'}), 400
    limit = max(1, min(limit, 500))
    try:
        result = mf_events.read_events(run_id, since_index=since, max_count=limit)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify(result)


@admin_mirofish_bp.route('/runs/<run_id>/events/stream', methods=['GET'])
@admin_required
def stream_events(run_id):
    """SSE stream — generator yields event-stream until idle timeout."""
    try:
        since = int(request.args.get('since', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'since must be integer'}), 400
    return Response(
        mf_events.stream_events_sse(run_id, since_index=since),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@admin_mirofish_bp.route('/scanner/status', methods=['GET'])
@admin_required
def get_scanner_status():
    return jsonify(mirofish.get_scanner_schedule_status())


@admin_mirofish_bp.route('/scanner/runs', methods=['GET'])
@admin_required
def list_scanner_runs():
    try:
        limit = int(request.args.get('limit', 20))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 100))
    return jsonify({'runs': mirofish.list_scanner_runs(limit=limit)})


@admin_mirofish_bp.route('/scanner/runs', methods=['POST'])
@admin_required
def create_scanner_run():
    try:
        run = mirofish.create_scanner_run(request.get_json(silent=True) or {})
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify(run), 201


@admin_mirofish_bp.route('/scanner/runs/latest', methods=['GET'])
@admin_required
def get_latest_scanner_run():
    run = mirofish.read_latest_scanner_run()
    if run is None:
        return jsonify({'error': 'scanner run not found'}), 404
    return jsonify(run)


@admin_mirofish_bp.route('/scanner/runs/<run_id>', methods=['GET'])
@admin_required
def get_scanner_run(run_id):
    try:
        run = mirofish.read_scanner_run(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if run is None:
        return jsonify({'error': 'scanner run not found'}), 404
    return jsonify(run)


@admin_mirofish_bp.route('/scanner/runs/<run_id>/candidates', methods=['GET'])
@admin_required
def get_scanner_candidates(run_id):
    try:
        candidates = mirofish.read_scanner_candidates(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if candidates is None:
        return jsonify({'error': 'scanner run not found'}), 404
    return jsonify(candidates)


@admin_mirofish_bp.route('/deepseek/status', methods=['GET'])
@admin_required
def deepseek_status():
    include_live = request.args.get('live', '').lower() in {'1', 'true', 'yes'}
    try:
        return jsonify(mirofish.get_deepseek_status(include_live=include_live))
    except mirofish.DeepSeekError as exc:
        return jsonify({'error': str(exc), 'provider': 'deepseek'}), 502


@admin_mirofish_bp.route('/deepseek/scanner-summary', methods=['POST'])
@admin_required
def create_scanner_run_with_deepseek_summary():
    payload = request.get_json(silent=True) or {}
    scanner_payload = payload.get('scanner') if isinstance(payload.get('scanner'), dict) else {}
    if not scanner_payload:
        scanner_payload = {
            key: payload[key]
            for key in ('limit', 'symbols')
            if key in payload
        }
    try:
        run = mirofish.create_scanner_run(scanner_payload)
        summary = mirofish.summarize_scanner_run_with_deepseek(
            run,
            limit=payload.get('summary_limit', payload.get('limit', 5)),
            model=payload.get('model'),
            thinking=bool(payload.get('thinking', False)),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except mirofish.DeepSeekError as exc:
        return jsonify({'error': str(exc), 'provider': 'deepseek'}), 502
    return jsonify({
        'run': run,
        'summary': summary,
        'links': {
            'run': f"/api/admin/mirofish/scanner/runs/{run['id']}",
            'candidates': f"/api/admin/mirofish/scanner/runs/{run['id']}/candidates",
            'telegram': f"/api/admin/mirofish/scanner/runs/{run['id']}/deepseek-summary/telegram",
        },
    }), 201


@admin_mirofish_bp.route('/scanner/runs/<run_id>/deepseek-summary', methods=['POST'])
@admin_required
def summarize_scanner_candidates_with_deepseek(run_id):
    try:
        run = mirofish.read_scanner_run(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if run is None:
        return jsonify({'error': 'scanner run not found'}), 404

    payload = request.get_json(silent=True) or {}
    try:
        summary = mirofish.summarize_scanner_run_with_deepseek(
            run,
            limit=payload.get('limit', 5),
            model=payload.get('model'),
            thinking=bool(payload.get('thinking', False)),
        )
    except mirofish.DeepSeekError as exc:
        return jsonify({'error': str(exc), 'provider': 'deepseek'}), 502
    return jsonify(summary)


@admin_mirofish_bp.route('/scanner/runs/<run_id>/deepseek-summary/telegram', methods=['POST'])
@admin_required
def send_scanner_deepseek_summary_to_telegram(run_id):
    try:
        run = mirofish.read_scanner_run(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if run is None:
        return jsonify({'error': 'scanner run not found'}), 404

    payload = request.get_json(silent=True) or {}
    try:
        summary = payload.get('summary')
        if not isinstance(summary, dict):
            summary = mirofish.summarize_scanner_run_with_deepseek(
                run,
                limit=payload.get('limit', 5),
                model=payload.get('model'),
                thinking=bool(payload.get('thinking', False)),
            )
        message = mirofish.build_summary_telegram_message(summary)
        from app.utils.scheduler import _send_telegram_long
        ok = _send_telegram_long(message, channel=False)
    except mirofish.DeepSeekError as exc:
        return jsonify({'error': str(exc), 'provider': 'deepseek'}), 502
    if not ok:
        return jsonify({'error': 'telegram send failed', 'run_id': run_id}), 502
    return jsonify({
        'ok': True,
        'run_id': run_id,
        'provider': 'deepseek',
        'message_chars': len(message),
        'summary': summary,
    })
