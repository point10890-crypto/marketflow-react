"""Entitlement-gated reads of MarketFlow's stored article and verification data."""

import math
import re
import sqlite3

from flask import jsonify, request

from app.services import kongming_article_candidates, kongming_verification


_NO_STORE = 'private, no-store, no-cache, must-revalidate, max-age=0'
_AMOUNT = (str, int, float)
_NUMBER = (int, float)
_PRICE_FIELDS = {
    'status': str, 'reason': str, 'refresh_status': str, 'source': str, 'market': str,
    'reference_at': str, 'observed_at': str, 'fetched_at': str, 'session': str,
    'calendar_source': str, 'calendar_captured_at': str,
    'window_end_at': str, 'window_complete': bool, 'close': _NUMBER,
    'latest_close': _NUMBER, 'latest_observed_at': str, 'change_pct': _NUMBER,
}
_VALIDATION_FIELDS = {
    'source': str, 'computed_at': str, 'history_count': int,
    'live': {
        'last_run_at': str, 'last_change_at': str, 'age_seconds': int,
        'stalled': bool, 'worker_interval_seconds': int,
    },
    'operation': {
        'state': str, 'task_count': int, 'pending_count': int,
        'disclosure_checked': int, 'price_checked': int, 'source_error_count': int,
    },
    'items': [{
        'task_id': str, 'article_id': str, 'symbol': str, 'name': str,
        'article_title': str, 'article_url': str, 'article_published_at': str,
        'first_seen_at': str, 'first_seen_source': str, 'checked_at': str,
        'primary': {
            'status': str, 'source': str, 'checked_at': str, 'error_code': str, 'reason': str, 'refresh_status': str,
            'query_start': str, 'query_end': str,
            'checks': [{
                'status': str, 'url': str, 'filing_date_relation': str,
                'filing': {'report_nm': str, 'rcept_no': str, 'rcept_dt': str, 'corp_name': str},
                'claims': [{
                    'metric': str, 'article_amount_krw': _AMOUNT,
                    'official_amount_krw': _AMOUNT, 'verified': bool, 'period': str, 'basis': str,
                }],
            }],
        },
        'price': _PRICE_FIELDS,
    }],
}
_HISTORY_FIELDS = {
    'source': str,
    'items': [{
        'id': str, 'article_id': str, 'article_title': str, 'checked_at': str, 'name': str, 'symbol': str,
        'primary': {'status': str}, 'price': {'status': str},
    }],
}


def _project(value, fields):
    """Keep only UI fields, preserving source types and nullable observations."""
    if value is None:
        return None
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


def _response(payload, status):
    response = jsonify(payload)
    response.status_code = status
    response.headers['Cache-Control'] = _NO_STORE
    return response


def _allowed():
    user = request.current_user
    return user.is_admin or getattr(user, 'is_kongming_active', False)


def catalyst_response(*, history=False):
    """Serve saved verification evidence without calling providers."""
    if not _allowed():
        return _response({'error': 'kongming_catalyst_forbidden'}, 403)
    article_id = request.args.get('article_id')
    if article_id is not None and not re.fullmatch(r'[1-9][0-9]{0,9}', article_id):
        return _response({'error': 'invalid_article_id'}, 400)
    try:
        read = kongming_verification.read_history if history else kongming_verification.read_dashboard
        raw = read(article_id=article_id)
        if not isinstance(raw, dict) or not isinstance(raw.get('items'), list):
            raise ValueError('Invalid saved verification payload')
        payload = _project(raw, _HISTORY_FIELDS if history else _VALIDATION_FIELDS)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, RecursionError):
        return _response({'error': 'kongming_catalyst_unavailable'}, 503)
    return _response(payload, 200)


def article_candidates_response():
    """Read only MarketFlow's own article snapshot using the bundle entitlement."""
    if not _allowed():
        return _response({'error': 'kongming_catalyst_forbidden'}, 403)
    try:
        payload = kongming_article_candidates.read_view()
    except (OSError, ValueError, KeyError, TypeError):
        return _response({'error': 'kongming_article_candidates_unavailable'}, 503)
    return _response(payload, 200)


_SURGE_FIELDS = {
    'schema_version': int, 'status': str, 'generated_at': str, 'source_as_of': str,
    'threshold': {'change_pct': _NUMBER, 'trading_value': _NUMBER},
    'operation': {'state': str, 'last_run_at': str, 'source_status': str,
                  'processed': int, 'pending': int},
    'items': [{
        'id': str, 'symbol': str, 'name': str, 'market': str, 'session': str,
        'first_detected_at': str, 'price_observed_at': str, 'price': _NUMBER,
        'change_pct': _NUMBER, 'trading_value': _NUMBER, 'status': str, 'summary': str,
        'evidence': [{
            'id': str, 'kind': str, 'title': str, 'url': str, 'source': str,
            'publisher': str, 'published_at': str, 'published_precision': str,
            'first_received_at': str, 'timing': str, 'discovered_after_observation': bool,
            'category': str, 'direction': str, 'verification': str, 'duplicate_count': int,
        }],
        'checks': [{'source': str, 'status': str, 'checked_at': str, 'count': int, 'error': str}],
        'limitations': [str],
    }],
}


def surge_traces_response():
    """Serve the standalone trace worker's saved result; never trigger lookup."""
    if not _allowed():
        return _response({'error': 'kongming_catalyst_forbidden'}, 403)
    if request.args:
        return _response({'error': 'invalid_surge_trace_query'}, 400)
    from app.services.surge_trace import service
    try:
        raw = service.read_view()
        if (not isinstance(raw, dict) or raw.get('schema_version') != 1
                or not isinstance(raw.get('status'), str) or not isinstance(raw.get('items'), list)):
            raise ValueError('Invalid saved trace')
        payload = _project(raw, _SURGE_FIELDS)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, RecursionError):
        return _response({'error': 'surge_trace_unavailable'}, 503)
    return _response(payload, 200)


_FINDING_FIELDS = {'text': str, 'claim_status': str, 'evidence_ids': [str], 'quotes': [{'evidence_id': str, 'quote': str}]}
_REVIEW_FIELDS = {
    'schema_version': int, 'kind': str, 'status': str, 'last_run_at': str, 'empty_reason': str,
    'items': [{
        'id': str, 'input_fingerprint': str, 'source_input_fingerprint': str,
        'decision_id': str, 'article_id': str, 'generated_at': str, 'source_cutoff_at': str,
        'source_origin_at': str, 'candidate_basis': str, 'original_status': str,
        'status': str, 'provider': str, 'model': str, 'fallback_reason': str,
        'omitted_findings': int,
        'freshness': str, 'review_scope': str,
        'rows': [{'symbol': str, 'name': str, 'market': str,
                  'strengths': [_FINDING_FIELDS], 'risks': [_FINDING_FIELDS], 'what_to_watch': [_FINDING_FIELDS]}],
        'sources': [{'evidence_id': str, 'title': str, 'url': str, 'source': str,
                     'published_at': str, 'fetched_at': str, 'verification_status': str,
                     'available_at_original_decision': bool}],
    }],
}


def evidence_review_response(*, candidate=False):
    """Serve allowlisted saved interpretations using each product's access gate."""
    if not candidate and not _allowed():
        return _response({'error': 'kongming_catalyst_forbidden'}, 403)
    if request.query_string or request.get_data(cache=True).strip():
        return _response({'error': 'invalid_evidence_review_request'}, 400)
    try:
        from app.services import evidence_review
        read = evidence_review.read_candidate_review if candidate else evidence_review.read_article_reviews
        payload = _project(read(), _REVIEW_FIELDS)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, RecursionError):
        return _response({'error': 'evidence_review_unavailable'}, 503)
    return _response(payload, 200)
