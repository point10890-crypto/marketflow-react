"""
AI Briefing Blueprint — /api/briefing/*
조간/마감 AI 브리핑 조회 API
"""
import os
import json
import time
import re
from flask import Blueprint, jsonify

briefing_bp = Blueprint('briefing', __name__)

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIEFING_DIR = os.path.join(_BASE, 'data', 'briefing')

# TTL cache (60s — briefings change at most twice daily)
_cache: dict = {}
_CACHE_TTL = 60


def _load(filename: str) -> dict | None:
    now = time.time()
    if filename in _cache:
        data, ts = _cache[filename]
        if now - ts < _CACHE_TTL:
            return data

    fpath = os.path.join(_BRIEFING_DIR, filename)
    if not os.path.exists(fpath):
        return None
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _cache[filename] = (data, now)
        return data
    except Exception:
        return None


def _find_latest_of_type(briefing_type: str) -> dict | None:
    """Find the most recent briefing of given type"""
    if not os.path.isdir(_BRIEFING_DIR):
        return None

    files = sorted(
        [f for f in os.listdir(_BRIEFING_DIR) if f.startswith(f'{briefing_type}_') and f.endswith('.json')],
        reverse=True
    )
    for f in files:
        data = _load(f)
        if data:
            return data
    return None


@briefing_bp.route('/latest')
def get_latest():
    """Most recent briefing (morning or closing)"""
    data = _load('latest.json')
    if data:
        return jsonify(data)
    return jsonify({'error': 'No briefing available'}), 404


@briefing_bp.route('/morning')
@briefing_bp.route('/morning/<date>')
def get_morning(date=None):
    """Morning briefing — today or by date (YYYYMMDD)"""
    if date:
        if not re.match(r'^\d{8}$', date):
            return jsonify({'error': 'Invalid date format, use YYYYMMDD'}), 400
        data = _load(f'morning_{date}.json')
    else:
        data = _find_latest_of_type('morning')

    if data:
        return jsonify(data)
    return jsonify({'error': 'Morning briefing not found'}), 404


@briefing_bp.route('/closing')
@briefing_bp.route('/closing/<date>')
def get_closing(date=None):
    """Closing briefing — today or by date (YYYYMMDD)"""
    if date:
        if not re.match(r'^\d{8}$', date):
            return jsonify({'error': 'Invalid date format, use YYYYMMDD'}), 400
        data = _load(f'closing_{date}.json')
    else:
        data = _find_latest_of_type('closing')

    if data:
        return jsonify(data)
    return jsonify({'error': 'Closing briefing not found'}), 404


@briefing_bp.route('/dates')
def get_dates():
    """List available briefing dates"""
    if not os.path.isdir(_BRIEFING_DIR):
        return jsonify({'dates': []})

    dates_map: dict = {}
    for f in os.listdir(_BRIEFING_DIR):
        if f == 'latest.json':
            continue
        match = re.match(r'^(morning|closing)_(\d{8})\.json$', f)
        if match:
            btype, date = match.groups()
            if date not in dates_map:
                dates_map[date] = []
            dates_map[date].append(btype)

    dates = sorted(
        [{'date': d, 'types': sorted(t)} for d, t in dates_map.items()],
        key=lambda x: x['date'],
        reverse=True
    )
    return jsonify({'dates': dates})
