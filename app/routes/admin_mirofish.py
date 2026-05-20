"""Admin-only MiroFish live endpoints."""

import os

from flask import Blueprint, Response, jsonify, request

from app.auth.decorators import admin_required, admin_or_aibain_required
from app.services import mirofish
from app.services.mirofish import events as mf_events


admin_mirofish_bp = Blueprint('admin_mirofish', __name__)


def _telegram_config_status() -> dict:
    personal_token = os.getenv('TELEGRAM_BOT_TOKEN')
    personal_chat = os.getenv('TELEGRAM_CHAT_ID')
    channel_token = os.getenv('TELEGRAM_CHANNEL_BOT_TOKEN')
    channel_chat = os.getenv('TELEGRAM_CHANNEL_CHAT_ID')
    return {
        'personal_configured': bool(personal_token and personal_chat and 'your_bot_token' not in personal_token),
        'channel_configured': bool(channel_token and channel_chat),
        'personal_chat_present': bool(personal_chat),
        'channel_chat_present': bool(channel_chat),
    }


def _payload_bool(payload: dict, key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _payload_float(payload: dict, key: str, default: float) -> float:
    value = payload.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{key} must be a number')


def _payload_int(payload: dict, key: str, default: int) -> int:
    value = payload.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{key} must be an integer')


@admin_mirofish_bp.route('/status', methods=['GET'])
@admin_or_aibain_required
def status():
    return jsonify(mirofish.get_status())


@admin_mirofish_bp.route('/chat', methods=['POST'])
@admin_or_aibain_required
def chat():
    """자연어 채팅 — Gemini function calling 으로 안전한 read-only MCP 도구 호출.

    Request body:
        {
            "message": "이번 TOP 3 알려줘",
            "history": [{"role": "user|assistant", "content": "..."}]  // 옵션
        }
    Response:
        {
            "reply": "...",
            "tool_calls": [{"name", "args", "result_preview"}],
            "iterations": int,
            "method": "llm" | "fallback" | "llm_error"
        }
    """
    payload = request.get_json(silent=True) or {}
    message = payload.get('message', '')
    history = payload.get('history') or []
    if not isinstance(history, list):
        history = []
    try:
        result = mirofish.run_chat_agent(message, history=history)
        return jsonify(result)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@admin_mirofish_bp.route('/chat/telegram', methods=['POST'])
@admin_required
def chat_telegram():
    """채팅 응답 내용을 텔레그램으로 공유.

    HTML/마크다운 혼용된 채팅 응답을 텔레그램 호환 형식으로 정규화 후 전송.
    개인 봇 전용 — 채널 오염 방지.

    Request body:
        {
            "content": "공유할 텍스트 (필수)",
            "question": "원본 사용자 질문 (선택, 헤더용)",
            "channel": false  // 기본 false — 개인 봇만
        }
    Response:
        {
            "ok": bool,
            "telegram_sent": bool,
            "message_chars": int,
            "telegram_config": {...}
        }
    """
    payload = request.get_json(silent=True) or {}
    content = (payload.get('content') or '').strip()
    question = (payload.get('question') or '').strip()
    channel = _payload_bool(payload, 'channel', False)

    if not content:
        return jsonify({'error': 'content is required'}), 400

    # 마크다운 → 텔레그램 HTML 정규화 (간단 변환)
    # **bold** → <b>bold</b>
    import re
    normalized = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', content)
    # 백틱 코드 → <code>
    normalized = re.sub(r'`([^`]+)`', r'<code>\1</code>', normalized)

    header_parts = ['💬 <b>MiroFish 어시스턴트 공유</b>']
    if question:
        # HTML 이스케이프 최소화 — < > & 만
        q_safe = question.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        if len(q_safe) > 200:
            q_safe = q_safe[:197] + '...'
        header_parts.append(f'🙋 <i>질문:</i> {q_safe}')
    header = '\n'.join(header_parts)

    body = f'{header}\n\n{normalized}'

    try:
        from app.utils.scheduler import _send_telegram_long
        ok = _send_telegram_long(body, channel=channel)
    except Exception as exc:
        return jsonify({
            'error': f'telegram send exception: {type(exc).__name__}: {exc}',
            'telegram_config': _telegram_config_status(),
        }), 500

    if not ok:
        return jsonify({
            'ok': False,
            'error': 'telegram send failed',
            'telegram_sent': False,
            'message_chars': len(body),
            'telegram_config': _telegram_config_status(),
        }), 502

    return jsonify({
        'ok': True,
        'telegram_sent': True,
        'message_chars': len(body),
        'telegram_config': _telegram_config_status(),
    })


@admin_mirofish_bp.route('/data-sources', methods=['GET'])
@admin_or_aibain_required
def data_sources():
    return jsonify(mirofish.get_data_sources())


@admin_mirofish_bp.route('/pipeline/today', methods=['GET'])
@admin_or_aibain_required
def pipeline_today():
    """오늘의 검출 파이프라인 + 시장 컨텍스트 스냅샷.

    Returns:
        {
            'generated_at', 'date_kst',
            'market': {'kr': {...}, 'us': {...}},
            'funnel': {'scanner_pool', 'scanner_runs_today', 'batch_new_candidates',
                       'graphrag_uploaded', 'top3_ready', ...},
            'kpi_7d': {'sample_size', 'hit_rate_pct', 'avg_return_pct', ...},
            'kpi_30d': {...},
            'next': {'next_scheduled_scan_at', ...},
            'alerts_today': {'scanner_alerts_today', ...}
        }
    """
    try:
        return jsonify(mirofish.get_pipeline_today_snapshot())
    except Exception as exc:
        return jsonify({
            'error': f'{type(exc).__name__}: {exc}',
            'service': 'mirofish-pipeline-overview',
        }), 500


@admin_mirofish_bp.route('/auto-runner/status', methods=['GET'])
@admin_required
def auto_runner_status():
    """MCP Stage 2 자동 실행기 상태 스냅샷."""
    return jsonify(mirofish.auto_runner.get_status())


@admin_mirofish_bp.route('/auto-runner/pause', methods=['POST'])
@admin_required
def auto_runner_pause():
    """자동 실행기 일시정지 토글. Body: { "paused": true|false }"""
    payload = request.get_json(silent=True) or {}
    paused = _payload_bool(payload, 'paused', True)
    return jsonify(mirofish.auto_runner.set_paused(paused))


@admin_mirofish_bp.route('/auto-runner/reset', methods=['POST'])
@admin_required
def auto_runner_reset():
    """서킷 브레이커 / 오늘 카운터 리셋. Body: { "scope": "circuit"|"today"|"all" }"""
    payload = request.get_json(silent=True) or {}
    scope = str(payload.get('scope') or 'circuit').strip().lower()
    if scope == 'today':
        return jsonify(mirofish.auto_runner.reset_today())
    if scope == 'all':
        mirofish.auto_runner.reset_circuit()
        return jsonify(mirofish.auto_runner.reset_today())
    return jsonify(mirofish.auto_runner.reset_circuit())


@admin_mirofish_bp.route('/auto-runner/tune', methods=['POST'])
@admin_required
def auto_runner_tune():
    """LLM (Gemini) 이 최근 outcomes 분석 → 새 임계값 추천.

    Body (옵션): { "window_days": 14, "apply": false }
    apply=true 면 즉시 in-memory 적용 (Flask 재시작 시 env 우선).
    """
    payload = request.get_json(silent=True) or {}
    try:
        window_days = int(payload.get('window_days') or 14)
    except (TypeError, ValueError):
        return jsonify({'error': 'window_days must be int'}), 400
    apply_now = _payload_bool(payload, 'apply', False)
    try:
        result = mirofish.auto_runner.recommend_thresholds(window_days=window_days)
        if apply_now and result.get('ok') and result.get('recommendation'):
            result['applied'] = mirofish.auto_runner.apply_recommendation_in_memory(result['recommendation'])
        return jsonify(result)
    except Exception as exc:
        return jsonify({
            'error': f'{type(exc).__name__}: {exc}',
            'service': 'mirofish-auto-runner-tuner',
        }), 500


@admin_mirofish_bp.route('/auto-runner/apply-tune', methods=['POST'])
@admin_required
def auto_runner_apply_tune():
    """이전 tune 결과 또는 사용자 제공 임계값을 in-memory 적용.

    Body: { "min_alpha": 55, "max_risk": 60, "min_new_events": 2,
            "cooldown_minutes": 15, "force_after_hours": 4 }
    필드 부분 적용 OK. 모든 값 누락 시 last_recommendation 사용.
    """
    payload = request.get_json(silent=True) or {}
    rec = {k: v for k, v in payload.items() if k in {
        'min_alpha', 'max_risk', 'min_new_events',
        'cooldown_minutes', 'force_after_hours',
    }}
    if not rec:
        # last_recommendation fallback
        status = mirofish.auto_runner.get_status()
        last = (status or {}).get('last_recommendation') or {}
        rec = (last.get('recommendation') or {})
        if not rec:
            return jsonify({'error': 'no last_recommendation; provide thresholds in body'}), 400
    try:
        return jsonify(mirofish.auto_runner.apply_recommendation_in_memory(rec))
    except Exception as exc:
        return jsonify({
            'error': f'{type(exc).__name__}: {exc}',
            'service': 'mirofish-auto-runner-apply-tune',
        }), 500


@admin_mirofish_bp.route('/auto-runner/trigger', methods=['POST'])
@admin_required
def auto_runner_force_trigger():
    """관리자 강제 트리거 — 쿨다운/신규 이벤트 게이트 우회 (시장/freshness는 유지)."""
    try:
        result = mirofish.auto_runner.force_trigger()
        return jsonify(result)
    except Exception as exc:
        return jsonify({
            'error': f'{type(exc).__name__}: {exc}',
            'service': 'mirofish-auto-runner',
        }), 500


@admin_mirofish_bp.route('/outcomes/board', methods=['GET'])
@admin_or_aibain_required
def outcomes_board():
    """최근 N일 워크플로우 추천의 forward outcomes 집계.

    Query:
        days  (int, default 30) — 윈도우 일수
        limit (int, default 20) — 반환 아이템 최대 개수

    Returns:
        {
            'window_days', 'generated_at', 'sample_size', 'workflow_count',
            'summary': {'hit_rate_pct', 'avg_forward_return_pct',
                        'false_positive_pct', 'targets', ...},
            'items': [{'symbol', 'name', 'entry_date', 'status', 'hit',
                       'forward_return_pct', 'horizons', ...}],
        }
    """
    try:
        days = int(request.args.get('days', 30))
    except (TypeError, ValueError):
        return jsonify({'error': 'days must be an integer'}), 400
    try:
        limit = int(request.args.get('limit', 20))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    try:
        return jsonify(mirofish.get_outcomes_board(days=days, limit=limit))
    except Exception as exc:
        return jsonify({
            'error': f'{type(exc).__name__}: {exc}',
            'service': 'mirofish-outcomes-board',
        }), 500


@admin_mirofish_bp.route('/targets/resolve', methods=['GET'])
@admin_or_aibain_required
def resolve_target():
    target = request.args.get('target', '')
    try:
        snapshot = mirofish.resolve_target_snapshot(target)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify(snapshot)


@admin_mirofish_bp.route('/targets/search', methods=['GET'])
@admin_or_aibain_required
def search_targets():
    target = request.args.get('target', '')
    try:
        limit = int(request.args.get('limit', 16))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    return jsonify(mirofish.search_target_candidates(target, limit=limit))


@admin_mirofish_bp.route('/runs', methods=['POST'])
@admin_or_aibain_required
def create_run():
    try:
        payload = request.get_json(silent=True) or {}
        current_user = getattr(request, 'current_user', None)
        if bool(getattr(current_user, 'is_admin', False)):
            run = mirofish.create_run(payload)
            return jsonify(run), 201

        run = mirofish.create_aibain_run_for_user(
            payload,
            user_id=getattr(request, 'current_user_id', None),
            user_email=getattr(request, 'current_user_email', None),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except mirofish.AIBainRunLimitError as exc:
        return jsonify({'error': str(exc), 'subscriber_policy': exc.policy}), exc.status_code
    status_code = 200 if (run.get('subscriber_policy') or {}).get('reused_cached_run') else 202
    return jsonify(run), status_code


@admin_mirofish_bp.route('/runs', methods=['GET'])
@admin_or_aibain_required
def list_runs():
    try:
        limit = int(request.args.get('limit', 20))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 100))
    return jsonify({'runs': mirofish.list_runs(limit=limit)})


@admin_mirofish_bp.route('/runs/<run_id>', methods=['GET'])
@admin_or_aibain_required
def get_run(run_id):
    try:
        run = mirofish.read_run(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if run is None:
        return jsonify({'error': 'run not found'}), 404
    return jsonify(run)


@admin_mirofish_bp.route('/runs/<run_id>/graph', methods=['GET'])
@admin_or_aibain_required
def get_graph(run_id):
    try:
        graph = mirofish.get_graph(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if graph is None:
        return jsonify({'error': 'run not found'}), 404
    return jsonify(graph)


@admin_mirofish_bp.route('/runs/<run_id>/report', methods=['GET'])
@admin_or_aibain_required
def get_report(run_id):
    try:
        report = mirofish.get_report(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if report is None:
        return jsonify({'error': 'run not found'}), 404
    return jsonify(report)


@admin_mirofish_bp.route('/runs/<run_id>/events', methods=['GET'])
@admin_or_aibain_required
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
@admin_or_aibain_required
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
@admin_or_aibain_required
def get_scanner_status():
    return jsonify(mirofish.get_scanner_schedule_status())


@admin_mirofish_bp.route('/scanner/diagnostics', methods=['GET'])
@admin_or_aibain_required
def get_scanner_diagnostics():
    return jsonify(mirofish.get_scanner_diagnostics())


@admin_mirofish_bp.route('/scanner/alerts/state', methods=['GET'])
@admin_or_aibain_required
def get_scanner_alert_state():
    return jsonify(mirofish.read_scanner_alert_state())


@admin_mirofish_bp.route('/scanner/monitor/status', methods=['GET'])
@admin_or_aibain_required
def get_scanner_monitor_status():
    return jsonify(mirofish.read_scanner_monitor_state())


@admin_mirofish_bp.route('/scanner/monitor/check', methods=['POST'])
@admin_required
def check_scanner_monitor():
    payload = request.get_json(silent=True) or {}
    try:
        limit = _payload_int(payload, 'limit', 20)
        min_alpha = _payload_float(payload, 'min_alpha', 70)
        max_risk = _payload_float(payload, 'max_risk', 45)
        max_events = _payload_int(payload, 'max_events', 8)
        retry_seconds = _payload_int(payload, 'retry_seconds', 300)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    force = _payload_bool(payload, 'force', False)
    dry_run = _payload_bool(payload, 'dry_run', False)
    channel = _payload_bool(payload, 'channel', False)
    scanner_payload = {
        key: payload[key]
        for key in ('symbols',)
        if key in payload
    }
    scanner_payload['limit'] = limit

    try:
        send_fn = None
        if not dry_run:
            from app.utils.scheduler import _send_telegram_long

            send_fn = lambda message: _send_telegram_long(message, channel=channel)
        result = mirofish.run_scanner_realtime_monitor_check(
            scanner_payload,
            min_alpha=min_alpha,
            max_risk=max_risk,
            max_events=max_events,
            retry_seconds=retry_seconds,
            force=force,
            commit_monitor_state=not dry_run,
            send_fn=send_fn,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if not dry_run:
        result['telegram_config'] = _telegram_config_status()
    code = 502 if result.get('status') == 'send_failed' else 200
    return jsonify(result), code


@admin_mirofish_bp.route('/scanner/alerts/check', methods=['POST'])
@admin_required
def check_scanner_alerts():
    payload = request.get_json(silent=True) or {}
    try:
        limit = _payload_int(payload, 'limit', 20)
        min_alpha = _payload_float(payload, 'min_alpha', 70)
        max_risk = _payload_float(payload, 'max_risk', 45)
        max_events = _payload_int(payload, 'max_events', 8)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    dry_run = _payload_bool(payload, 'dry_run', False)
    send_telegram = _payload_bool(payload, 'send_telegram', True)
    channel = _payload_bool(payload, 'channel', False)
    scanner_payload = {
        key: payload[key]
        for key in ('symbols',)
        if key in payload
    }
    scanner_payload['limit'] = limit

    try:
        result = mirofish.run_scanner_alert_check(
            scanner_payload,
            min_alpha=min_alpha,
            max_risk=max_risk,
            max_events=max_events,
            commit_state=False,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    events = result.get('events') or []
    telegram_sent = False
    state_committed = False
    state = result.get('state')
    status = 'dry_run' if dry_run else 'checked'

    if dry_run:
        status = 'dry_run'
    elif events and send_telegram:
        from app.utils.scheduler import _send_telegram_long

        telegram_sent = _send_telegram_long(result.get('message') or '', channel=channel)
        if not telegram_sent:
            return jsonify({
                'error': 'telegram send failed',
                'status': 'send_failed',
                'run_id': (result.get('run') or {}).get('id'),
                'new_event_count': len(events),
                'events': events,
                'state_committed': False,
                'message_chars': len(result.get('message') or ''),
                'telegram_config': _telegram_config_status(),
                'alert_blocked': bool(result.get('alert_blocked')),
                'blocked_reason': result.get('blocked_reason'),
            }), 502
        state = mirofish.commit_scanner_alert_events(result)
        state_committed = True
        status = 'sent'
    elif events and not send_telegram:
        status = 'preview'
    else:
        state = mirofish.commit_scanner_alert_events(result)
        state_committed = True
        status = 'no_new_events'

    return jsonify({
        'ok': True,
        'status': status,
        'run_id': (result.get('run') or {}).get('id'),
        'candidate_count': (result.get('run') or {}).get('candidate_count'),
        'new_event_count': len(events),
        'events': events,
        'telegram_sent': telegram_sent,
        'state_committed': state_committed,
        'state': state,
        'message': result.get('message'),
        'message_chars': len(result.get('message') or ''),
        'telegram_config': _telegram_config_status() if send_telegram else None,
        'alert_blocked': bool(result.get('alert_blocked')),
        'blocked_reason': result.get('blocked_reason'),
    })


@admin_mirofish_bp.route('/scanner/runs', methods=['GET'])
@admin_or_aibain_required
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
@admin_or_aibain_required
def get_latest_scanner_run():
    run = mirofish.read_latest_scanner_run()
    if run is None:
        return jsonify({'error': 'scanner run not found'}), 404
    return jsonify(run)


@admin_mirofish_bp.route('/scanner/runs/<run_id>', methods=['GET'])
@admin_or_aibain_required
def get_scanner_run(run_id):
    try:
        run = mirofish.read_scanner_run(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if run is None:
        return jsonify({'error': 'scanner run not found'}), 404
    return jsonify(run)


@admin_mirofish_bp.route('/scanner/runs/<run_id>/candidates', methods=['GET'])
@admin_or_aibain_required
def get_scanner_candidates(run_id):
    try:
        candidates = mirofish.read_scanner_candidates(run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if candidates is None:
        return jsonify({'error': 'scanner run not found'}), 404
    return jsonify(candidates)


def _scanner_artifact_response(run_id: str, filename: str):
    try:
        artifact = mirofish.read_scanner_run_artifact(run_id, filename)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if artifact is None:
        return jsonify({'error': 'scanner artifact not found'}), 404
    return jsonify(artifact)


@admin_mirofish_bp.route('/scanner/runs/<run_id>/feature-vectors', methods=['GET'])
@admin_or_aibain_required
def get_scanner_feature_vectors(run_id):
    return _scanner_artifact_response(run_id, 'feature_vectors.json')


@admin_mirofish_bp.route('/scanner/runs/<run_id>/evidence', methods=['GET'])
@admin_or_aibain_required
def get_scanner_evidence_ledger(run_id):
    return _scanner_artifact_response(run_id, 'evidence_ledger.json')


@admin_mirofish_bp.route('/scanner/runs/<run_id>/rejects', methods=['GET'])
@admin_or_aibain_required
def get_scanner_rejected_candidates(run_id):
    return _scanner_artifact_response(run_id, 'rejected_candidates.json')


@admin_mirofish_bp.route('/workflow/status', methods=['GET'])
@admin_or_aibain_required
def get_workflow_status():
    return jsonify(mirofish.get_workflow_status())


@admin_mirofish_bp.route('/workflows', methods=['GET'])
@admin_or_aibain_required
def list_workflows():
    try:
        limit = int(request.args.get('limit', 20))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 100))
    return jsonify({'workflows': mirofish.list_workflows(limit=limit)})


@admin_mirofish_bp.route('/workflows/latest', methods=['GET'])
@admin_or_aibain_required
def get_latest_workflow():
    workflow = mirofish.read_latest_workflow()
    if workflow is None:
        return jsonify({'error': 'workflow not found'}), 404
    return jsonify(workflow)


@admin_mirofish_bp.route('/workflows/<workflow_id>', methods=['GET'])
@admin_or_aibain_required
def get_workflow(workflow_id):
    try:
        workflow = mirofish.read_workflow(workflow_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if workflow is None:
        return jsonify({'error': 'workflow not found'}), 404
    return jsonify(workflow)


@admin_mirofish_bp.route('/workflows/<workflow_id>/share', methods=['GET'])
@admin_or_aibain_required
def get_workflow_share(workflow_id):
    """카카오톡 공유용 페이로드 — Kakao SDK 'feed' 템플릿에 맞춘 형식.

    Returns:
        {
            'title': str,            # KakaoTalk 공유 카드 제목
            'description': str,      # 설명 (TOP 3 요약)
            'image_url': str,        # 썸네일
            'link_url': str,         # 클릭 시 이동
            'rank': int (선택),       # 단일 종목 공유 시 (?rank=1|2|3)
            'top_items': list,        # 전체 TOP 3 (UI 사이드용)
        }

    쿼리 파라미터:
        rank: 1|2|3 — 특정 종목만 공유 시. 없으면 TOP 3 전체 요약.
    """
    try:
        workflow = mirofish.read_workflow(workflow_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if workflow is None:
        return jsonify({'error': 'workflow not found'}), 404

    rank_param = request.args.get('rank')
    rank = None
    if rank_param:
        try:
            rank = int(rank_param)
            if rank < 1 or rank > 3:
                return jsonify({'error': 'rank must be 1, 2, or 3'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'rank must be integer'}), 400

    payload = mirofish.build_share_payload(workflow, rank=rank)
    return jsonify(payload)


@admin_mirofish_bp.route('/workflows/<workflow_id>/outcomes', methods=['GET'])
@admin_or_aibain_required
def get_workflow_outcomes(workflow_id):
    try:
        outcomes = mirofish.read_workflow_outcomes(workflow_id)
        if outcomes is None:
            outcomes = mirofish.refresh_workflow_outcomes(workflow_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404
    return jsonify(outcomes)


@admin_mirofish_bp.route('/workflows/<workflow_id>/outcomes/refresh', methods=['POST'])
@admin_required
def refresh_workflow_outcomes(workflow_id):
    payload = request.get_json(silent=True) or {}
    horizons = payload.get('horizons') if isinstance(payload.get('horizons'), list) else None
    try:
        outcomes = mirofish.refresh_workflow_outcomes(workflow_id, horizons=horizons)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404
    return jsonify(outcomes)


@admin_mirofish_bp.route('/workflow/scan-analyze', methods=['POST'])
@admin_required
def start_workflow_scan_analyze():
    payload = request.get_json(silent=True) or {}
    dry_run = _payload_bool(payload, 'dry_run', False)
    try:
        result = mirofish.start_workflow_from_scanner_events(
            payload,
            async_mode=not _payload_bool(payload, 'sync', False),
            commit_event_state=_payload_bool(payload, 'commit_event_state', False),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    code = 202 if result.get('status') in {'queued', 'running'} else 200
    return jsonify(result), code


def _autonomous_error_response(exc: Exception):
    if isinstance(exc, PermissionError):
        return jsonify({'error': str(exc), 'service': 'mirofish-autonomous-mcp'}), 403
    if isinstance(exc, ValueError):
        return jsonify({'error': str(exc), 'service': 'mirofish-autonomous-mcp'}), 400
    return jsonify({
        'error': f'{type(exc).__name__}: {exc}',
        'service': 'mirofish-autonomous-mcp',
    }), 500


@admin_mirofish_bp.route('/autonomous/status', methods=['GET'])
@admin_or_aibain_required
def autonomous_status():
    return jsonify(mirofish.get_autonomous_status())


@admin_mirofish_bp.route('/autonomous/learning', methods=['GET'])
@admin_or_aibain_required
def get_autonomous_learning():
    feedback = mirofish.read_learning_feedback()
    if feedback is None:
        return jsonify({'available': False})
    return jsonify({'available': True, **feedback})


@admin_mirofish_bp.route('/autonomous/candidate-alert', methods=['POST'])
@admin_required
def run_autonomous_candidate_alert():
    payload = request.get_json(silent=True) or {}
    try:
        result = mirofish.run_candidate_detection_alert(payload)
    except Exception as exc:
        return _autonomous_error_response(exc)
    code = 502 if result.get('status') == 'send_failed' else 200
    return jsonify(result), code


@admin_mirofish_bp.route('/autonomous/scan-analysis', methods=['POST'])
@admin_required
def run_autonomous_scan_analysis():
    payload = request.get_json(silent=True) or {}
    try:
        result = mirofish.run_autonomous_scan_analysis(payload)
    except Exception as exc:
        return _autonomous_error_response(exc)
    code = 202 if result.get('status') in {'queued', 'running'} else 200
    if result.get('status') == 'telegram_send_failed':
        code = 502
    return jsonify(result), code


@admin_mirofish_bp.route('/autonomous/learning/refresh', methods=['POST'])
@admin_required
def refresh_autonomous_learning():
    payload = request.get_json(silent=True) or {}
    try:
        result = mirofish.refresh_learning_feedback(payload)
    except Exception as exc:
        return _autonomous_error_response(exc)
    return jsonify(result)


@admin_mirofish_bp.route('/autonomous/telegram/latest', methods=['POST'])
@admin_required
def send_latest_autonomous_workflow_telegram():
    payload = request.get_json(silent=True) or {}
    try:
        result = mirofish.send_latest_workflow_telegram(payload)
    except Exception as exc:
        return _autonomous_error_response(exc)
    code = 200 if result.get('ok') else 502
    return jsonify(result), code


@admin_mirofish_bp.route('/deepseek/status', methods=['GET'])
@admin_or_aibain_required
def deepseek_status():
    include_live = request.args.get('live', '').lower() in {'1', 'true', 'yes'}
    try:
        return jsonify(mirofish.get_deepseek_status(include_live=include_live))
    except mirofish.DeepSeekError as exc:
        return jsonify({'error': str(exc), 'provider': 'deepseek'}), 502


@admin_mirofish_bp.route('/tradingview/status', methods=['GET'])
@admin_or_aibain_required
def tradingview_status():
    include_live = request.args.get('live', '').lower() in {'1', 'true', 'yes', 'on'}
    try:
        return jsonify(mirofish.get_tradingview_status(include_live=include_live))
    except Exception as exc:
        return jsonify({'error': str(exc), 'provider': 'tradingview_mcp'}), 502


@admin_mirofish_bp.route('/price-chart/<symbol>', methods=['GET'])
@admin_required
def price_chart(symbol):
    try:
        limit = int(request.args.get('limit', 120))
    except (TypeError, ValueError):
        limit = 120
    try:
        return jsonify(mirofish.read_price_chart(symbol, limit=limit))
    except ValueError as exc:
        return jsonify({'error': str(exc), 'service': 'mirofish-price-chart'}), 400


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
        limit = _payload_int(payload, 'limit', 5)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    fallback_reason = None
    provider = 'deepseek'
    try:
        summary = payload.get('summary')
        if not isinstance(summary, dict):
            try:
                summary = mirofish.summarize_scanner_run_with_deepseek(
                    run,
                    limit=limit,
                    model=payload.get('model'),
                    thinking=bool(payload.get('thinking', False)),
                )
            except mirofish.DeepSeekError as exc:
                fallback_reason = str(exc)
                provider = 'scanner_fallback'
                summary = None
                message = mirofish.build_scanner_run_telegram_message(run, limit=limit)
            else:
                message = mirofish.build_summary_telegram_message(summary)
        else:
            message = mirofish.build_summary_telegram_message(summary)
        from app.utils.scheduler import _send_telegram_long
        ok = _send_telegram_long(message, channel=False)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if not ok:
        return jsonify({
            'error': 'telegram send failed',
            'run_id': run_id,
            'provider': provider,
            'fallback_reason': fallback_reason,
            'telegram_config': _telegram_config_status(),
        }), 502
    return jsonify({
        'ok': True,
        'run_id': run_id,
        'provider': provider,
        'message_source': provider,
        'fallback_reason': fallback_reason,
        'telegram_config': _telegram_config_status(),
        'message_chars': len(message),
        'summary': summary,
    })
