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
                'C:\\Projects', 'OneDrive']
    sys.path = [p for p in sys.path if not any(b.lower() in p.lower() for b in _blocked)]

# ── Path setup (all platforms) ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Ensure output directories exist (cloud: ephemeral filesystem)
for d in ['data', 'logs', 'us_market_preview/output', 'us_market/output']:
    os.makedirs(os.path.join(BASE_DIR, d), exist_ok=True)

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

    app.run(host='0.0.0.0', port=port, debug=False)
