# app/routes/common.py
"""공통 API 라우트 (Crypto 전용)"""

import os
import json
import sys
import subprocess
from datetime import datetime
from flask import Blueprint, jsonify, request, Response, stream_with_context

common_bp = Blueprint('common', __name__)


@common_bp.route('/health')
def health_check():
    """헬스 체크"""
    return jsonify({'status': 'ok', 'service': 'CryptoAnalytics'})


@common_bp.route('/system/data-status')
def get_data_status():
    """데이터 파일 상태 조회 (Crypto 전용)"""

    data_files_to_check = [
        {
            'name': 'VCP Signals DB',
            'path': os.path.join('crypto_market', 'signals.sqlite3'),
            'link': '/dashboard/crypto/signals',
            'menu': 'Signals'
        },
        {
            'name': 'Market Gate',
            'path': os.path.join('crypto_market', 'output', 'market_gate.json'),
            'link': '/dashboard/crypto',
            'menu': 'Overview'
        },
        {
            'name': 'Crypto Briefing',
            'path': os.path.join('crypto_market', 'output', 'crypto_briefing.json'),
            'link': '/dashboard/crypto/briefing',
            'menu': 'Briefing'
        },
        {
            'name': 'BTC Prediction',
            'path': os.path.join('crypto_market', 'output', 'btc_prediction.json'),
            'link': '/dashboard/crypto/prediction',
            'menu': 'Prediction'
        },
        {
            'name': 'Risk Analysis',
            'path': os.path.join('crypto_market', 'output', 'crypto_risk.json'),
            'link': '/dashboard/crypto/risk',
            'menu': 'Risk'
        },
        {
            'name': 'Lead-Lag Results',
            'path': os.path.join('crypto_market', 'lead_lag', 'results.json'),
            'link': '/dashboard/crypto',
            'menu': 'Overview'
        },
        {
            'name': 'Timeline Events',
            'path': os.path.join('crypto_market', 'timeline_events.json'),
            'link': '/dashboard/crypto',
            'menu': 'Overview'
        },
    ]

    files_status = []

    for file_info in data_files_to_check:
        path = file_info['path']
        exists = os.path.exists(path)

        if exists:
            stat = os.stat(path)
            size_bytes = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime)

            if size_bytes > 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            elif size_bytes > 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes} B"

            row_count = None
            if path.endswith('.json'):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        row_count = len(data)
                    elif isinstance(data, dict):
                        for key in ['signals', 'events', 'lead_lag', 'history']:
                            if key in data and isinstance(data[key], list):
                                row_count = len(data[key])
                                break
                except Exception:
                    pass

            files_status.append({
                'name': file_info['name'],
                'path': path,
                'exists': True,
                'lastModified': mtime.isoformat(),
                'size': size_str,
                'rowCount': row_count,
                'link': file_info.get('link', ''),
                'menu': file_info.get('menu', '')
            })
        else:
            files_status.append({
                'name': file_info['name'],
                'path': path,
                'exists': False,
                'lastModified': '',
                'size': '-',
                'rowCount': None,
                'link': file_info.get('link', ''),
                'menu': file_info.get('menu', '')
            })

    return jsonify({
        'files': files_status,
        'update_status': {
            'isRunning': False,
            'lastRun': '',
            'progress': ''
        }
    })


@common_bp.route('/system/update-single')
def update_single_data():
    """개별 데이터 업데이트 (SSE 스트리밍)"""
    data_type = request.args.get('type', '')

    update_commands = {
        'vcp_signals': {
            'name': 'VCP Signals',
            'script': os.path.join('crypto_market', 'run_scan.py'),
            'args': []
        },
        'market_gate': {
            'name': 'Market Gate',
            'script': os.path.join('crypto_market', 'market_gate.py'),
            'args': []
        },
        'briefing': {
            'name': 'Crypto Briefing',
            'script': os.path.join('crypto_market', 'crypto_briefing.py'),
            'args': []
        },
        'prediction': {
            'name': 'BTC Prediction',
            'script': os.path.join('crypto_market', 'crypto_prediction.py'),
            'args': []
        },
        'risk': {
            'name': 'Risk Analysis',
            'script': os.path.join('crypto_market', 'crypto_risk.py'),
            'args': []
        },
        'lead_lag': {
            'name': 'Lead-Lag Analysis',
            'script': os.path.join('crypto_market', 'run_lead_lag.py'),
            'args': []
        },
    }

    if data_type not in update_commands:
        return jsonify({
            'error': f'Unknown data type: {data_type}',
            'available_types': list(update_commands.keys())
        }), 400

    config = update_commands[data_type]

    def generate():
        yield f"data: [SYSTEM] Starting {config['name']} update...\n\n"

        try:
            script_path = config['script']
            if not os.path.exists(script_path):
                yield f"data: [ERROR] Script not found: {script_path}\n\n"
                yield "event: end\ndata: close\n\n"
                return

            cmd = [sys.executable, '-u', script_path] + config.get('args', [])

            env = os.environ.copy()
            env['PYTHONPATH'] = os.getcwd()
            env['PYTHONUNBUFFERED'] = '1'

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                env=env,
                bufsize=1
            )

            buffer = ""
            last_progress_line = ""

            while True:
                char = process.stdout.read(1)
                if not char:
                    break

                if char == '\n':
                    clean_line = buffer.strip()
                    if clean_line:
                        yield f"data: {clean_line}\n\n"
                    buffer = ""
                elif char == '\r':
                    clean_line = buffer.strip()
                    if clean_line and clean_line != last_progress_line:
                        yield f"data: {clean_line}\n\n"
                        last_progress_line = clean_line
                    buffer = ""
                else:
                    buffer += char

            if buffer.strip():
                yield f"data: {buffer.strip()}\n\n"

            process.wait()

            if process.returncode == 0:
                yield f"data: [SYSTEM] {config['name']} update completed successfully.\n\n"
            else:
                yield f"data: [SYSTEM] {config['name']} update failed (exit code: {process.returncode})\n\n"

        except Exception as e:
            yield f"data: [ERROR] Failed: {str(e)}\n\n"

        yield "event: end\ndata: close\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@common_bp.route('/system/update-data-stream')
def stream_update_data():
    """전체 데이터 업데이트 (Crypto orchestrator)"""
    def generate():
        yield "data: [SYSTEM] Starting crypto data update...\n\n"

        try:
            script_path = 'orchestrator.py'
            if not os.path.exists(script_path):
                yield f"data: [ERROR] Script not found at {script_path}\n\n"
                yield "event: end\ndata: close\n\n"
                return

            cmd = [sys.executable, '-u', script_path]

            env = os.environ.copy()
            env['PYTHONPATH'] = os.getcwd()

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                env=env,
                bufsize=1
            )

            for line in process.stdout:
                clean_line = line.strip()
                if clean_line:
                    yield f"data: {clean_line}\n\n"

            process.wait()

            if process.returncode == 0:
                yield "data: [SYSTEM] Update completed successfully.\n\n"
            else:
                yield "data: [SYSTEM] Update failed. Check logs.\n\n"

        except Exception as e:
            yield f"data: [ERROR] Failed to start process: {str(e)}\n\n"

        yield "event: end\ndata: close\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')
