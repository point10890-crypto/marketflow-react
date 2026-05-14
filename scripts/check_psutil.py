"""psutil 설치 여부 + 운영 프로세스 RSS 확인."""
import sys, os
try:
    import psutil
    print(f'psutil OK: version={psutil.__version__}')
    p = psutil.Process(os.getpid())
    print(f'this process RSS_MB={round(p.memory_info().rss / 1024 / 1024, 1)}')
except ImportError as e:
    print(f'psutil MISSING: {e}')
    sys.exit(1)

# Flask process 찾기
flask_pid = None
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if proc.info['name'] == 'python.exe':
            cmdline = ' '.join(proc.info.get('cmdline') or [])
            if 'flask_app.py' in cmdline:
                flask_pid = proc.info['pid']
                break
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        continue

if flask_pid:
    fp = psutil.Process(flask_pid)
    print(f'flask_app pid={flask_pid} RSS_MB={round(fp.memory_info().rss / 1024 / 1024, 1)}')
else:
    print('flask_app process NOT FOUND in psutil iter')
