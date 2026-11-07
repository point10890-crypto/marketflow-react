"""Read-only, explicitly authorized bridge to the local Kongming catalyst view."""

import http.client
import json
import math
from contextlib import closing

from flask import jsonify, request

from app.services import kongming_article_candidates


_MAX_BODY_BYTES = 8 * 1024 * 1024
_SOCKET_TIMEOUT_SECONDS = 4
_NO_STORE = 'private, no-store, no-cache, must-revalidate, max-age=0'
_ERROR_COUNTS = object()
_CLAIM_AMOUNT = (str, int, float)

_SETUP = {'label': str, 'complete': bool, 'failed': [str], 'missing': [str]}
_STYLE = {
    'state': str, 'technical_pass': bool, 'qualified': bool, 'eligible': bool,
    'currently_eligible': bool, 'blockers': [str],
    'quote': {'observed_at': str, 'received_at': str, 'plan': {'valid_until': str}},
}
_VALIDATION_FIELDS = {
    'computed_at': str, 'hash': str, 'history_count': int,
    'current_eligible_count': int, 'current_eligible_symbol_count': int,
    'quote_expiry_seconds': int,
    'live': {
        'last_run_at': str, 'last_change_at': str, 'age_seconds': int,
        'stalled': bool, 'worker_interval_seconds': int,
    },
    'operation': {
        'state': str, 'market_open': bool, 'task_count': int, 'price_probed': int,
        'task_errors': _ERROR_COUNTS, 'watch_error': str, 'error_type': str,
    },
    'swing_watch': {
        'source_as_of': str, 'population': int, 'baseline_count': int,
        'baseline_rows': [{
            'symbol': str, 'name': str, 'common_pass': bool,
            'failed_common': [str], 'missing_common': [str],
        }],
        'common_watch_count': int,
        'watch_rows': [{
            'symbol': str, 'name': str,
            'setups': {'contraction': _SETUP, 'breakout': _SETUP, 'pullback': _SETUP},
        }],
        'common_funnel': [{'label': str, 'count': int}],
    },
    'items': [{
        'task_id': str, 'symbol': str, 'name': str, 'article_title': str, 'article_url': str,
        'article_published_at': str, 'first_seen_at': str, 'checked_at': str,
        'primary': {
            'status': str,
            'checks': [{
                'status': str, 'url': str, 'filing': {'report_nm': str},
                'claims': [{
                    'metric': str, 'article_amount_krw': _CLAIM_AMOUNT,
                    'official_amount_krw': _CLAIM_AMOUNT, 'verified': bool,
                }],
            }],
        },
        'styles': {'scalp': _STYLE, 'swing': _STYLE, 'close': _STYLE},
    }],
}
_HISTORY_FIELDS = {
    'items': [{
        'id': str, 'checked_at': str, 'name': str, 'symbol': str,
        'primary': {'status': str}, 'market_state': str, 'buy_eligible': bool,
    }],
}


def _project(value, fields):
    """Keep only UI fields, preserving source types and nullable observations."""
    if value is None:
        return None
    if fields is _ERROR_COUNTS:
        if not isinstance(value, dict) or any(
            not name.isidentifier() or len(name) > 128 or type(count) is not int or count < 0
            for name, count in value.items()
        ):
            raise ValueError('Invalid catalyst error counts')
        return value
    if isinstance(fields, dict):
        if not isinstance(value, dict):
            raise ValueError('Invalid catalyst object')
        return {key: _project(value[key], spec) for key, spec in fields.items() if key in value}
    if isinstance(fields, list):
        if not isinstance(value, list) or any(item is None for item in value):
            raise ValueError('Invalid catalyst list')
        return [_project(item, fields[0]) for item in value]
    accepted = fields if isinstance(fields, tuple) else (fields,)
    if type(value) not in accepted or (type(value) is float and not math.isfinite(value)):
        raise ValueError('Invalid catalyst value')
    return value


def _read(path):
    with closing(http.client.HTTPConnection('127.0.0.1', 8768, timeout=_SOCKET_TIMEOUT_SECONDS)) as connection:
        connection.request('GET', path, headers={'Accept': 'application/json'})
        upstream = connection.getresponse()
        if upstream.status != 200 or upstream.getheader('Content-Type', '').partition(';')[0].strip().lower() != 'application/json':
            raise ValueError('Unexpected catalyst response')
        body = upstream.read(_MAX_BODY_BYTES + 1)
        if len(body) > _MAX_BODY_BYTES:
            raise ValueError('Oversized catalyst response')
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
        raise ValueError('Invalid catalyst payload')
    return payload


def _response(payload, status):
    response = jsonify(payload)
    response.status_code = status
    response.headers['Cache-Control'] = _NO_STORE
    return response


def catalyst_response(*, history=False):
    """Allow authenticated administrators and active bundle subscribers."""
    user = request.current_user
    if not (user.is_admin or getattr(user, 'is_kongming_active', False)):
        return _response({'error': 'kongming_catalyst_forbidden'}, 403)
    try:
        if history:
            payload = _project(_read('/api/catalyst-validation-history'), _HISTORY_FIELDS)
        else:
            payload = _project(_read('/api/catalyst-validation'), _VALIDATION_FIELDS)
    except (OSError, http.client.HTTPException, ValueError, RecursionError):
        return _response({'error': 'kongming_catalyst_unavailable'}, 502)
    return _response(payload, 200)


def article_candidates_response():
    """Read only MarketFlow's own article snapshot using the bundle entitlement."""
    user = request.current_user
    if not (user.is_admin or getattr(user, 'is_kongming_active', False)):
        return _response({'error': 'kongming_catalyst_forbidden'}, 403)
    try:
        payload = kongming_article_candidates.read_view()
    except (OSError, ValueError, KeyError, TypeError):
        return _response({'error': 'kongming_article_candidates_unavailable'}, 503)
    return _response(payload, 200)
