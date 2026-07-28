#!/usr/bin/env python3
"""
Flask application entry point
Supports both local (Windows) and cloud (Render.com) deployment.
Gunicorn uses: flask_app:app
"""
import sys
import os

# ── Platform-specific setup ──
if sys.platform.startswith('win'):
    import shutil
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

    # Fix SSL cert path for Korean directory names (Windows only)
    try:
        import certifi
        cert_src = certifi.where()
        safe_cert = os.path.join(os.path.expanduser('~'), 'cacert.pem')
        if not os.path.exists(safe_cert) or os.path.getmtime(cert_src) > os.path.getmtime(safe_cert):
            shutil.copy2(cert_src, safe_cert)
        os.environ['CURL_CA_BUNDLE'] = safe_cert
        os.environ['SSL_CERT_FILE'] = safe_cert
    except Exception:
        pass

    # Windows sys.path pollution prevention
    _blocked = ['korean market', 'crypto-analytics', 'us-market-pro', 'kr_market_package',
                'Projects', 'OneDrive']
    sys.path = [p for p in sys.path if not any(b.lower() in p.lower() for b in _blocked)]

# ── Path setup (all platforms) ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Ensure output directories exist (cloud: ephemeral filesystem)
for d in ['data', 'logs', 'us_market/output']:
    os.makedirs(os.path.join(BASE_DIR, d), exist_ok=True)

# ── 메모리 누수 진단 모드 (운영 진단용, 평소 OFF) ──
# GRAPHRAG_TRACEMALLOC=1 으로 시작하면 tracemalloc 활성화. RSS 누수 발생 시
# /api/admin/mirofish/_debug/memory?tracemalloc=1 로 top allocations 확인 가능.
# .env 파일이 create_app() 안에서 load_dotenv 되므로 그 전에 .env 를 직접 읽어
# GRAPHRAG_TRACEMALLOC 환경변수를 적용한다.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.join(BASE_DIR, '.env'), override=False)
except ImportError:
    pass

if os.getenv('GRAPHRAG_TRACEMALLOC', '0') == '1':
    import tracemalloc
    tracemalloc.start(25)  # 25 frame deep — 충분히 호출자 traceback 확보
    print('[DEBUG] tracemalloc enabled (25 frames)')

from app import create_app

# Create the Flask app (gunicorn imports this as flask_app:app)
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('FLASK_PORT', os.environ.get('PORT', 5001)))
    print(f"\n{'='*60}")
    print(f"[START] Flask App (port {port})")
    print(f"   BASE_DIR: {BASE_DIR}")
    print(f"   Platform: {sys.platform}")
    print(f"   Cloud: {'Render' if os.getenv('RENDER') else 'Local'}")
    print(f"{'='*60}\n")

    # Cloud(Render) / 홈서버(HOME_SERVER): 0.0.0.0 / 개발PC: 127.0.0.1
    host = os.getenv('FLASK_HOST') or (
        '0.0.0.0' if os.getenv('RENDER') or os.getenv('HOME_SERVER') else '127.0.0.1'
    )
    app.run(host=host, port=port, debug=False)
