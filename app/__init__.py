# app/__init__.py
"""Flask 애플리케이션 팩토리 (KR Market + Auth + Stripe)"""

import hashlib
import os
import logging
import secrets
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

    # 응답 압축 (옵셔널) — 스크리너/Wave JSON 은 0.9~2.2MB 이며 gzip 시 8~10배 축소.
    # after_request 는 등록 역순으로 실행되므로 여기(캐시/ETag 훅보다 먼저)에 등록해야
    # ETag 가 원본 본문 기준으로 계산된 뒤 압축이 적용된다.
    if os.getenv('MARKETFLOW_COMPRESS', '1') != '0':
        try:
            from flask_compress import Compress
            app.config.setdefault('COMPRESS_MIMETYPES', [
                'application/json', 'text/html', 'text/css', 'text/plain',
                'application/javascript',
            ])
            app.config.setdefault('COMPRESS_MIN_SIZE', 1024)
            Compress(app)
        except ImportError:
            logging.getLogger(__name__).info('flask-compress not installed, response compression disabled')

    # 환경변수 로드
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # 기본 설정
    configured_secret = os.getenv('SECRET_KEY', '').strip()
    if configured_secret:
        app.config['SECRET_KEY'] = configured_secret
    else:
        # Never fall back to a repository-known signing key.  A known key lets
        # anyone mint a valid Bearer token for an arbitrary user id.  The
        # process-local key keeps an accidentally misconfigured instance safe;
        # production must still configure SECRET_KEY so tokens survive restarts.
        app.config['SECRET_KEY'] = secrets.token_urlsafe(48)
        logging.getLogger(__name__).critical(
            'SECRET_KEY is not configured; using a process-local random key. '
            'Existing auth tokens will be invalid after restart.'
        )
    # 부팅 시 런타임 설정 검증 — 문제마다 WARNING(값은 로그하지 않음),
    # MARKETFLOW_STRICT_CONFIG=1 이면 기동을 중단한다 (config.validate_runtime_config).
    _config_log = logging.getLogger(__name__)
    try:
        from config import RuntimeConfigError, validate_runtime_config
        _config_problems = validate_runtime_config(strict=False)
    except ImportError:  # pragma: no cover — 루트 config.py 가 sys.path 에 없는 임베딩 환경
        RuntimeConfigError = RuntimeError
        _config_problems = []
    for _problem in _config_problems:
        _config_log.warning('[config] %s', _problem)
    if _config_problems and os.getenv('MARKETFLOW_STRICT_CONFIG', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        raise RuntimeConfigError('MARKETFLOW_STRICT_CONFIG=1: ' + '; '.join(_config_problems))

    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(
        os.path.abspath(os.path.dirname(os.path.dirname(__file__))), 'data', 'users.db'
    ).replace('\\', '/')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 110 * 1024 * 1024
    app.config['MAX_FORM_MEMORY_SIZE'] = 1024 * 1024
    app.config['MAX_JSON_CONTENT_LENGTH'] = 1024 * 1024

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
        from app.models.funnel import FunnelEvent  # noqa: F401
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
                # AI Brain add-on columns are required by User.to_dict(),
                # access guards, expiry checker, and admin approval workflow.
                # Keep this startup migration idempotent so restored MiniPC DBs
                # do not need manual one-off scripts before the app can boot.
                if 'aibain_enabled' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN aibain_enabled BOOLEAN NOT NULL DEFAULT 0'))
                if 'aibain_expires_at' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN aibain_expires_at DATETIME'))
                if 'aibain_alert_stage' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN aibain_alert_stage VARCHAR(10)'))
                if 'pro_paused_at' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN pro_paused_at DATETIME'))
                # 비밀번호 변경 시각 — 이전 발급 토큰 무효화 근거 (2026-08-11)
                if 'password_changed_at' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN password_changed_at DATETIME'))
                # 회원 본인 텔레그램 알림 연결 (2026-09-03) — 승인/만료 안내를 본인에게 발송
                if 'telegram_chat_id' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR(64)'))
                    conn.execute(text('CREATE INDEX IF NOT EXISTS ix_users_telegram_chat_id ON users (telegram_chat_id)'))
                if 'telegram_link_code' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN telegram_link_code VARCHAR(32)'))
                if 'telegram_link_code_expires_at' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN telegram_link_code_expires_at DATETIME'))
                if 'telegram_linked_at' not in user_cols:
                    conn.execute(text('ALTER TABLE users ADD COLUMN telegram_linked_at DATETIME'))
        except Exception:
            pass  # table may not exist yet (create_all handles it)

        # Existing SQLite databases are not altered by db.create_all(), so the
        # model's partial unique index must also be installed explicitly.  It
        # protects the check-then-insert purchase route across processes while
        # preserving rejected re-purchase and historical approved rows.
        if db.engine.dialect.name == 'sqlite':
            from sqlalchemy import text as sql_text

            with db.engine.begin() as conn:
                pending_duplicate_groups = conn.execute(sql_text('''
                    SELECT COUNT(*)
                    FROM (
                        SELECT post_id, user_id
                        FROM purchase_requests
                        WHERE status = 'pending'
                        GROUP BY post_id, user_id
                        HAVING COUNT(*) > 1
                    ) AS duplicate_groups
                ''')).scalar_one()
                if pending_duplicate_groups:
                    # 레거시 중복 pending 행은 데이터를 건드리지 않고(삭제·수정 금지)
                    # 인덱스 설치만 건너뛴다 — 커뮤니티 인덱스 하나 때문에 전체 API
                    # 부팅이 거부되면 안 된다. 운영자가 수동 정리 후 재기동하면 설치된다.
                    logging.getLogger(__name__).error(
                        'Pending purchase uniqueness index NOT installed: '
                        '%s duplicate (post_id, user_id) pending group(s) exist in '
                        'purchase_requests. Resolve them manually (keep one row per '
                        'group), then restart to install '
                        'uq_purchase_requests_pending_post_user.',
                        pending_duplicate_groups,
                    )
                else:
                    conn.execute(sql_text('''
                        CREATE UNIQUE INDEX IF NOT EXISTS
                            uq_purchase_requests_pending_post_user
                        ON purchase_requests(post_id, user_id)
                        WHERE status = 'pending'
                    '''))

    # Blueprint 등록
    from app.routes import register_blueprints
    register_blueprints(app)

    @app.before_request
    def reject_oversized_json():
        """Reject oversized JSON before Flask materializes it in memory."""
        content_length = request.content_length
        max_json = int(app.config.get('MAX_JSON_CONTENT_LENGTH', 1024 * 1024))
        if request.is_json and content_length is not None and content_length > max_json:
            return make_response({'error': 'JSON request body too large'}, 413)
        return None

    # ── API Cache-Control 정책 ──
    # 리뷰(2026-09-02): 구독자 요청은 전부 Authorization/Cookie 를 싣기 때문에
    # 기존 `has_credentials → no-store` 분기가 모든 데이터 GET 을 무캐시로 만들었고
    # `private, max-age=30` 분기는 사실상 죽은 코드였다. 브라우저 전용(private)
    # 캐시는 사용자 간 혼합이 없으므로 인증 여부와 무관하게 안전하다.
    # 민감 prefix(admin/auth/community/stripe)·비GET·오류 응답만 no-store 로 남긴다.
    _NO_STORE_PREFIXES = (
        '/api/admin/',
        '/api/auth/',
        '/api/community/',
        '/api/stripe/',
    )
    _ETAG_MAX_BYTES = 4 * 1024 * 1024

    @app.after_request
    def add_cache_headers(response):
        """JSON API: 기본 30초 브라우저(private) 캐시 + ETag/304, 민감 경로는 no-store.

        - /api/admin/*, /api/auth/*, /api/community/*, /api/stripe/*: 즉시 반영 필요 → no-store
        - 라우트가 직접 Cache-Control 을 지정한 경우 그대로 존중 (실시간 엔드포인트의 no-store 등)
        - 그 외 GET 200 JSON: `private, max-age=30` + 본문 해시 ETag. 폴링 페이지(5s/30s)가
          If-None-Match 를 보내면 본문 없이 304 로 응답해 대역폭·직렬화 비용을 줄인다.
        """
        if response.content_type and 'application/json' in response.content_type:
            path = (request.path or '')
            if (
                request.method != 'GET'
                or response.status_code >= 400
                or path.startswith(_NO_STORE_PREFIXES)
            ):
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                response.headers['Pragma'] = 'no-cache'
            elif not response.headers.get('Cache-Control'):
                # API responses may become user-specific as access rules evolve.
                # Browser-private caching preserves the short TTL optimization
                # without allowing Cloudflare/shared proxies to mix users.
                response.headers['Cache-Control'] = 'private, max-age=30'

            cache_control = response.headers.get('Cache-Control', '')
            if (
                request.method == 'GET'
                and response.status_code == 200
                and 'no-store' not in cache_control
                and not response.direct_passthrough
                and not response.headers.get('ETag')
            ):
                try:
                    body = response.get_data()
                    if body and len(body) <= _ETAG_MAX_BYTES:
                        response.set_etag(hashlib.sha1(body).hexdigest(), weak=True)
                        response.make_conditional(request)
                except Exception:  # noqa: BLE001 — ETag 는 최적화일 뿐, 응답을 막지 않는다
                    pass

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
    # 내부 스케줄 구성(작업 목록/실행 시각)이 그대로 노출되므로 관리자 전용.
    from app.auth.decorators import admin_required as _status_admin_required

    @app.route('/api/scheduler/status')
    @_status_admin_required
    def scheduler_status():
        from flask import jsonify as _jsonify
        from app.utils.scheduler import get_scheduler_status
        return _jsonify(get_scheduler_status())

    # ── 스케줄러 수동 트리거 API ──
    # C2(2026-09-03): 데몬이 기록한 data/scheduler_jobs.json 의 잡 키를 검증하고
    # data/scheduler_trigger_requests.json 큐에 넣는다 → 데몬(scheduler.py)이 30초 내 소비.
    # 잡 파일이 없으면(데몬 미기동/구버전) 기존 Flask 내부 5개 태스크 맵으로 폴백 — 회귀 없음.
    from app.auth.decorators import admin_required as _admin_required
    @app.route('/api/scheduler/trigger/<job_key>', methods=['POST'])
    @_admin_required
    def scheduler_trigger(job_key):
        from flask import jsonify as _jsonify, request as _request
        import threading
        from app.utils.scheduler import read_daemon_jobs, enqueue_trigger_request

        daemon_keys = [j['key'] for j in read_daemon_jobs()]
        if daemon_keys:
            if job_key not in daemon_keys:
                return _jsonify({'error': f'Unknown job_key: {job_key}', 'available': daemon_keys}), 400
            user = getattr(_request, 'current_user', None)
            try:
                req = enqueue_trigger_request(job_key, requested_by=getattr(user, 'email', None))
            except Exception as e:  # noqa: BLE001 — 큐 파일 잠금/디스크 오류
                return _jsonify({'error': f'enqueue failed: {e}', 'job_key': job_key}), 500
            return _jsonify({'status': 'queued', 'id': req['id'], 'job_key': job_key})

        # 폴백: 기존 5개 Flask 내부 태스크
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
        func = tasks_map.get(job_key)
        if not func:
            return _jsonify({'error': f'Unknown task: {job_key}', 'available': list(tasks_map.keys())}), 400

        # 백그라운드 스레드에서 실행
        threading.Thread(target=func, daemon=True, name=f'trigger-{job_key}').start()
        return _jsonify({'status': 'triggered', 'task': job_key})

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
    # 내부 호스트/포트/경로와 에러 상세가 포함되므로 관리자 전용 (info disclosure).
    @app.route('/api/system/diagnostics')
    @_status_admin_required
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

    # ── Pro / AI Brain 구독 만료 유지보수 (1시간 간격) ──
    background_workers_enabled = (
        not app.config.get('TESTING')
        and os.getenv('MARKETFLOW_BACKGROUND_WORKERS', 'true').strip().lower()
        not in {'0', 'false', 'no', 'off'}
    )
    expiry_workers_raw = os.getenv('MARKETFLOW_EXPIRY_WORKERS_ENABLED')
    expiry_workers_enabled = (
        not app.config.get('TESTING')
        and (
            background_workers_enabled
            if expiry_workers_raw is None
            else expiry_workers_raw.strip().lower() not in {'0', 'false', 'no', 'off'}
        )
    )
    if expiry_workers_enabled:
        _start_expiry_checker(app)
        _start_aibain_expiry_checker(app)
        # 회원 텔레그램 연결 폴러 — 만료 알림과 같은 게이트로 on/off (봇 토큰 없으면 자체 skip)
        _start_member_telegram_link_worker(app)
    else:
        print("[INFO] Subscription expiry workers disabled for this app instance")

    # ── manual-stock-analysis 스크래퍼 루프 (프로세스당 1회 명시적 기동) ──
    # 상태 GET 폴링이 스크랩을 암묵 실행하는 것은 계속 금지(MANUAL_STOCK_ANALYSIS_AUTO_LOOP=0).
    # 대신 여기서 명시적으로 한 번만 띄운다. 이 트리거가 없으면 루프를 시작하는 주체가
    # 아무도 없어 대시보드가 마지막 회차에서 그대로 멈춘다(2026-07-15 사고).
    # 기본 off — MANUAL_STOCK_ANALYSIS_LOOP_AUTOSTART=true 인 호스트에서만 동작.
    if not app.config.get('TESTING'):
        try:
            from app.services import manual_stock_analysis as _manual_scraper
            if _manual_scraper.start_scraper_loop_on_boot():
                print("[OK] Manual stock analysis scraper loop scheduled at boot")
        except Exception as e:
            print(f"[WARN] Manual scraper boot autostart failed: {e}")

    # ── GraphRAG 엔티티 DB 부트스트랩 (초성/별칭/퍼지 검색의 전제) ──
    # entities.db 가 없으면 decision_brief._graphrag_matches 가 조용히 [] 를 돌려
    # 리졸버 코드가 죽은 코드가 된다. 부팅을 막지 않도록 데몬 스레드에서 1회 보장.
    # GRAPHRAG_BOOTSTRAP_ENABLED=0 으로 끌 수 있다 (기본 on, TESTING 에서는 off).
    if not app.config.get('TESTING'):
        if os.getenv('GRAPHRAG_BOOTSTRAP_ENABLED', '1').strip().lower() not in {'0', 'false', 'no', 'off'}:
            try:
                from app.services.mirofish.graphrag.bootstrap import start_background_bootstrap
                start_background_bootstrap()
                print("[OK] GraphRAG entities.db bootstrap scheduled (background)")
            except Exception as e:
                print(f"[WARN] GraphRAG entities bootstrap failed to start: {e}")
        else:
            print("[OFF] GraphRAG entities bootstrap disabled via GRAPHRAG_BOOTSTRAP_ENABLED=0")

    if not background_workers_enabled:
        print("[INFO] Background workers disabled for this app instance")
        return app

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
            from app.services.pro_expiry import build_expiry_alert_message
            msg = build_expiry_alert_message(
                name=user.name, email=user.email, user_id=user.id,
                stage=stage, when=when,
            )
            _telegram_post(bot_token, chat_id, msg, label=f"expiry_{stage}")
        except Exception as e:
            print(f"[Expiry alert] {type(e).__name__}: {e}")

    def _expiry_loop():
        time.sleep(30)  # Flask 초기화 대기
        while True:
            try:
                with app.app_context():
                    # 만료는 status='expired' (tier 보존, 재구독 유도) — 'suspended' 는
                    # 관리자 수동 정지 전용이다. 로직·테스트는 services/pro_expiry.py.
                    from app.services.pro_expiry import run_expiry_sweep
                    run_expiry_sweep(notify=_alert)
            except Exception as e:
                print(f"[Expiry] Error: {e}")
            time.sleep(3600)  # 1시간 간격

    thread = threading.Thread(target=_expiry_loop, daemon=True, name='ExpiryChecker')
    thread.start()
    print("[OK] Pro expiry checker started (1h interval, D-3/D-1/expired alerts)")


def _apply_aibain_expiry_state(user, now):
    """AI Brain 만료 상태를 적용하고 Pro 베이스 카운터를 재개한다.

    반환값은 Pro 카운터가 일시정지됐던 기간(timedelta)이며, 베이스 tier/status와
    AI Brain 만료 이력(aibain_expires_at)은 변경하지 않는다.
    """
    from datetime import timezone

    user.aibain_enabled = False
    user.aibain_alert_stage = 'expired'

    if user.pro_paused_at is None:
        return None

    elapsed = None
    if user.tier == 'pro' and user.pro_expires_at is not None:
        paused_at = user.pro_paused_at
        if paused_at.tzinfo is None:
            paused_at = paused_at.replace(tzinfo=timezone.utc)
        normalized_now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        candidate_elapsed = normalized_now - paused_at
        if candidate_elapsed.total_seconds() > 0:
            pro_existing = user.pro_expires_at
            if pro_existing.tzinfo is None:
                pro_existing = pro_existing.replace(tzinfo=timezone.utc)
            user.pro_expires_at = pro_existing + candidate_elapsed
            elapsed = candidate_elapsed

    # Pro는 새 만료일로 카운터 재개. Ultra Pro/비정상 레거시 marker도 안전하게 정리.
    user.pro_paused_at = None
    user.pro_expiry_alert_stage = None
    return elapsed


def _start_member_telegram_link_worker(app):
    """회원 텔레그램 연결 폴러 (60초 간격) — /start <code> 를 읽어 User.telegram_chat_id 에 매칭.

    MEMBER_TELEGRAM_LINK_ENABLED=0 이거나 봇 토큰(TELEGRAM_MEMBER_BOT_TOKEN →
    TELEGRAM_BOT_TOKEN 폴백)이 없으면 시작하지 않는다. 폴러 내부 예외는 로그만.
    """
    import threading
    import time

    try:
        from app.services import member_telegram
    except Exception as e:
        print(f"[WARN] Member telegram service import failed: {e}")
        return
    if not member_telegram.link_enabled():
        print("[INFO] Member telegram link poller disabled (no bot token or MEMBER_TELEGRAM_LINK_ENABLED=0)")
        return

    def _loop():
        time.sleep(20)  # Flask 초기화 대기
        while True:
            try:
                with app.app_context():
                    result = member_telegram.poll_link_updates()
                    if result.get('linked'):
                        print(f"[MemberTelegram] linked={result['linked']} updates={result['updates']}")
            except Exception as e:
                print(f"[MemberTelegram] poll error: {type(e).__name__}: {e}")
            time.sleep(60)

    thread = threading.Thread(target=_loop, daemon=True, name='MemberTelegramLink')
    thread.start()
    print("[OK] Member telegram link poller started (60s interval)")


def _start_aibain_expiry_checker(app):
    """AI Brain 알파 스캐너 만료 자동 비활성화 + D-3/D-1/만료 텔레그램 알림 (1시간 간격).

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
                f"🤖 <b>AI Brain {label_map.get(stage, stage)}</b>\n\n"
                f"👤 {user.name} ({user.email})\n"
                f"📋 베이스: {tier_label}\n"
                f"📅 AI Brain 만료일: {when}\n"
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
                f'AI Brain 만료: {user.name}',
                f'{user.email} (베이스 {tier_label}) — AI Brain 자동 비활성화',
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

                    # 1) AI Brain 만료된 유저 — 자동 비활성화
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
                        # aibain_expires_at 은 이력 추적을 위해 보존한다.
                        elapsed = _apply_aibain_expiry_state(user, now)
                        if elapsed is not None:
                            print(f"[AIbain expiry] {user.email}: pro_expires_at extended +{elapsed.days}d (paused → resumed)")

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
    print("[OK] AI Brain expiry checker started (1h interval, D-3/D-1/expired alerts)")


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


def _screener_poll_interval_seconds():
    """Return a quota-safe start-to-start interval for the canonical poller."""
    raw = os.getenv('KIS_SCREENER_POLL_INTERVAL_SECONDS', '30')
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 30.0
    # A complete scan currently needs roughly 10-15 seconds and consumes more
    # than 50 physical KIS requests.  A five-second loop therefore ran scans
    # continuously and left no account-wide quota headroom for Scheduler/Claw.
    return max(15.0, min(value, 300.0))


def _screener_result_is_safe(result):
    """Only an explicitly complete scan may feed alerts or reset backoff."""
    if not isinstance(result, dict) or result.get('error') or result.get('poller_busy'):
        return False
    quality = result.get('data_quality')
    return isinstance(quality, dict) and quality.get('safe_to_replace_latest') is True


def _screener_stock_is_immediate_s(stock):
    """Gate immediate alerts on the synchronous KIS score.

    The display grade may include asynchronous AI/consecutive enrichment. On
    worker restart that cache warms after the first scan, so using it here can
    turn cache availability into a false S-grade market alert.
    """
    if not isinstance(stock, dict):
        return False
    score = stock.get('score')
    if isinstance(score, dict) and score.get('total') is not None:
        try:
            return float(score.get('total')) >= 80
        except (TypeError, ValueError):
            return False
    return stock.get('grade') == 'S'


def _start_screener_worker(app):
    """장중(09:00~15:30) 주도주 스크리너 백그라운드 폴링.

    - 장중: 기본 30초 start-to-start (KIS 계정 호출량 여유 확보)
    - 장외: 60초 간격 장 시작 대기
    - S등급 발생 시 텔레그램 알림 (5분 쿨다운)
    - 에러 3회 연속 시 30초 휴식 후 재시도
    """
    import threading
    import time as _time

    def _screener_loop():
        _time.sleep(3)  # Flask 최소 대기
        poll_interval = _screener_poll_interval_seconds()
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
                    # Keep this only as a poller-busy fallback. Treating an old
                    # disk artifact as a freshly scanned in-memory result can
                    # emit stale opening alerts and defer the first live scan.
                    _result_cache["ts"] = 0
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

                scan_started = _time.monotonic()
                result = run_screening()
                if result.get('poller_busy'):
                    # Another process owns the complete scan window. Do not
                    # re-alert from its fallback; retry on the next loop.
                    _time.sleep(min(5.0, poll_interval))
                    continue
                if not _screener_result_is_safe(result):
                    consecutive_errors += 1
                    quality = result.get('data_quality') if isinstance(result, dict) else {}
                    print(
                        "[Screener] Unsafe scan rejected "
                        f"#{consecutive_errors}: error={result.get('error') if isinstance(result, dict) else 'invalid_result'} "
                        f"missing={list((quality or {}).get('missing_sources') or [])}"
                    )
                    # Failed scans must not become a tight retry loop.  The
                    # capped exponential delay also gives KIS quota windows and
                    # transient connections time to recover.
                    _time.sleep(min(120.0, poll_interval * (2 ** min(consecutive_errors - 1, 2))))
                    continue
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
                        if not _screener_stock_is_immediate_s(stock):
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

                # Keep a quota-safe start-to-start cadence. A complete KIS scan
                # can take longer than the target; never compensate by bursting.
                scan_elapsed = _time.monotonic() - scan_started
                _time.sleep(max(1.0, poll_interval - scan_elapsed))

            except Exception as e:
                consecutive_errors += 1
                print(f"[Screener] Error #{consecutive_errors}: {e}")
                if consecutive_errors >= 3:
                    print("[Screener] 3회 연속 에러 — 30초 휴식")
                    _time.sleep(30)
                    consecutive_errors = 0
                else:
                    _time.sleep(min(5.0, poll_interval))

    thread = threading.Thread(target=_screener_loop, daemon=True, name='ScreenerWorker')
    thread.start()
    print(
        "[OK] Screener worker started "
        f"({int(_screener_poll_interval_seconds())}s polling during market hours)"
    )


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
                send_fn = None
                if _env_bool('ALPHA_SCANNER_TELEGRAM_ENABLED', 'false'):
                    from app.utils.scheduler import _send_telegram_long

                    send_fn = lambda message: _send_telegram_long(message, channel=False)

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
                        send_fn=send_fn,
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
