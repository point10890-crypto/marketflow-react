"""Flask app import + create 검증 — 시작 실패 원인 진단용."""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    print('Importing flask_app...')
    import flask_app
    print(f'flask_app imported OK, app={type(flask_app.app).__name__}')
    print(f'routes: {sum(1 for _ in flask_app.app.url_map.iter_rules())}')
    # tracemalloc 상태 확인
    import tracemalloc
    print(f'tracemalloc.is_tracing: {tracemalloc.is_tracing()}')
    # psutil 확인
    try:
        import psutil
        p = psutil.Process(os.getpid())
        print(f'psutil OK, this RSS_MB={round(p.memory_info().rss / 1024 / 1024, 1)}')
    except Exception as e:
        print(f'psutil FAIL: {e}')
    print('OK')
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
