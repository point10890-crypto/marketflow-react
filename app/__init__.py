# app/__init__.py
"""Flask 애플리케이션 팩토리 (KR Market + Auth + Stripe)"""

import os
import sys
from flask import Flask, make_response, request
from flask.json.provider import DefaultJSONProvider

# 패키지 루트 경로 추가 + OneDrive/외부 경로 오염 방지
_app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_blocked = ['kr_market_package', 'OneDrive', '바탕 화면', 'desktop',
            'closing_bet', 'us-market-pro', 'korean market']
sys.path = [p for p in sys.path if not any(b.lower() in p.lower() for b in _blocked)]
sys.path.insert(0, _app_root)


import math


def _sanitize_nan(obj):
    """재귀적으로 NaN/Infinity float 값을 None 으로 치환.

    문자열 치환(`.replace("NaN", "null")`) 은 stock 이름 등 합법적 'NaN'
    부분 문자열까지 손상시키므로 값 단계에서 처리해야 한다.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_nan(v) for v in obj]
    return obj


class SafeJSONProvider(DefaultJSONProvider):
    """NaN/Infinity → null 변환 (JSON 표준 준수)"""
    def dumps(self, obj, **kwargs):
        kwargs.setdefault("default", self.default)
        return super().dumps(_sanitize_nan(obj), **kwargs)


def create_app(config=None):
    """Flask 앱 팩토리 함수"""
    app = Flask(__name__)
    app.json_provider_class = SafeJSONProvider
    app.json = SafeJSONProvider(app)

    # CORS 설정 (옵셔널)
    try:
        from flask_cors import CORS
        allowed_origins = [
            "http://localhost:5173",
            "http://localhost:4000",
            "https://bitman-marketflow.pages.dev",
            "https://www.bit-man.net",
            "https://bit-man.net",
            "https://marketflow-api.bit-man.net",
        ]
        CORS(app, resources={r"/api/*": {"origins": allowed_origins}})
    except ImportError:
        print("flask-cors not installed, CORS disabled")

    # 환경변수 로드
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # 기본 설정
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'marketflow-secret-key-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(
        os.path.abspath(os.path.dirname(os.path.dirname(__file__))), 'data', 'users.db'
    ).replace('\\', '/')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 설정 적용
    if config:
        app.config.update(config)

    if not app.config.get('SQLALCHEMY_ENGINE_OPTIONS'):
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        engine_options = {'pool_pre_ping': True}
        if ':memory:' not in db_uri:
            engine_options.update({
                'pool_size': int(os.getenv('SQLALCHEMY_POOL_SIZE', '20')),
                'max_overflow': int(os.getenv('SQLALCHEMY_MAX_OVERFLOW', '40')),
                'pool_timeout': int(os.getenv('SQLALCHEMY_POOL_TIMEOUT', '10')),
                'pool_recycle': int(os.getenv('SQLALCHEMY_POOL_RECYCLE', '1800')),
            })
            if db_uri.startswith('sqlite:///'):
                engine_options['connect_args'] = {'check_same_thread': False}
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options

    # Database
    from app.models import db
    db.init_app(app)
    with app.app_context():
        from app.models.user import User, AdminAuditLog  # noqa: F401
        from app.models.wave import WaveSignal, WaveTracking, WavePatternStats  # noqa: F401
        from app.models.community import Board, Post, PostImage, Comment  # noqa: F401
        db.create_all()

        # Idempotent migration: add columns if missing
        try:
            from sqlalchemy import text, inspect
            inspector = inspect(db.engine)

            # subscription_requests 테이블
            sr_cols = [c['name'] for c in inspector.get_columns('subscription_requests')]
            with db.engine.begin() as conn:
                if 'depositor_name' not in sr_cols:
                    conn.execute(text('ALTER TABLE subscription_requests ADD COLUMN depositor_name VARCHAR(100)'))
                if 'amount' not in sr_cols:
                    conn.execute(text('ALTER TABLE subscription_requests ADD COLUMN amount VARCHAR(50)'))

            # users 테이블 — pro_expires_at, pro_expiry_alert_stage 컬럼 추가
            user_cols = [c['name'] for c in inspector.get_columns('users')]
            with db.engine.begin() as conn:
                if 'pro_expires_at' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN pro_expires_at DATETIME'))
                if 'pro_expiry_alert_stage' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN pro_expiry_alert_stage VARCHAR(10)'))
        except Exception:
            pass  # table may not exist yet (create_all handles it)

    # Blueprint 등록
    from app.routes import register_blueprints
    register_blueprints(app)

    # ── API Cache-Control 정책 ──
    @app.after_request
    def add_cache_headers(response):
        """JSON API: 기본 30초 브라우저 캐시 허용, 실시간 엔드포인트는 개별 no-cache 설정

        - /api/admin/*, /api/auth/*: 운영자·계정 상태는 즉시 반영 필요 → no-store
        - 그 외: 기존 정책 (30초 브라우저 캐시)
        """
        if response.content_type and 'application/json' in response.content_type:
            path = (request.path or '')
            if path.startswith('/api/admin/') or path.startswith('/api/auth/'):
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                response.headers['Pragma'] = 'no-cache'
            elif not response.headers.get('Cache-Control'):
                response.headers['Cache-Control'] = 'public, max-age=30'

        # Security headers (all responses)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response

    # ═══════════════════════════════════════════════════════
    #  App-wide access gate: pro/premium만 데이터 API 접근 허용
    # ═══════════════════════════════════════════════════════
    # 'free' 플랜 폐지 (2026-04-06). 앱의 데이터 엔드포인트는 status=approved
    # + tier in (pro, premium) 유저만 호출할 수 있어야 함. 프론트엔드
    # AppAccessGuard는 라우팅 레벨 방어선이고, 이 훅은 직접 API 호출을
    # 차단하는 두 번째 방어선.
    #
    # 전략: DENYLIST 방식 — 데이터성 prefix만 게이트. auth/admin/stripe/
    # system/scheduler/community 는 각자 이미 데코레이터로 보호 중.
    _GATED_PREFIXES = (
        '/api/kr/',
        '/api/us/',
        '/api/crypto/',
        '/api/wave/',
        '/api/briefing/',
        '/api/stock-analyzer/',
        '/api/econ/',
    )
    # 게이트 내에서도 허용할 정적/공개 엔드포인트 (<img> 태그는 Authorization 헤더 불가)
    _GATE_EXEMPT = set()
    _GATE_EXEMPT_PREFIXES = (
        '/api/kr/ai-chart-image/',
        '/api/us/ai-chart-image/',
    )

    @app.before_request
    def _enforce_pro_access():
        from flask import request as _req, jsonify as _jsonify
        # preflight은 CORS 미들웨어가 처리
        if _req.method == 'OPTIONS':
            return None
        path = _req.path or ''
        if path in _GATE_EXEMPT:
            return None
        if any(path.startswith(p) for p in _GATE_EXEMPT_PREFIXES):
            return None
        if not any(path.startswith(p) for p in _GATED_PREFIXES):
            return None
        # Pro 게이트는 AUTH_DISABLED 와 무관하게 항상 작동 — 구독 경제 핵심 게이트
        from app.auth.decorators import _get_current_user
        user = _get_current_user()
        if user is None:
            return _jsonify({'error': 'Authentication required'}), 401
        if user.is_admin:
            _req.current_user = user
            return None

        # status 가 이미 'expired' 면 즉시 재구독 페이지로 안내
        if user.status == 'expired':
            return _jsonify({
                'error': 'Subscription expired',
                'status': 'expired',
                'expired': True,
                'redirect_to': '/plan-select?resubscribe=1&from=expired',
                'message': 'Pro 구독 만료 — 재구독이 필요합니다.',
            }), 403

        if user.status != 'approved':
            return _jsonify({
                'error': 'Account not approved',
                'status': user.status,
                'redirect_to': '/pending-approval',
            }), 403

        if user.tier not in ('pro', 'premium'):
            return _jsonify({
                'error': 'Pro subscription required',
                'tier': user.tier,
                'redirect_to': '/plan-select',
            }), 403

        # Pro 만료 자동 처리 — DB status 'expired' 로 변경 (계정 정지 효과)
        if user.is_pro_expired:
            try:
                from app.models import db as _db
                user.status = 'expired'
                user.pro_expiry_alert_stage = 'expired'
                _db.session.commit()
            except Exception as _exc:
                _db.session.rollback() if hasattr(_db, 'session') else None
            return _jsonify({
                'error': 'Pro subscription expired',
                'status': 'expired',
                'expired': True,
                'redirect_to': '/plan-select?resubscribe=1&from=expired',
                'message': 'Pro 구독 만료로 계정이 정지되었습니다. 재구독해 주세요.',
            }), 403

        _req.current_user = user
        return None

    # ── Liveness probe (watchdog 전용, 최소 응답시간) ──
    # 외부 의존성 없음. DB/디스크 ping 안 함 → Flask 프로세스 자체가 살아 있는지만 확인.
    # Flask watchdog (scripts/flask_watchdog.ps1) 가 5분 주기로 호출.
    # 응답시간 목표: < 50ms.
    @app.route('/healthz')
    def healthz():
        from flask import jsonify as _jsonify
        return _jsonify({'ok': True}), 200

    # Health check endpoint (자세한 상태 — 운영 진단용)
    @app.route('/api/health')
    def health_check():
        import subprocess
        from flask import jsonify as _jsonify
        try:
            git_hash = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                stderr=subprocess.DEVNULL, timeout=3
            ).decode().strip()
        except Exception:
            git_hash = 'unknown'
        vcp_exists = os.path.exists(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'signals_log.csv'))
        return _jsonify({
            'status': 'ok',
            'service': 'MarketFlow API',
            'version': git_hash,
            'data': {'signals_log': vcp_exists},
        })

    # ── 스케줄러 상태 API ──
    @app.route('/api/scheduler/status')
    def scheduler_status():
        from flask import jsonify as _jsonify
        from app.utils.scheduler import get_scheduler_status
        return _jsonify(get_scheduler_status())

    # ── 스케줄러 수동 트리거 API ──
    from app.auth.decorators import admin_required as _admin_required
    @app.route('/api/scheduler/trigger/<task>', methods=['POST'])
    @_admin_required
    def scheduler_trigger(task):
        from flask import jsonify as _jsonify
        import threading
        from app.utils.scheduler import (
            _run_jongga_v2, _run_round2, _run_us_update, _run_crypto_pipeline,
            _run_all_update
        )

        tasks_map = {
            'jongga-v2': _run_jongga_v2,
            'round2': _run_round2,
            'us-update': _run_us_update,
            'crypto': _run_crypto_pipeline,
            'all-update': _run_all_update,
        }
        func = tasks_map.get(task)
        if not func:
            return _jsonify({'error': f'Unknown task: {task}', 'available': list(tasks_map.keys())}), 400

        # 백그라운드 스레드에서 실행
        threading.Thread(target=func, daemon=True, name=f'trigger-{task}').start()
        return _jsonify({'status': 'triggered', 'task': task})

    # ── 데이터 freshness 확인 (GitHub Actions용) ──
    @app.route('/api/system/last-update')
    def system_last_update():
        from flask import jsonify as _jsonify
        from datetime import datetime, timezone
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        files_to_check = {
            'kr_jongga': os.path.join(base, 'data', 'jongga_v2_latest.json'),
            'us_briefing': os.path.join(base, 'us_market', 'output', 'market_briefing.json'),
            'us_market_data': os.path.join(base, 'us_market', 'output', 'market_data.json'),
            'us_top_picks': os.path.join(base, 'us_market', 'output', 'top_picks.json'),
        }
        result = {}
        for key, path in files_to_check.items():
            if os.path.exists(path):
                mtime = os.path.getmtime(path)
                result[key] = {
                    'timestamp': datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                    'age_seconds': int(datetime.now(timezone.utc).timestamp() - mtime),
                }
            else:
                result[key] = {'timestamp': None, 'age_seconds': -1}
        return _jsonify(result)

    # ── 자가진단 API ──
    @app.route('/api/system/diagnostics')
    def system_diagnostics():
        from flask import jsonify as _jsonify
        from app.utils.diagnostics import get_cached_or_run
        return _jsonify(get_cached_or_run(max_age=120))

    # ── 라우트 등록 검증: 핵심 라우트 누락 시 즉시 중단 ──
    registered = {r.rule for r in app.url_map.iter_rules()}
    for critical in ['/api/health', '/api/data-version']:
        if critical not in registered:
            raise RuntimeError(
                f"[FATAL] Critical route not registered: {critical}\n"
                f"  Registered ({len(registered)}): {sorted(list(registered))[:15]}..."
            )

    # ── Pro 구독 만료 자동 다운그레이드 (1시간 간격) ──
    background_workers_enabled = (
        not app.config.get('TESTING')
        and os.getenv('MARKETFLOW_BACKGROUND_WORKERS', 'true').strip().lower()
        not in {'0', 'false', 'no', 'off'}
    )
    if not background_workers_enabled:
        print("[INFO] Background workers disabled for this app instance")
        return app

    _start_expiry_checker(app)
    _start_aibain_expiry_checker(app)

    # ── 클라우드 스케줄러 자동 시작 (Render 또는 SCHEDULER_ENABLED) ──
    if os.getenv('RENDER'):  # 로컬: scheduler.py --daemon 사용. 이중 스케줄러 방지
        try:
            from app.utils.scheduler import start_cloud_scheduler
            start_cloud_scheduler()
            print("[OK] Cloud scheduler started in background thread")
        except Exception as e:
            print(f"[WARN] Cloud scheduler failed to start: {e}")

    # ── 프리컴퓨팅 스냅샷 워커 (느린 엔드포인트 백그라운드 갱신) ──
    # 누수 진단 또는 응급 시 개별 토글 가능:
    #   WORKER_PRECOMPUTE_ENABLED=0
    #   WORKER_SCREENER_ENABLED=0
    #   WORKER_ALPHA_MONITOR_ENABLED=0
    # 기본은 모두 활성 (운영 호환). 진단 후 원인 격리 시 끔.
    if not os.getenv('RENDER'):
        if os.getenv('WORKER_PRECOMPUTE_ENABLED', '1') != '0':
            _start_precompute_worker(app)
        else:
            print("[OFF] PreCompute worker disabled via WORKER_PRECOMPUTE_ENABLED=0")
        if os.getenv('WORKER_SCREENER_ENABLED', '1') != '0':
            _start_screener_worker(app)
        else:
            print("[OFF] Screener worker disabled via WORKER_SCREENER_ENABLED=0")
        if os.getenv('WORKER_ALPHA_MONITOR_ENABLED', '1') != '0':
            _start_alpha_scanner_monitor_worker(app)
        else:
            print("[OFF] Alpha scanner monitor disabled via WORKER_ALPHA_MONITOR_ENABLED=0")
    else:
        print("[INFO] PreCompute/Screener workers disabled on Render (memory limit)")

    return app


def _start_expiry_checker(app):
    """Pro 구독 만료 자동 다운그레이드 + D-3/D-1/만료일 텔레그램 알림 (1시간 간격)"""
    import threading
    import time

    def _alert(user, stage: str, when: str):
        """관리자 텔레그램에 만료 알림. 본인용 알림은 별도 채널 미구성으로 생략."""
        try:
            bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
            chat_id = os.environ.get('TELEGRAM_CHAT_ID')
            if not bot_token or not chat_id:
                return
            label_map = {'d3': 'D-3 만료 임박', 'd1': 'D-1 만료 임박', 'expired': '만료 처리'}
            msg = (
                f"⏰ <b>Pro 구독 {label_map.get(stage, stage)}</b>\n\n"
                f"👤 {user.name} ({user.email})\n"
                f"📅 만료일: {when}\n"
                f"🆔 user_id={user.id}"
            )
            _telegram_post(bot_token, chat_id, msg, label=f"expiry_{stage}")
        except Exception as e:
            print(f"[Expiry alert] {type(e).__name__}: {e}")

    def _expiry_loop():
        time.sleep(30)  # Flask 초기화 대기
        while True:
            try:
                with app.app_context():
                    from app.models.user import User
                    from app.models import db
                    from datetime import datetime, timezone, timedelta

                    now = datetime.now(timezone.utc)
                    d3_window = now + timedelta(days=3)
                    d1_window = now + timedelta(days=1)

                    # 1) 만료된 유저 처리 — paused 유저 skip (AI Bain 활성 중 일시정지)
                    expired = User.query.filter(
                        User.tier == 'pro',
                        User.pro_expires_at.isnot(None),
                        User.pro_expires_at < now,
                        User.pro_paused_at.is_(None),
                    ).all()
                    for user in expired:
                        when = user.pro_expires_at.isoformat() if user.pro_expires_at else '?'
                        print(f"[Expiry] {user.email}: pro → suspended (expired {user.pro_expires_at})")
                        if user.pro_expiry_alert_stage != 'expired':
                            _alert(user, 'expired', when)
                        user.tier = None
                        user.pro_expires_at = None
                        user.status = 'suspended'
                        user.pro_expiry_alert_stage = 'expired'

                    # 2) D-1 임박 (이미 d1 알림 보낸 유저는 스킵, paused 유저 skip)
                    d1_users = User.query.filter(
                        User.tier == 'pro',
                        User.pro_expires_at.isnot(None),
                        User.pro_expires_at >= now,
                        User.pro_expires_at < d1_window,
                        User.pro_paused_at.is_(None),
                    ).all()
                    for user in d1_users:
                        if user.pro_expiry_alert_stage in ('d1', 'expired'):
                            continue
                        _alert(user, 'd1', user.pro_expires_at.isoformat())
                        user.pro_expiry_alert_stage = 'd1'

                    # 3) D-3 임박 (paused 유저 skip)
                    d3_users = User.query.filter(
                        User.tier == 'pro',
                        User.pro_expires_at.isnot(None),
                        User.pro_expires_at >= d1_window,
                        User.pro_expires_at < d3_window,
                        User.pro_paused_at.is_(None),
                    ).all()
                    for user in d3_users:
                        if user.pro_expiry_alert_stage in ('d3', 'd1', 'expired'):
                            continue
                        _alert(user, 'd3', user.pro_expires_at.isoformat())
                        user.pro_expiry_alert_stage = 'd3'

                    if expired or d1_users or d3_users:
                        db.session.commit()
            except Exception as e:
                print(f"[Expiry] Error: {e}")
            time.sleep(3600)  # 1시간 간격

    thread = threading.Thread(target=_expiry_loop, daemon=True, name='ExpiryChecker')
    thread.start()
    print("[OK] Pro expiry checker started (1h interval, D-3/D-1/expired alerts)")


def _start_aibain_expiry_checker(app):
    """AI Bain 알파 스캐너 만료 자동 비활성화 + D-3/D-1/만료 텔레그램 알림 (1시간 간격).

    Pro 만료와 분리된 차원으로 독립 처리:
    - 베이스 tier 는 그대로 (Pro / Ultra Pro 유지)
    - aibain_enabled=False 처리 + aibain_alert_stage 기록
    - 알림은 운영자 텔레그램 + AdminNotification 인앱
    """
    import threading
    import time

    def _alibain_alert(user, stage: str, when: str):
        try:
            bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
            chat_id = os.environ.get('TELEGRAM_CHAT_ID')
            if not bot_token or not chat_id:
                return
            label_map = {'d3': 'D-3 만료 임박', 'd1': 'D-1 만료 임박', 'expired': '만료 처리'}
            tier_label = 'Ultra Pro' if user.tier == 'premium' else 'Pro' if user.tier == 'pro' else 'No Tier'
            msg = (
                f"🤖 <b>AI Bain {label_map.get(stage, stage)}</b>\n\n"
                f"👤 {user.name} ({user.email})\n"
                f"📋 베이스: {tier_label}\n"
                f"📅 AI Bain 만료일: {when}\n"
                f"🆔 user_id={user.id}"
            )
            _telegram_post(bot_token, chat_id, msg, label=f"aibain_expiry_{stage}")
        except Exception as e:
            print(f"[AIbain expiry alert] {type(e).__name__}: {e}")

    def _aibain_create_admin_notification(user, stage: str):
        """AdminNotification 인앱 알림 — 만료 처리 시점에만."""
        if stage != 'expired':
            return
        try:
            from app.routes.admin import create_admin_notification
            tier_label = 'Ultra Pro' if user.tier == 'premium' else 'Pro' if user.tier == 'pro' else 'No Tier'
            create_admin_notification(
                'aibain_expired',
                f'AI Bain 만료: {user.name}',
                f'{user.email} (베이스 {tier_label}) — AI Bain 자동 비활성화',
                related_id=user.id,
            )
        except Exception as e:
            print(f"[AIbain notification] {type(e).__name__}: {e}")

    def _aibain_loop():
        time.sleep(45)  # Pro expiry checker (30s) 직후 시작
        while True:
            try:
                with app.app_context():
                    from app.models.user import User
                    from app.models import db
                    from datetime import datetime, timezone, timedelta

                    now = datetime.now(timezone.utc)
                    d3_window = now + timedelta(days=3)
                    d1_window = now + timedelta(days=1)

                    # 1) AI Bain 만료된 유저 — 자동 비활성화
                    expired = User.query.filter(
                        User.aibain_enabled == True,
                        User.aibain_expires_at.isnot(None),
                        User.aibain_expires_at < now,
                    ).all()
                    for user in expired:
                        when = user.aibain_expires_at.isoformat() if user.aibain_expires_at else '?'
                        print(f"[AIbain expiry] {user.email}: aibain disabled (expired {user.aibain_expires_at}, base tier {user.tier} 유지)")
                        if user.aibain_alert_stage != 'expired':
                            _alibain_alert(user, 'expired', when)
                            _aibain_create_admin_notification(user, 'expired')
                        user.aibain_enabled = False
                        # aibain_expires_at 은 보존 (이력 추적용)
                        user.aibain_alert_stage = 'expired'
                        # ── Pro 일시정지 재개 ─────────────────────────────────
                        # AI Bain 만료 시점 = Pro 카운터 재개. paused 기간만큼 pro_expires_at 연장.
                        # 정상 시나리오: aibain_expires_at - pro_paused_at = 30일 → Pro 30일 연장.
                        # Pro 회원 only (premium 은 pro_expires_at=NULL 이라 영향 X)
                        if user.pro_paused_at is not None and user.tier == 'pro' and user.pro_expires_at is not None:
                            paused_at = user.pro_paused_at
                            if paused_at.tzinfo is None:
                                paused_at = paused_at.replace(tzinfo=timezone.utc)
                            elapsed = now - paused_at
                            if elapsed.total_seconds() > 0:
                                pro_existing = user.pro_expires_at
                                if pro_existing.tzinfo is None:
                                    pro_existing = pro_existing.replace(tzinfo=timezone.utc)
                                user.pro_expires_at = pro_existing + elapsed
                                print(f"[AIbain expiry] {user.email}: pro_expires_at extended +{elapsed.days}d (paused → resumed)")
                            user.pro_paused_at = None
                            user.pro_expiry_alert_stage = None  # 새 만료일 기준으로 알림 재계산

                    # 2) D-1 임박 (이미 d1 알림 보낸 유저 스킵)
                    d1_users = User.query.filter(
                        User.aibain_enabled == True,
                        User.aibain_expires_at.isnot(None),
                        User.aibain_expires_at >= now,
                        User.aibain_expires_at < d1_window,
                    ).all()
                    for user in d1_users:
                        if user.aibain_alert_stage in ('d1', 'expired'):
                            continue
                        _alibain_alert(user, 'd1', user.aibain_expires_at.isoformat())
                        user.aibain_alert_stage = 'd1'

                    # 3) D-3 임박
                    d3_users = User.query.filter(
                        User.aibain_enabled == True,
                        User.aibain_expires_at.isnot(None),
                        User.aibain_expires_at >= d1_window,
                        User.aibain_expires_at < d3_window,
                    ).all()
                    for user in d3_users:
                        if user.aibain_alert_stage in ('d3', 'd1', 'expired'):
                            continue
                        _alibain_alert(user, 'd3', user.aibain_expires_at.isoformat())
                        user.aibain_alert_stage = 'd3'

                    if expired or d1_users or d3_users:
                        db.session.commit()
            except Exception as e:
                print(f"[AIbain expiry] Error: {e}")
            time.sleep(3600)  # 1시간 간격

    thread = threading.Thread(target=_aibain_loop, daemon=True, name='AibainExpiryChecker')
    thread.start()
    print("[OK] AI Bain expiry checker started (1h interval, D-3/D-1/expired alerts)")


def _start_precompute_worker(app):
    """5분 간격으로 느린 엔드포인트 4개의 스냅샷을 백그라운드에서 프리컴퓨팅.

    대상: portfolio, decision-signal, kr/market-gate, crypto/dominance
    → 각 엔드포인트는 스냅샷 파일이 5분 이내면 즉시 반환 (yfinance 호출 스킵)
    """
    import threading
    import time

    def _precompute_loop():
        time.sleep(10)  # Flask 초기화 완료 대기
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        while True:
            try:
                with app.test_request_context():
                    _precompute_snapshots(base_dir)
            except Exception as e:
                print(f"[PreCompute] Error: {e}")
            time.sleep(300)  # 5분 간격

    thread = threading.Thread(target=_precompute_loop, daemon=True, name='PreComputeWorker')
    thread.start()
    print("[OK] PreCompute worker started (5min interval)")


def _start_screener_worker(app):
    """장중(09:00~15:30) 주도주 스크리너 백그라운드 폴링.

    - 장중: 5초 간격 스캔 → 캐시 항상 최신 유지
    - 장외: 60초 간격 장 시작 대기
    - S등급 발생 시 텔레그램 알림 (5분 쿨다운)
    - 에러 3회 연속 시 30초 휴식 후 재시도
    """
    import threading
    import time as _time

    def _screener_loop():
        _time.sleep(3)  # Flask 최소 대기
        consecutive_errors = 0
        alert_cooldown = {}  # {code: timestamp}
        last_hourly_send = 0  # 1시간 간격 텔레그램 마지막 전송 시각
        first_scan_sent = False  # 첫 스캔 텔레그램 전송 여부

        # 파일 캐시 먼저 로드 (즉시 응답 가능하게)
        try:
            from app.services.kis_screener import load_latest, _result_cache, _result_lock
            latest = load_latest()
            if latest:
                with _result_lock:
                    _result_cache["data"] = latest
                    _result_cache["ts"] = _time.time()
                print(f"[Screener] File cache loaded ({len(latest.get('results', []))} results)")
        except Exception:
            pass

        print("[Screener] Worker ready")

        while True:
            try:
                from app.services.kis_screener import is_market_open, run_screening
                from datetime import datetime as _dt

                if not is_market_open():
                    _time.sleep(60)
                    first_scan_sent = False  # 장 시작 시 리셋
                    last_hourly_send = 0
                    continue

                # 15:30 이후 텔레그램 전송 중단
                now_dt = _dt.now()
                past_cutoff = (now_dt.hour == 15 and now_dt.minute >= 30) or now_dt.hour > 15

                result = run_screening()
                consecutive_errors = 0  # 성공 시 리셋

                # Layer 2 보강 (15분 주기)
                try:
                    from app.services.leading_enricher import should_enrich, enrich_stocks
                    from app.services.kis_screener import _price_details_cache, _price_details_lock
                    if should_enrich() and result and result.get('results'):
                        with _price_details_lock:
                            pd_snapshot = dict(_price_details_cache)
                        enrich_stocks(result['results'], pd_snapshot)
                except Exception as e:
                    print(f"[Enricher] Error: {e}")

                if result and result.get('results') and not past_cutoff:
                    now = _time.time()

                    # S등급 즉시 알림 (5분 쿨다운)
                    for stock in result['results']:
                        if stock.get('grade') != 'S':
                            continue
                        code = stock.get('code', '')
                        if code in alert_cooldown and (now - alert_cooldown[code]) < 300:
                            continue
                        alert_cooldown[code] = now
                        try:
                            _send_screener_alert(stock, result)
                        except Exception:
                            pass

                    # 1시간 간격 전체 요약 텔레그램 (첫 스캔 포함)
                    should_send_hourly = (not first_scan_sent) or (now - last_hourly_send >= 3600)
                    if should_send_hourly:
                        try:
                            _send_screener_hourly_summary(result)
                            last_hourly_send = now
                            first_scan_sent = True
                        except Exception as e:
                            print(f"[Screener] Hourly summary error: {e}")

                _time.sleep(5)  # 장중 5초 간격

            except Exception as e:
                consecutive_errors += 1
                print(f"[Screener] Error #{consecutive_errors}: {e}")
                if consecutive_errors >= 3:
                    print("[Screener] 3회 연속 에러 — 30초 휴식")
                    _time.sleep(30)
                    consecutive_errors = 0
                else:
                    _time.sleep(5)

    thread = threading.Thread(target=_screener_loop, daemon=True, name='ScreenerWorker')
    thread.start()
    print("[OK] Screener worker started (5s polling during market hours)")


def _start_alpha_scanner_monitor_worker(app):
    """Watch alpha-scanner source artifacts and Telegram new candidates."""
    import threading
    import time as _time

    def _env_bool(name: str, default: str = 'true') -> bool:
        return os.environ.get(name, default).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}

    if not _env_bool('ALPHA_SCANNER_ENABLED', 'true'):
        print("[AlphaScanner] realtime monitor skipped: ALPHA_SCANNER_ENABLED=false")
        return
    if not _env_bool('ALPHA_SCANNER_REALTIME_ENABLED', 'true'):
        print("[AlphaScanner] realtime monitor skipped: ALPHA_SCANNER_REALTIME_ENABLED=false")
        return

    interval = max(5, int(os.environ.get('ALPHA_SCANNER_REALTIME_INTERVAL', '30')))
    initial_delay = max(1, int(os.environ.get('ALPHA_SCANNER_REALTIME_INITIAL_DELAY', '12')))
    retry_seconds = max(30, int(os.environ.get('ALPHA_SCANNER_ALERT_RETRY_SECONDS', '300')))

    def _alpha_scanner_monitor_loop():
        _time.sleep(initial_delay)
        consecutive_errors = 0
        print(f"[AlphaScanner] realtime monitor ready ({interval}s polling)")

        while True:
            try:
                if not _env_bool('ALPHA_SCANNER_REALTIME_ENABLED', 'true'):
                    _time.sleep(interval)
                    continue

                from app.services.mirofish.alpha_scanner import run_scanner_realtime_monitor_check
                from app.utils.scheduler import _send_telegram_long

                limit = int(os.environ.get('ALPHA_SCANNER_LIMIT', '20'))
                min_alpha = float(os.environ.get('ALPHA_SCANNER_MIN_ALPHA', '70'))
                max_risk = float(os.environ.get('ALPHA_SCANNER_MAX_RISK', '45'))
                max_events = int(os.environ.get('ALPHA_SCANNER_MAX_EVENTS', '8'))

                with app.app_context():
                    result = run_scanner_realtime_monitor_check(
                        {'limit': limit},
                        min_alpha=min_alpha,
                        max_risk=max_risk,
                        max_events=max_events,
                        retry_seconds=retry_seconds,
                        send_fn=lambda message: _send_telegram_long(message, channel=False),
                    )

                consecutive_errors = 0
                status = result.get('status')
                if status in {'sent', 'send_failed', 'no_new_events'}:
                    print(
                        "[AlphaScanner] monitor "
                        f"status={status} events={result.get('new_event_count', 0)} "
                        f"run={(result.get('run') or {}).get('id')}"
                    )
            except Exception as e:
                consecutive_errors += 1
                print(f"[AlphaScanner] monitor error #{consecutive_errors}: {type(e).__name__}: {e}")
                if consecutive_errors >= 3:
                    _time.sleep(60)
                    consecutive_errors = 0

            _time.sleep(interval)

    thread = threading.Thread(
        target=_alpha_scanner_monitor_loop,
        daemon=True,
        name='AlphaScannerMonitor',
    )
    thread.start()
    print("[OK] Alpha scanner realtime monitor started")

    # MCP Stage 2 자동 실행기 (event-driven state machine)
    try:
        from app.services.mirofish import auto_runner as _auto_runner
        if _auto_runner.start_worker():
            print("[OK] MCP auto-runner started (event-driven Stage 2 automation)")
        else:
            print("[OFF] MCP auto-runner disabled via MIROFISH_AUTO_RUNNER_ENABLED=false")
    except Exception as _exc:
        print(f"[WARN] MCP auto-runner failed to start: {type(_exc).__name__}: {_exc}")


def _telegram_html(value) -> str:
    import html
    return html.escape(str(value or ""), quote=False)


def _format_screener_timestamp(result) -> str:
    from datetime import datetime as _dt

    raw_ts = (result or {}).get('timestamp')
    if not raw_ts:
        return _dt.now().strftime('%m/%d %H:%M:%S')
    try:
        stamp = _dt.fromisoformat(str(raw_ts).replace('Z', '+00:00'))
        return stamp.strftime('%m/%d %H:%M:%S')
    except Exception:
        return str(raw_ts)


def _quote_mode_label(result=None) -> str:
    mode = str((result or {}).get('quote_mode') or '').lower()
    if not mode:
        mode = 'paper' if os.environ.get('KIS_PAPER', 'true').lower() in {'1', 'true', 'yes', 'on'} else 'real'
    return 'KIS 실전' if mode == 'real' else 'KIS 모의'


def _quote_mode_warning(result=None) -> str:
    return (
        "\n⚠️ 모의투자 시세 기준입니다. 실전 HTS/증권사 현재가와 차이가 날 수 있습니다."
        if _quote_mode_label(result) == 'KIS 모의' else ""
    )


def _screener_source_label(result=None) -> str:
    status = (result or {}).get('market_status') or 'unknown'
    served_from = (result or {}).get('served_from')
    if served_from:
        return f"{status} · {served_from}"
    return status


def _build_screener_alert_message(stock, result=None):
    score = stock.get('score', {})
    enrich = stock.get('enrichment', {})
    ai_reason = enrich.get('ai_reason', '')
    themes = enrich.get('themes', [])
    consecutive = enrich.get('consecutive_days', 0)
    cap_tier = enrich.get('market_cap_tier', '')
    total_score = score.get('total_enriched')
    if total_score is None:
        total_score = score.get('total', 0)

    msg = (
        f"<b>🔥 주도주 S등급 발견</b>\n\n"
        f"<b>{_telegram_html(stock.get('name'))}</b> ({_telegram_html(stock.get('code'))})\n"
        f"기준: {_format_screener_timestamp(result)} · {_quote_mode_label(result)} · {_screener_source_label(result)}"
        f"{_quote_mode_warning(result)}\n"
        f"현재가: {stock.get('price', 0):,}원 ({stock.get('change_pct', 0):+.1f}%)\n"
        f"거래대금: {stock.get('trading_value_eok', 0):,}억\n"
        f"점수: {total_score}/100 "
        f"(거래{score.get('trading_value', 0)} 모멘{score.get('momentum', 0)} "
        f"수급{score.get('smart_money', 0)} 급증{score.get('volume_surge', 0)} "
        f"섹터{score.get('sector', 0)} 신고{score.get('new_high', 0)})"
        + (f"\n👑 52주 신고가 근접 ({stock.get('high_52w', {}).get('distance_pct', 0)}%)"
           if score.get('new_high', 0) >= 10 else "")
        + (f"\n🤖 AI: {_telegram_html(ai_reason)}" if ai_reason else "")
        + (f"\n🏷️ {' '.join(f'#{_telegram_html(t)}' for t in themes)}" if themes else "")
        + (f"\n🔥 {consecutive}일 연속 주도주!" if consecutive >= 2 else "")
        + (f"\n📊 {_telegram_html(cap_tier)}주" if cap_tier and cap_tier != "미분류" else "")
    )
    return msg


def _send_screener_alert(stock, result=None):
    """S등급 주도주 텔레그램 알림"""
    try:
        import requests
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        if not bot_token or not chat_id:
            return
        msg = _build_screener_alert_message(stock, result)
        _telegram_post(bot_token, chat_id, msg, label="screener_alert_main")
        # 채널에도 전송
        ch_token = os.environ.get('TELEGRAM_CHANNEL_BOT_TOKEN')
        ch_id = os.environ.get('TELEGRAM_CHANNEL_CHAT_ID')
        if ch_token and ch_id:
            _telegram_post(ch_token, ch_id, msg, label="screener_alert_channel")
    except Exception as e:
        _tg_logger().warning(f"_send_screener_alert failed: {type(e).__name__}: {e}")


def _tg_logger():
    import logging as _logging
    return _logging.getLogger("marketflow.telegram")


def _telegram_post(bot_token: str, chat_id: str, msg: str, *, label: str) -> bool:
    """Centralized telegram send with explicit logging on failure.

    Returns True on HTTP 200 success. Any exception or non-200 is logged
    with label + truncated body so silent failures are visible in logs.
    """
    import requests
    logger = _tg_logger()
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=5,
        )
        if resp.status_code == 200:
            logger.info(f"telegram[{label}] ok chat={chat_id}")
            return True
        logger.warning(
            f"telegram[{label}] HTTP {resp.status_code} chat={chat_id} body={resp.text[:200]}"
        )
        return False
    except Exception as e:
        logger.warning(f"telegram[{label}] exception chat={chat_id}: {type(e).__name__}: {e}")
        return False


def _send_screener_hourly_summary(result):
    """주도주LIVE 1시간 간격 전체 종목 요약 텔레그램"""
    try:
        import requests
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        if not bot_token or not chat_id:
            return

        msg = _build_screener_hourly_message(result)
        _telegram_post(bot_token, chat_id, msg, label="screener_hourly_main")
        # 채널에도 전송
        ch_token = os.environ.get('TELEGRAM_CHANNEL_BOT_TOKEN')
        ch_id = os.environ.get('TELEGRAM_CHANNEL_CHAT_ID')
        if ch_token and ch_id:
            _telegram_post(ch_token, ch_id, msg, label="screener_hourly_channel")
    except Exception as e:
        _tg_logger().warning(f"_send_screener_hourly_summary failed: {type(e).__name__}: {e}")


def _build_screener_hourly_message(result):
    stocks = result.get('results', [])
    by_grade = result.get('by_grade', {})
    now_str = _format_screener_timestamp(result)

    lines = [
        f"<b>📊 주도주LIVE 현황 ({now_str})</b>",
        f"시세: {_quote_mode_label(result)} · {_screener_source_label(result)}",
        f"S:{by_grade.get('S', 0)} A:{by_grade.get('A', 0)} B:{by_grade.get('B', 0)} | 총 {len(stocks)}종목",
    ]
    warning = _quote_mode_warning(result).strip()
    if warning:
        lines.append(warning)
    lines.append("")

    for stock in stocks:
        grade = stock.get('grade', '')
        if grade not in ('S', 'A'):
            continue
        score = stock.get('score', {})
        enrich = stock.get('enrichment', {})
        ai_reason = enrich.get('ai_reason', '')
        consecutive = enrich.get('consecutive_days', 0)
        cap_tier = enrich.get('market_cap_tier', '')
        total_score = score.get('total_enriched')
        if total_score is None:
            total_score = score.get('total', 0)
        line = (
            f"{'🔥' if grade == 'S' else '🟡'} <b>{_telegram_html(stock.get('name'))}</b> "
            f"{stock.get('price', 0):,}원 "
            f"{stock.get('change_pct', 0):+.1f}% "
            f"({total_score}점) "
            f"{stock.get('trading_value_eok', 0):,}억"
        )
        extras = []
        if ai_reason:
            extras.append(f"💡{_telegram_html(ai_reason)}")
        if consecutive >= 2:
            extras.append(f"🔥{consecutive}연속")
        if cap_tier and cap_tier != "미분류":
            extras.append(_telegram_html(cap_tier))
        if extras:
            line += f"\n   └ {' · '.join(extras)}"
        lines.append(line)

    b_stocks = [s.get('name', '') for s in stocks if s.get('grade') == 'B']
    if b_stocks:
        names = [_telegram_html(name) for name in b_stocks[:5]]
        lines.append(f"\nB등급: {', '.join(names)}{'...' if len(b_stocks) > 5 else ''}")

    try:
        import json as _json
        theme_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  'data', 'kiwoom_ai_theme_latest.json')
        if os.path.exists(theme_path):
            with open(theme_path, 'r', encoding='utf-8') as f:
                theme_data = _json.load(f)
            theme_stocks = theme_data.get('stocks', [])
            if theme_stocks and not theme_data.get('preview_mode'):
                lines.append("")
                lines.append(f"<b>🤖 AI전략 테마 TOP</b> ({theme_data.get('executed', 0)}/{theme_data.get('total_conditions', 7)}개 조건식)")
                for ts in theme_stocks[:5]:
                    hit = ts.get('hit_count', 0)
                    total = theme_data.get('total_conditions', 7)
                    lines.append(
                        f"  [{hit}/{total}] <b>{_telegram_html(ts.get('name'))}</b> "
                        f"{ts.get('change_pct', 0):+.1f}%"
                    )
    except Exception as e:
        _tg_logger().debug(f"AI theme block skipped: {e}")

    return '\n'.join(lines)


def _precompute_snapshots(base_dir):
    """느린 엔드포인트 스냅샷 갱신"""
    import time
    import json

    tasks = [
        ('US Portfolio', _precompute_portfolio, base_dir),
        ('US Market Gate', _precompute_us_market_gate, base_dir),
        ('US Decision Signal', _precompute_decision_signal, base_dir),
        ('US Smart Money', _precompute_smart_money, base_dir),
        ('US Cumulative Perf', _precompute_cumulative_perf, base_dir),
        ('KR Market Gate', _precompute_kr_market_gate, base_dir),
        ('Crypto Dominance', _precompute_crypto_dominance, base_dir),
    ]

    for name, func, bd in tasks:
        try:
            start = time.time()
            func(bd)
            elapsed = time.time() - start
            print(f"[PreCompute] {name}: OK ({elapsed:.1f}s)")
        except Exception as e:
            print(f"[PreCompute] {name}: FAIL ({e})")


def _precompute_portfolio(base_dir):
    """US Portfolio 스냅샷 프리컴퓨팅"""
    from app.routes.us_market import _fetch_portfolio_live
    _fetch_portfolio_live()  # 내부에서 스냅샷 파일 저장


def _precompute_decision_signal(base_dir):
    """US Decision Signal 스냅샷 프리컴퓨팅"""
    from app.routes.us_market import _compute_decision_signal_live
    _compute_decision_signal_live()  # 내부에서 스냅샷 파일 저장


def _precompute_us_market_gate(base_dir):
    """US Market Gate 스냅샷 프리컴퓨팅"""
    from app.routes.us_market import _get_us_market_gate_payload
    _get_us_market_gate_payload(force=True)  # 내부에서 스냅샷 파일 저장


def _precompute_kr_market_gate(base_dir):
    """KR Market Gate 스냅샷 프리컴퓨팅"""
    from app.routes.kr_market import _compute_kr_market_gate_live
    _compute_kr_market_gate_live()  # 내부에서 스냅샷 파일 저장


def _precompute_smart_money(base_dir):
    """US Smart Money 스냅샷 프리컴퓨팅"""
    from app.routes.us_market import _compute_smart_money_live
    _compute_smart_money_live()  # 내부에서 스냅샷 파일 저장


def _precompute_cumulative_perf(base_dir):
    """US Cumulative Performance 스냅샷 프리컴퓨팅"""
    from app.routes.us_market import _compute_cumulative_performance_live
    _compute_cumulative_performance_live()  # 내부에서 스냅샷 파일 저장


def _precompute_crypto_dominance(base_dir):
    """Crypto Dominance 스냅샷 프리컴퓨팅"""
    from app.routes.crypto import _compute_crypto_dominance_live
    _compute_crypto_dominance_live()  # 내부에서 스냅샷 파일 저장
