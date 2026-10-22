"""Versioned candidate-desk inputs: immutable success objects, failed-only resume.

The caller supplies the isolated candidate-desk inputs root. No v1/v2 input,
decision or outcome files are read or modified here. Current publication is the
last step of a complete, hash-verified acquisition; readers do no provider IO.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from filelock import FileLock, Timeout

from app.utils.atomic_json import write_json_atomic
from .daily_source import (DailySourceError, KISDailyProvider, SOURCE_CONTRACT, _bar,
                           _clock, _cutoff, _number, _session, _stamp, _symbol)

SNAPSHOT_VERSION = 'candidate-desk-inputs-v1'
_CODES = {'candidate_inputs_missing', 'candidate_inputs_integrity', 'candidate_inputs_scope',
    'candidate_inputs_source', 'candidate_inputs_identity', 'candidate_inputs_ohlcv',
    'candidate_inputs_capture', 'candidate_inputs_session', 'candidate_inputs_session_incomplete',
    'candidate_inputs_incomplete', 'candidate_inputs_provider', 'candidate_inputs_publish',
    'candidate_inputs_busy'}


class CandidateInputError(ValueError):
    def __init__(self, code, *, failures=None):
        self.code = code if code in _CODES else 'candidate_inputs_provider'
        self.failures = dict(failures or {})
        self.failed_symbols = sorted(self.failures)
        super().__init__(self.code)


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _read(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or set(value) != {'data', 'sha256'}
                or not isinstance(value['data'], dict) or not _digest(value['sha256'])
                or value['sha256'] != _hash(value['data'])):
            raise ValueError()
        return value['data']
    except (OSError, ValueError, TypeError, OverflowError):
        raise CandidateInputError('candidate_inputs_integrity') from None


def _write(path, data):
    write_json_atomic(str(path), dict(data=data, sha256=_hash(data)), sort_keys=True)


def _spec(symbols, latest_session, scope_hash, names):
    try:
        if (not isinstance(symbols, (list, tuple, set)) or not 1 <= len(symbols) <= 100
                or len(set(symbols)) != len(symbols) or not _digest(scope_hash)
                or not isinstance(names, dict)):
            raise ValueError()
        ordered = sorted(_symbol(symbol) for symbol in symbols)
        selected_names = {}
        for symbol in ordered:
            name = names.get(symbol) or symbol
            if not isinstance(name, str) or not 1 <= len(name) <= 100 or any(ord(c) < 32 for c in name):
                raise ValueError()
            selected_names[symbol] = name
        latest_session = _session(latest_session)
    except (ValueError, TypeError):
        raise CandidateInputError('candidate_inputs_scope') from None
    return dict(snapshot_version=SNAPSHOT_VERSION, symbols=ordered, scope_hash=scope_hash,
        names=selected_names, latest_session=latest_session, requested_sessions=756,
        source_contract=deepcopy(SOURCE_CONTRACT), source_contract_hash=_hash(SOURCE_CONTRACT),
        symbols_hash=_hash(dict(version=SNAPSHOT_VERSION, symbols=ordered, scope_hash=scope_hash,
                               source_contract=SOURCE_CONTRACT, latest_session=latest_session)))


def _validated(result, symbol, spec, upper, *, lower=None):
    """Recheck injected and saved provider data, retaining only public fields."""
    if not isinstance(result, dict) or result.get('symbol') != symbol:
        raise CandidateInputError('candidate_inputs_identity')
    if result.get('source') != spec['source_contract']:
        raise CandidateInputError('candidate_inputs_source')
    try:
        first, last = (_clock(result['capture'][key]) for key in ('first', 'last'))
        captured = _clock(result['captured_at'])
        if not _cutoff(spec['latest_session']) <= first <= last == captured <= upper:
            raise ValueError()
        if lower is not None and first < lower:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise CandidateInputError('candidate_inputs_capture') from None
    rows, observed = result.get('bars'), []
    if not isinstance(rows, list) or not 1 <= len(rows) <= 756:
        raise CandidateInputError('candidate_inputs_ohlcv')
    for raw in rows:
        if not isinstance(raw, dict) or raw.get('symbol') != symbol:
            raise CandidateInputError('candidate_inputs_identity')
        try:
            day = _session(raw.get('date'))
            if day > spec['latest_session']:
                raise ValueError()
            row = dict(symbol=symbol, date=day)
            row.update({field: _number(raw.get(field), field)
                        for field in ('open', 'high', 'low', 'close', 'volume', 'traded_value')})
            if not (row['low'] <= row['open'] <= row['high'] and row['low'] <= row['close'] <= row['high']):
                raise ValueError()
            if raw.get('tradable') is not (row['volume'] > 0):
                raise ValueError()
            flags = raw.get('quality_flags')
            if (not isinstance(flags, list) or any(not isinstance(flag, dict) or set(flag) != {'code', 'severity'}
                    or flag['code'] not in ('zero_volume_nontradable', 'provider_price_event_unverified')
                    or flag['severity'] != ('nontradable' if flag['code'] == 'zero_volume_nontradable' else 'warning')
                    for flag in flags)):
                raise ValueError()
            if row['volume'] == 0 and dict(code='zero_volume_nontradable', severity='nontradable') not in flags:
                raise ValueError()
            source_flags = raw.get('source_flags')
            if (not isinstance(source_flags, dict) or not set(source_flags) <= {'flng_cls_code', 'prtt_rate', 'mod_yn', 'revl_issu_reas'}
                    or any(not isinstance(v, str) or len(v) > 80 or any(ord(c) < 32 for c in v)
                           for v in source_flags.values())):
                raise ValueError()
            row.update(tradable=raw['tradable'], quality_flags=deepcopy(flags), source_flags=deepcopy(source_flags))
        except (ValueError, KeyError, TypeError):
            raise CandidateInputError('candidate_inputs_ohlcv') from None
        observed.append(row)
    days = [row['date'] for row in observed]
    if days != sorted(set(days)) or days[-1] != spec['latest_session']:
        raise CandidateInputError('candidate_inputs_session')
    status = 'complete' if len(observed) == 756 else 'insufficient_history'
    if result.get('history_status') != status:
        raise CandidateInputError('candidate_inputs_ohlcv')
    # The default provider has already allowlisted raw pages; revalidate all of
    # them here as well so dependency injection cannot persist arbitrary bodies.
    pages = result.get('pages')
    if not isinstance(pages, list) or not 1 <= len(pages) <= 12:
        raise CandidateInputError('candidate_inputs_source')
    public_pages, page_prices, page_stamps = [], {}, []
    cursor = date.fromisoformat(spec['latest_session'])
    for index, page in enumerate(pages):
        try:
            if not isinstance(page, dict) or set(page) != {'params', 'captured_at', 'response'}:
                raise ValueError()
            at = _clock(page['captured_at'])
            params, response = page['params'], page['response']
            if (not first <= at <= last or page_stamps and at < page_stamps[-1]
                    or not isinstance(params, dict)
                    or set(params) != {'FID_COND_MRKT_DIV_CODE', 'FID_INPUT_ISCD', 'FID_INPUT_DATE_1',
                                      'FID_INPUT_DATE_2', 'FID_PERIOD_DIV_CODE', 'FID_ORG_ADJ_PRC'}
                    or params['FID_COND_MRKT_DIV_CODE'] != 'J' or params['FID_INPUT_ISCD'] != symbol
                    or params['FID_PERIOD_DIV_CODE'] != 'D' or params['FID_ORG_ADJ_PRC'] != '0'
                    or params['FID_INPUT_DATE_2'] != cursor.strftime('%Y%m%d')
                    or params['FID_INPUT_DATE_1'] != (cursor-timedelta(days=370)).strftime('%Y%m%d')
                    or not isinstance(response, dict) or set(response) != {'rt_cd', 'output1', 'output2'}
                    or response['rt_cd'] != '0' or response['output1'] != {'stck_shrn_iscd': symbol}
                    or not isinstance(response['output2'], list) or len(response['output2']) > 100):
                raise ValueError()
            public_rows, page_days = [], []
            for raw in response['output2']:
                row, public = _bar(raw, symbol)
                if (not (cursor-timedelta(days=370)).isoformat() <= row['date'] <= cursor.isoformat()
                        or row['date'] in page_prices and page_prices[row['date']] != row):
                    raise ValueError()
                page_prices[row['date']] = row
                page_days.append(row['date'])
                public_rows.append(public)
            if page_days:
                cursor = date.fromisoformat(min(page_days))-timedelta(days=1)
            elif index != len(pages)-1:
                raise ValueError()
            page_stamps.append(at)
            public_pages.append(dict(params=deepcopy(params), captured_at=_stamp(at),
                response=dict(rt_cd='0', output1=dict(stck_shrn_iscd=symbol), output2=public_rows)))
        except (ValueError, KeyError, TypeError):
            raise CandidateInputError('candidate_inputs_source') from None
    if (page_stamps[0] != first or page_stamps[-1] != last
            or [page_prices[day] for day in sorted(page_prices)[-756:]] != observed
            or status == 'insufficient_history' and pages[-1]['response']['output2']):
        raise CandidateInputError('candidate_inputs_source')
    return dict(symbol=symbol, bars=observed, source=deepcopy(spec['source_contract']),
        capture=dict(first=_stamp(first), last=_stamp(last)), captured_at=_stamp(captured),
        pages=public_pages, history_status=status)


def _objects(root, references, spec, upper):
    if not isinstance(references, dict) or not set(references) <= set(spec['symbols']):
        raise CandidateInputError('candidate_inputs_integrity')
    values = {}
    for symbol, digest in references.items():
        if not _digest(digest):
            raise CandidateInputError('candidate_inputs_integrity')
        value = _read(root/'objects'/(digest+'.json'))
        if _hash(value) != digest:
            raise CandidateInputError('candidate_inputs_integrity')
        try:
            values[symbol] = _validated(value, symbol, spec, upper)
        except CandidateInputError:
            raise CandidateInputError('candidate_inputs_integrity') from None
    return values


def _assemble(spec, identity, objects, references):
    provenance = dict(snapshot_version=SNAPSHOT_VERSION, snapshot_id=identity,
        source_contract=deepcopy(spec['source_contract']), source_contract_hash=spec['source_contract_hash'],
        scope_hash=spec['scope_hash'], symbols_hash=spec['symbols_hash'], symbol_hashes=references,
        history_status={symbol: objects[symbol]['history_status'] for symbol in spec['symbols']},
        historical_vintage_verified=False, corporate_actions_verified=False, finality_verified=False,
        cohort='dated_current_financial_quality_TOP100_not_historical_point_in_time')
    result = dict(prices_by_symbol={symbol: objects[symbol]['bars'] for symbol in spec['symbols']},
        names=spec['names'], latest_session=spec['latest_session'], provenance=provenance,
        capture_audit={symbol: objects[symbol]['capture'] for symbol in spec['symbols']})
    result['input_fingerprint'] = _hash(result)
    return result


def _load_snapshot(root, identity, *, upper):
    if not _digest(identity):
        raise CandidateInputError('candidate_inputs_integrity')
    saved = _read(root/'snapshots'/identity/'manifest.json')
    spec, references = saved.get('spec'), saved.get('objects')
    try:
        if (not isinstance(spec, dict) or _hash(spec) != identity
                or spec != _spec(spec['symbols'], spec['latest_session'], spec['scope_hash'], spec['names'])
                or not isinstance(references, dict) or set(references) != set(spec['symbols'])):
            raise ValueError()
        objects = _objects(root, references, spec, upper)
        result = _assemble(spec, identity, objects, references)
        if saved.get('input_fingerprint') != result['input_fingerprint']:
            raise ValueError()
        return result
    except (ValueError, TypeError, KeyError):
        raise CandidateInputError('candidate_inputs_integrity') from None


def load_inputs(root):
    """Read the complete sealed pointer only; no network calls or file writes."""
    root = Path(root)
    if not (root/'current.json').exists():
        raise CandidateInputError('candidate_inputs_missing')
    pointer = _read(root/'current.json')
    result = _load_snapshot(root, pointer.get('snapshot_id'), upper=datetime.now(timezone.utc))
    if pointer.get('input_fingerprint') != result['input_fingerprint']:
        raise CandidateInputError('candidate_inputs_integrity')
    return result


def collect_inputs(root, symbols, *, latest_session, scope_hash, names, provider=None, now=None):
    """Collect at most 100 symbols, preserving successes across bounded failures.

    ``now`` is an injectable validation clock, never a capture-time override.
    For real collection leave it unset: every request records its actual time.
    """
    current = _clock(datetime.now(timezone.utc) if now is None else now)
    spec = _spec(symbols, latest_session, scope_hash, names)
    if current < _cutoff(spec['latest_session']):
        raise CandidateInputError('candidate_inputs_session_incomplete')
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    identity = _hash(spec)
    directory = root/'snapshots'/identity
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(str(root/'acquisition.lock'), timeout=1):
            if (directory/'manifest.json').exists():
                result = _load_snapshot(root, identity, upper=current)
            else:
                progress_path = directory/'progress.json'
                progress = _read(progress_path) if progress_path.exists() else dict(spec=spec, objects={}, failures={})
                if progress.get('spec') != spec:
                    raise CandidateInputError('candidate_inputs_integrity')
                references = progress.get('objects')
                objects = _objects(root, references, spec, current)
                source, failures = provider or KISDailyProvider(), {}
                for symbol in spec['symbols']:
                    if symbol in objects:
                        continue
                    lower = current if now is not None else datetime.now(timezone.utc)
                    try:
                        raw = source.fetch_history(symbol, spec['latest_session'], count=756)
                        upper = current if now is not None else datetime.now(timezone.utc)
                        value = _validated(raw, symbol, spec, upper, lower=lower)
                        digest = _hash(value)
                        path = root/'objects'/(digest+'.json')
                        if path.exists():
                            if _read(path) != value:
                                raise CandidateInputError('candidate_inputs_integrity')
                        else:
                            _write(path, value)
                        objects[symbol], references[symbol] = value, digest
                    except CandidateInputError as exc:
                        failures[symbol] = exc.code
                    except DailySourceError as exc:
                        failures[symbol] = exc.code
                    except Exception:
                        failures[symbol] = 'candidate_inputs_provider'
                    _write(progress_path, dict(spec=spec, objects=references, failures=failures))
                if failures:
                    raise CandidateInputError('candidate_inputs_incomplete', failures=failures)
                if set(objects) != set(spec['symbols']):
                    raise CandidateInputError('candidate_inputs_integrity')
                result = _assemble(spec, identity, objects, references)
                _write(directory/'manifest.json', dict(spec=spec, objects=references,
                    input_fingerprint=result['input_fingerprint']))
            try:
                _write(root/'current.json', dict(snapshot_id=identity, input_fingerprint=result['input_fingerprint']))
            except Exception:
                raise CandidateInputError('candidate_inputs_publish') from None
            return result
    except Timeout:
        raise CandidateInputError('candidate_inputs_busy') from None
