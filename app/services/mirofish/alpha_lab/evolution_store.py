"""Independent, recoverable memory for fixed prospective evolution trials."""
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re

from filelock import FileLock, Timeout

from . import evolution, store

MAX_COHORTS = 106
MAX_STATUS_BYTES = 128 * 1024
PUBLIC_KEYS = frozenset({'schema_version', 'protocol_version', 'protocol_hash', 'binding', 'phase',
    'next_step', 'research_only', 'live_orders', 'approved_exposure', 'return_basis', 'window',
    'nomination', 'review', 'arms', 'reasons', 'declared_at', 'generated_at', 'status_id', 'status'})
BINDING_KEYS = ('decision_id', 'input_fingerprint', 'source_audit_hash')


def _directory(root):
    return Path(root)/'evolution'


def _clock(now=None):
    current = datetime.now(timezone.utc) if now is None else datetime.fromisoformat(now.replace('Z', '+00:00'))
    if current.utcoffset() is None:
        raise ValueError('evolution_clock')
    return current.astimezone(timezone.utc)


def _stamp(current):
    return current.isoformat().replace('+00:00', 'Z')


def _read(path, *, limit=store.MAX_BYTES):
    if not path.is_file():
        return None
    if path.stat().st_size > limit:
        raise ValueError('evolution_capacity')
    def nonfinite(_):
        raise ValueError('evolution_nonfinite')
    raw = json.loads(path.read_text(encoding='utf-8-sig'), parse_constant=nonfinite)
    if (not isinstance(raw, dict) or set(raw) != {'schema_version', 'data', 'sha256'}
            or type(raw['schema_version']) is not int or raw['schema_version'] != 1
            or not isinstance(raw['data'], dict) or raw['sha256'] != store._hash(raw['data'])):
        raise ValueError('evolution_integrity')
    return raw['data']


def _write(path, value):
    store._write(path, dict(schema_version=1, data=value, sha256=store._hash(value)))


def _binding(board):
    if not isinstance(board, dict) or any(not isinstance(board.get(key), str)
            or re.fullmatch('[0-9a-f]{64}', board[key]) is None for key in BINDING_KEYS):
        raise ValueError('evolution_binding')
    return {key: board[key] for key in BINDING_KEYS}


def _protocol(directory, current, *, create):
    expected = evolution.protocol_spec()
    path = directory/'protocol.json'
    saved = _read(path, limit=32768)
    if saved is None:
        if not create:
            return None
        saved = dict(expected, declared_at=_stamp(current))
        saved['protocol_id'] = store._hash(saved)
        _write(path, saved)
    if (set(saved) != set(expected) | {'declared_at', 'protocol_id'}
            or any(saved.get(key) != value for key, value in expected.items())
            or _clock(saved['declared_at']) > current
            or saved['protocol_id'] != store._hash({key: value for key, value in saved.items() if key != 'protocol_id'})):
        raise ValueError('evolution_protocol_changed')
    return saved


def initialize(root, *, now=None):
    current, directory = _clock(now), _directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    with FileLock(str(directory/'write.lock')).acquire(timeout=1):
        return deepcopy(_protocol(directory, current, create=True))


def _frozen(cohort):
    return {key: value for key, value in cohort.items() if key != 'observation'}


def _validate_cohort(cohort, protocol):
    if (not isinstance(cohort, dict) or cohort.get('schema_version') != 1
            or cohort.get('protocol_hash') != protocol['protocol_hash']
            or not isinstance(cohort.get('cohort_id'), str)
            or re.fullmatch('[0-9a-f]{64}', cohort['cohort_id']) is None
            or not isinstance(cohort.get('observation'), dict)):
        raise ValueError('evolution_cohort')
    day = cohort.get('decision_session')
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError('evolution_cohort_day')
    _binding(cohort.get('binding'))
    store._hash(cohort)


def _public(summary, protocol, board, current, *, status='ready', reasons=()):
    value = {key: deepcopy(item) for key, item in summary.items() if key in PUBLIC_KEYS}
    binding = _binding(board)
    if value.get('binding') != binding:
        for arm in value.get('arms', []):
            arm['selected'] = []
        reasons = (*reasons, 'current_selection_unavailable')
    value.update(binding=binding, declared_at=protocol['declared_at'], generated_at=_stamp(current), status=status)
    value['reasons'] = list(dict.fromkeys([*value.get('reasons', []), *reasons]))
    value['status_id'] = store._hash({key: item for key, item in value.items() if key != 'status_id'})
    if len(store._encode(value)) > MAX_STATUS_BYTES:
        raise ValueError('evolution_status_capacity')
    return value


def _persist_status(directory, value):
    _write(directory/'status.json', value)
    return deepcopy(value)


def _attempt(directory, current, status):
    # Operational metadata is recoverable; sealed trial evidence is not reset.
    try:
        previous = _read(directory/'last_attempt.json', limit=32768)
        if previous is not None and (set(previous) != {'attempted_at', 'status'}
                or previous['status'] not in ('ready', 'failed')):
            previous = None
        if previous is not None:
            _clock(previous['attempted_at'])
    except (ValueError, KeyError, TypeError):
        previous = None
    if previous is None or _clock(previous['attempted_at']) <= current:
        _write(directory/'last_attempt.json', dict(attempted_at=_stamp(current), status=status))


def _source_context(inputs, report, current):
    board = report.get('opportunity_board')
    binding = _binding(board)
    decision = _clock(report.get('decision_at'))
    if decision > current:
        raise ValueError('evolution_future_decision')
    session = report.get('latest_session')
    if (not isinstance(session, str) or date.fromisoformat(session).isoformat() != session
            or inputs.get('latest_session') != session or board.get('latest_session') != session
            or inputs.get('input_fingerprint') != binding['input_fingerprint']
            or report.get('input_fingerprint') != binding['input_fingerprint']
            or (report.get('opportunity_scan') or {}).get('audit_hash') != binding['source_audit_hash']):
        raise ValueError('evolution_source_context')
    return board, decision, session


def _nomination_receipt(protocol, cohorts, nomination):
    count = protocol['window']['nomination_sessions']
    if len(cohorts) < count:
        raise ValueError('evolution_nomination_coverage')
    return dict(protocol_id=protocol['protocol_id'],
                cohort_ids=[row['cohort_id'] for row in cohorts[:count]], nomination=deepcopy(nomination))


def _bound_nomination(receipt, protocol, cohorts):
    if (not isinstance(receipt, dict) or set(receipt) != {'protocol_id', 'cohort_ids', 'nomination'}
            or receipt != _nomination_receipt(protocol, cohorts, receipt['nomination'])):
        raise ValueError('evolution_nomination_binding')
    return deepcopy(receipt['nomination'])


def refresh(root, inputs, report, discovery, *, now=None):
    """Only the explicit research writer updates this independent namespace."""
    current, directory = _clock(now), _directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(directory/'write.lock')).acquire(timeout=1):
            protocol = _protocol(directory, current, create=True)
            board, decision, session = _source_context(inputs, report, current)
            cohort_dir, observation_dir = directory/'cohorts', directory/'observations'
            cohort_dir.mkdir(exist_ok=True); observation_dir.mkdir(exist_ok=True)
            paths = sorted(cohort_dir.glob('*.json'))
            if len(paths) > MAX_COHORTS:
                raise ValueError('evolution_cohort_capacity')
            cohort_path = cohort_dir/f'{session}.json'
            if (decision > _clock(protocol['declared_at']) and not cohort_path.exists()
                    and len(paths) < MAX_COHORTS):
                cohort = evolution.build_cohort(inputs, report, discovery, protocol=protocol, now=_stamp(current))
                _validate_cohort(cohort, protocol)
                if cohort['decision_session'] != session:
                    raise ValueError('evolution_cohort_day')
                _write(cohort_path, cohort)
                paths = sorted(cohort_dir.glob('*.json'))
            source_hash = store._hash(inputs['prices_by_symbol'])
            cohorts = []
            for path in paths:
                first = _read(path)
                _validate_cohort(first, protocol)
                if path.name != first['decision_session']+'.json':
                    raise ValueError('evolution_cohort_path')
                observed_path = observation_dir/(first['cohort_id']+'.json')
                saved = _read(observed_path)
                if saved is not None:
                    if (set(saved) != {'cohort', 'source_hash'} or not isinstance(saved['source_hash'], str)
                            or _frozen(saved['cohort']) != _frozen(first)):
                        raise ValueError('evolution_observation_identity')
                    observed = saved['cohort']
                else:
                    observed = first
                if saved is None or saved['source_hash'] != source_hash:
                    updated = evolution.observe_cohort(observed, inputs['prices_by_symbol'], now=_stamp(current))
                    if _frozen(updated) != _frozen(first):
                        raise ValueError('evolution_selection_changed')
                    _validate_cohort(updated, protocol)
                    _write(observed_path, dict(cohort=updated, source_hash=source_hash))
                    observed = updated
                cohorts.append(observed)
            receipt = _read(directory/'nomination.json', limit=32768)
            nomination = _bound_nomination(receipt, protocol, cohorts) if receipt is not None else None
            runtime = dict(protocol, **({'nomination': nomination} if nomination is not None else {}))
            summary = evolution.summarize(runtime, cohorts)
            if receipt is None and summary['nomination']['status'] in ('fixed', 'none'):
                _write(directory/'nomination.json', _nomination_receipt(protocol, cohorts, summary['nomination']))
                runtime['nomination'] = summary['nomination']
                summary = evolution.summarize(runtime, cohorts)
            if summary['review']['status'] == 'awaiting_review':
                review = dict(protocol_id=protocol['protocol_id'], nomination=summary['nomination'],
                              review=summary['review'], cohort_hashes=[store._hash(row) for row in cohorts],
                              research_only=True, live_orders=False, approved_exposure=0)
                review_dir = directory/'reviews'
                review_dir.mkdir(exist_ok=True)
                review_path = review_dir/(store._hash(review)+'.json')
                if not review_path.exists():
                    _write(review_path, review)
            extra = ['awaiting_first_prospective_decision'] if not cohorts else []
            value = _persist_status(directory, _public(summary, protocol, board, current, reasons=extra))
            _attempt(directory, current, 'ready')
            return value
    except (OSError, ValueError, KeyError, TypeError, Timeout):
        # Retain completed cohorts/observations/status. Public callers will bind
        # or hold the prior artifact; no optional failure rolls back research.
        try:
            with FileLock(str(directory/'write.lock')).acquire(timeout=1):
                _attempt(directory, current, 'failed')
        except (OSError, ValueError, KeyError, TypeError, Timeout):
            pass
        return dict(status='held', reason='evolution_refresh_failed')


def read_status(root, board, *, now=None):
    """Cheap saved GET; no lock creation, computation, acquisition or writes."""
    directory = _directory(root)
    try:
        value = _read(directory/'status.json', limit=MAX_STATUS_BYTES)
        if value is None:
            return None
        if (set(value) != PUBLIC_KEYS or value.get('schema_version') != 1
                or value.get('protocol_version') != evolution.POLICY
                or value.get('research_only') is not True or value.get('live_orders') is not False
                or type(value.get('approved_exposure')) not in (int, float)
                or value.get('approved_exposure') != 0 or value.get('status') not in ('ready', 'held')
                or value.get('status_id') != store._hash({key: item for key, item in value.items() if key != 'status_id'})):
            raise ValueError('evolution_public_integrity')
        current = _clock(now)
        if _clock(value['generated_at']) > current:
            raise ValueError('evolution_public_future')
        protocol = _protocol(directory, current, create=False)
        if protocol is None or protocol['protocol_hash'] != value['protocol_hash'] or protocol['declared_at'] != value['declared_at']:
            raise ValueError('evolution_public_protocol')
        attempt = _read(directory/'last_attempt.json', limit=32768)
        if attempt is not None:
            if set(attempt) != {'attempted_at', 'status'} or attempt['status'] not in ('ready', 'failed'):
                raise ValueError('evolution_attempt_invalid')
            if _clock(attempt['attempted_at']) > current:
                raise ValueError('evolution_attempt_future')
            if attempt['status'] == 'failed' and _clock(attempt['attempted_at']) >= _clock(value['generated_at']):
                value = deepcopy(value)
                value['status'] = 'held'
                value['reasons'] = list(dict.fromkeys([*value['reasons'], 'last_refresh_failed']))
                value['status_id'] = store._hash({key: item for key, item in value.items() if key != 'status_id'})
        binding = _binding(board)
        if value['binding'] != binding:
            value = deepcopy(value)
            value['status'] = 'held'
            value['reasons'] = list(dict.fromkeys([*value['reasons'], 'current_identity_mismatch']))
            for arm in value['arms']:
                arm['selected'] = []
                arm['metrics'] = {key: None for key in arm['metrics']}
            value['status_id'] = store._hash({key: item for key, item in value.items() if key != 'status_id'})
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return None
