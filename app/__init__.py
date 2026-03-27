# app/__init__.py
"""Flask 애플리케이션 팩토리 (KR Market + Auth + Stripe)"""

import os
import sys
from flask import Flask, make_response
from flask.json.provider import DefaultJSONProvider

# 패키지 루트 경로 추가 + OneDrive/외부 경로 오염 방지
_app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_blocked = ['kr_market_package', 'OneDrive', '바탕 화면', 'desktop',
            'closing_bet', 'us-market-pro', 'korean market']
sys.path = [p for p in sys.path if not any(b.lower() in p.lower() for b in _blocked)]
sys.path.insert(0, _app_root)


class SafeJSONProvider(DefaultJSONProvider):
    """NaN/Infinity → null 변환 (JSON 표준 준수)"""
    def dumps(self, obj, **kwargs):
        kwargs.setdefault("default", self.default)
        raw = super().dumps(obj, **kwargs)
        return raw.replace("NaN", "null").replace("Infinity", "null").replace("-Infinity", "null")


def create_app(config=None):
    """Flask 앱 팩토리 함수"""
    app = Flask(__name__)
    app.json_provider_class = SafeJSONProvider
    app.json = SafeJSONProvider(app)

    # CORS 설정 (옵셔널)
    try:
        from flask_cors import CORS
        CORS(app, resources={r"/api/*": {"origins": "*"}})
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
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 설정 적용
    if config:
        app.config.update(config)

    # Database
    from app.models import db
    db.init_app(app)
    with app.app_context():
        from app.models.user import User  # noqa: F401
        from app.models.wave import WaveSignal, WaveTracking, WavePatternStats  # noqa: F401
        db.create_all()

    # Blueprint 등록
    from app.routes import register_blueprints
    register_blueprints(app)

    # ── API Cache-Control 정책 ──
    @app.after_request
    def add_cache_headers(response):
        """JSON API: 기본 30초 브라우저 캐시 허용, 실시간 엔드포인트는 개별 no-cache 설정"""
        if response.content_type and 'application/json' in response.content_type:
            # 엔드포인트별 no-cache는 개별 라우트에서 설정 (portfolio, market-gate 등)
            if not response.headers.get('Cache-Control'):
                response.headers['Cache-Control'] = 'public, max-age=30'
        return response

    # Health check endpoint
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
    @app.route('/api/scheduler/trigger/<task>', methods=['POST'])
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
            'us_briefing': os.path.join(base, 'us_market', 'output', 'briefing.json'),
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

    # ── 클라우드 스케줄러 자동 시작 (Render 또는 SCHEDULER_ENABLED) ──
    if os.getenv('RENDER'):  # 로컬: scheduler.py --daemon 사용. 이중 스케줄러 방지
        try:
            from app.utils.scheduler import start_cloud_scheduler
            start_cloud_scheduler()
            print("[OK] Cloud scheduler started in background thread")
        except Exception as e:
            print(f"[WARN] Cloud scheduler failed to start: {e}")

    # ── 프리컴퓨팅 스냅샷 워커 (느린 엔드포인트 백그라운드 갱신) ──
    if not os.getenv('RENDER'):
        _start_precompute_worker(app)
        _start_screener_worker(app)
    else:
        print("[INFO] PreCompute/Screener workers disabled on Render (memory limit)")

    return app


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
                            _send_screener_alert(stock)
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


def _send_screener_alert(stock):
    """S등급 주도주 텔레그램 알림"""
    try:
        import requests
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        if not bot_token or not chat_id:
            return
        score = stock.get('score', {})
        enrich = stock.get('enrichment', {})
        ai_reason = enrich.get('ai_reason', '')
        themes = enrich.get('themes', [])
        consecutive = enrich.get('consecutive_days', 0)
        cap_tier = enrich.get('market_cap_tier', '')

        msg = (
            f"<b>🔥 주도주 S등급 발견</b>\n\n"
            f"<b>{stock.get('name')}</b> ({stock.get('code')})\n"
            f"현재가: {stock.get('price', 0):,}원 ({stock.get('change_pct', 0):+.1f}%)\n"
            f"거래대금: {stock.get('trading_value_eok', 0):,}억\n"
            f"점수: {score.get('total', 0)}/100 "
            f"(거래{score.get('trading_value', 0)} 모멘{score.get('momentum', 0)} "
            f"수급{score.get('smart_money', 0)} 급증{score.get('volume_surge', 0)} "
            f"섹터{score.get('sector', 0)} 신고{score.get('new_high', 0)})"
            + (f"\n👑 52주 신고가 근접 ({stock.get('high_52w', {}).get('distance_pct', 0)}%)"
               if score.get('new_high', 0) >= 10 else "")
            + (f"\n🤖 AI: {ai_reason}" if ai_reason else "")
            + (f"\n🏷️ {' '.join(f'#{t}' for t in themes)}" if themes else "")
            + (f"\n🔥 {consecutive}일 연속 주도주!" if consecutive >= 2 else "")
            + (f"\n📊 {cap_tier}주" if cap_tier and cap_tier != "미분류" else "")
        )
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception:
        pass


def _send_screener_hourly_summary(result):
    """주도주LIVE 1시간 간격 전체 종목 요약 텔레그램"""
    try:
        import requests
        from datetime import datetime as _dt
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        if not bot_token or not chat_id:
            return

        stocks = result.get('results', [])
        by_grade = result.get('by_grade', {})
        now_str = _dt.now().strftime('%H:%M')

        # 헤더
        lines = [
            f"<b>📊 주도주LIVE 현황 ({now_str})</b>",
            f"S:{by_grade.get('S', 0)} A:{by_grade.get('A', 0)} B:{by_grade.get('B', 0)} | 총 {len(stocks)}종목",
            "",
        ]

        # S/A등급 종목 리스트
        for stock in stocks:
            grade = stock.get('grade', '')
            if grade not in ('S', 'A'):
                continue
            score = stock.get('score', {})
            enrich = stock.get('enrichment', {})
            ai_reason = enrich.get('ai_reason', '')
            consecutive = enrich.get('consecutive_days', 0)
            cap_tier = enrich.get('market_cap_tier', '')
            line = (
                f"{'🔥' if grade == 'S' else '🟡'} <b>{stock.get('name')}</b> "
                f"{stock.get('change_pct', 0):+.1f}% "
                f"({score.get('total', 0)}점) "
                f"{stock.get('trading_value_eok', 0):,}억"
            )
            extras = []
            if ai_reason:
                extras.append(f"💡{ai_reason}")
            if consecutive >= 2:
                extras.append(f"🔥{consecutive}연속")
            if cap_tier and cap_tier != "미분류":
                extras.append(cap_tier)
            if extras:
                line += f"\n   └ {' · '.join(extras)}"
            lines.append(line)

        # B등급은 종목명만
        b_stocks = [s.get('name', '') for s in stocks if s.get('grade') == 'B']
        if b_stocks:
            lines.append(f"\nB등급: {', '.join(b_stocks[:5])}{'...' if len(b_stocks) > 5 else ''}")

        msg = '\n'.join(lines)
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=5
        )
    except Exception:
        pass


def _precompute_snapshots(base_dir):
    """느린 엔드포인트 스냅샷 갱신"""
    import time
    import json

    tasks = [
        ('US Portfolio', _precompute_portfolio, base_dir),
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
