"""Atomic research publication and immutable, genuinely prospective decisions."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

from filelock import FileLock

from app.utils.atomic_json import write_json_atomic
from .execution import ExecutionPolicy, simulate_trade

KST = timezone(timedelta(hours=9))
MAX_BYTES = 16 * 1024 * 1024
MAX_DECISIONS = 730


def timestamp(now=None):
    value = datetime.now(timezone.utc) if now is None else datetime.fromisoformat(now.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('timezone_required')
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':')).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_encode(value)).hexdigest()


def _write(path, value):
    if len(_encode(value)) > MAX_BYTES:
        raise ValueError('artifact_capacity')
    write_json_atomic(str(path), value)


def _read(path):
    if not path.exists():
        return None
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('artifact_capacity')
    def invalid(_):
        raise ValueError('nonfinite_artifact')
    return json.loads(path.read_text(encoding='utf-8-sig'), parse_constant=invalid)


def _envelope(state='missing', report=None, now=None, error=None):
    return dict(schema_version=1, state=state, generated_at=timestamp(now) if state != 'missing' else None,
                report=report, error=error)


def read_status(root, *, now=None):
    try:
        raw = _read(Path(root) / 'status.json')
        if raw is None:
            return _envelope()
        status = raw['status']
        if raw['sha256'] != _hash(status) or status['schema_version'] != 1:
            raise ValueError('status_integrity')
        if status['state'] == 'running':
            started = datetime.fromisoformat(status['generated_at'].replace('Z', '+00:00'))
            current = datetime.fromisoformat(timestamp(now).replace('Z', '+00:00'))
            if (current-started).total_seconds() > 900:
                status = dict(status, state='failed', error='scan_interrupted')
        return status
    except (OSError, ValueError, KeyError, TypeError):
        return _envelope('failed', now=now, error='saved_result_unavailable')


def _save(root, status):
    _write(Path(root) / 'status.json', dict(status=status, sha256=_hash(status)))
    return status


def set_running(root, *, now=None):
    return _save(root, _envelope('running', read_status(root, now=now)['report'], now))


def set_failure(root, *, now=None):
    return _save(root, _envelope('failed', read_status(root, now=now)['report'], now, 'scan_unavailable'))


def publish(root, report, *, now=None, held=False):
    if report.get('schema_version') != 1 or report.get('mode') != 'research':
        raise ValueError('research_report_required')
    _encode(report)
    return _save(root, _envelope('held' if held else 'ready', report, now))


def _result_body(outcome):
    return {key: value for key, value in outcome.items()
            if key not in ('sha256', 'result_sha256', 'source_revisions')}


def _seal_result(result, decision, candidate, prices, observed_day):
    symbol = candidate['symbol']
    calendar = sorted({row['date'] for rows in prices.values() for row in rows
                       if decision['decision_date'] < row['date'] <= observed_day})
    original = decision['snapshots'].get(symbol, [])
    # A collection can lag the wall clock; unobserved tail sessions are not consumed.
    known_sessions = calendar + [row['date'] for row in original if row['date'] <= observed_day]
    latest_known = max(known_sessions, default=decision['decision_date'])
    cutoff = result.get('exit_date') or (calendar[0] if result['status'] == 'unfilled' and calendar else latest_known)
    future = [row for row in prices.get(symbol, []) if decision['decision_date'] < row['date'] <= cutoff]
    consumed = [{key: row.get(key) for key in ('date', 'open', 'high', 'low', 'close', 'volume')}
                for row in original + future]
    first_session = calendar[0] if calendar else None
    entry_quote = next((row for row in consumed if row['date'] == first_session), None)
    sealed = dict(deepcopy(result), consumed_ohlcv=consumed, consumed_cutoff=cutoff,
                  consumed_calendar=[day for day in calendar if day <= cutoff],
                  expected_entry_session=first_session, entry_quote=entry_quote,
                  observed_through=observed_day, source_revisions=[])
    sealed['result_sha256'] = _hash(_result_body(sealed))
    sealed['sha256'] = _hash(sealed)
    return sealed


def read_journal(root):
    journal = _read(Path(root) / 'forward.json')
    if journal is None:
        return dict(schema_version=1, decisions=[])
    if (journal.get('schema_version') != 1 or not isinstance(journal.get('decisions'), list)
            or journal.get('sha256') != _hash({key: value for key, value in journal.items() if key != 'sha256'})):
        raise ValueError('journal_integrity')
    for decision in journal['decisions']:
        frozen = {key: value for key, value in decision.items() if key not in ('sha256', 'outcomes')}
        if decision.get('sha256') != _hash(frozen):
            raise ValueError('decision_integrity')
        outcomes = decision.get('outcomes')
        if not isinstance(outcomes, list):
            raise ValueError('outcome_integrity')
        for outcome in outcomes:
            if (outcome.get('result_sha256') != _hash(_result_body(outcome))
                    or outcome.get('sha256') != _hash({key: value for key, value in outcome.items() if key != 'sha256'})):
                raise ValueError('outcome_integrity')
    return journal


def _record_revision(outcome, decision, report, prices, moment):
    symbol = outcome['symbol']
    current = {row['date']: row for row in prices.get(symbol, [])}
    changes = []
    for bar in outcome['consumed_ohlcv']:
        replacement = current.get(bar['date'])
        if replacement is not None and any(replacement.get(key) != bar.get(key) for key in ('open', 'high', 'low', 'close', 'volume')):
            changes.append({key: replacement.get(key) for key in ('date', 'open', 'high', 'low', 'close', 'volume')})
    reasons = ['consumed_bar_revision'] if changes else []
    if decision['provenance']['price_basis'] != report['provenance']['price_basis']:
        reasons.append('price_basis_changed')
    entry_day = outcome.get('expected_entry_session')
    if entry_day and outcome.get('entry_quote') is None and entry_day in current:
        reasons.append('previously_missing_entry_quote_added')
    # Bound legacy wall-clock cutoffs without changing their sealed result bodies.
    known_sessions = outcome['consumed_calendar'] + [bar['date'] for bar in outcome['consumed_ohlcv']]
    cutoff = min(outcome['consumed_cutoff'], max(known_sessions, default=decision['decision_date']))
    added = sorted({row['date'] for rows in prices.values() for row in rows
                    if decision['decision_date'] < row['date'] <= cutoff}
                   - set(outcome['consumed_calendar']))
    if added:
        reasons.append('consumed_calendar_revision')
    if not reasons:
        return outcome
    signature = _hash(dict(reasons=reasons, bars=changes, added_sessions=added,
                           price_basis=report['provenance']['price_basis']))
    if not any(row['revision_sha256'] == signature for row in outcome['source_revisions']):
        outcome['source_revisions'].append(dict(observed_at=moment, reasons=reasons, revision_sha256=signature))
    outcome['sha256'] = _hash({key: value for key, value in outcome.items() if key != 'sha256'})
    return outcome


def _outcome(decision, candidate, prices, observed_day):
    symbol = candidate['symbol']
    original = decision['snapshots'].get(symbol, [])
    current = {row['date']: row for row in prices.get(symbol, [])}
    if any(day['date'] in current and any(current[day['date']].get(key) != day.get(key)
           for key in ('open', 'high', 'low', 'close', 'volume')) for day in original):
        return dict(symbol=symbol, status='source_revision', net_return=None)
    future = [row for row in prices.get(symbol, []) if decision['decision_date'] < row['date'] <= observed_day]
    calendar = sorted({row['date'] for rows in prices.values() for row in rows
                       if decision['decision_date'] < row['date'] <= observed_day})
    if not calendar or not original:
        return dict(symbol=symbol, status='pending', net_return=None)
    if not future or future[0]['date'] != calendar[0] or future[0]['volume'] <= 0:
        return dict(symbol=symbol, status='unfilled', net_return=None)
    # Missing sessions make a local-session horizon differ from the union calendar.
    # Hold rather than silently evaluate a different policy.
    if [row['date'] for row in future] != [day for day in calendar if day <= future[-1]['date']]:
        return dict(symbol=symbol, status='missing_session', net_return=None)
    trade = simulate_trade(original+future, len(original)-1, policy=ExecutionPolicy(**decision['policy']))
    if trade is None:
        return dict(symbol=symbol, status='unfilled', net_return=None)
    return dict(symbol=symbol, status=trade['status'], entry_date=trade['entry_date'],
                exit_date=trade.get('exit_date'), net_return=trade.get('net_return'),
                exit_reason=trade.get('exit_reason'))


def observe_and_freeze(root, report, prices, *, now=None, policy=None):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    moment = timestamp(now)
    day = datetime.fromisoformat(moment.replace('Z', '+00:00')).astimezone(KST).date().isoformat()
    policy = policy or ExecutionPolicy()
    with FileLock(str(root / 'forward.lock'), timeout=30):
        journal = read_journal(root)
        for decision in journal['decisions']:
            existing = {row['symbol']: row for row in decision['outcomes']}
            observed = []
            for candidate in decision['candidates']:
                previous = existing.get(candidate['symbol'])
                if previous is not None and previous['status'] in ('closed', 'unfilled', 'source_revision', 'open'):
                    previous = _record_revision(previous, decision, report, prices, moment)
                    current_dates = {row['date'] for row in prices.get(candidate['symbol'], [])}
                    missing_observed_bar = any(bar['date'] > decision['decision_date'] and bar['date'] not in current_dates
                                               for bar in previous['consumed_ohlcv'])
                    # Missing observed entry/holding quotes defer an open result;
                    # they cannot move its actual observed entry to a later session.
                    if previous['status'] != 'open' or previous['source_revisions'] or missing_observed_bar:
                        observed.append(previous)
                        continue
                if decision['provenance']['price_basis'] != report['provenance']['price_basis']:
                    result = dict(symbol=candidate['symbol'], status='source_revision', net_return=None)
                else:
                    result = _outcome(decision, candidate, prices, day)
                observed.append(_seal_result(result, decision, candidate, prices, day))
            decision['outcomes'] = observed
        if report['candidates'] and not any(row['decision_date'] == day for row in journal['decisions']):
            if len(journal['decisions']) >= MAX_DECISIONS:
                raise ValueError('archive_journal_before_capacity')
            frozen = dict(decision_date=day, created_at=moment, price_as_of=report['as_of'],
                          candidates=deepcopy(report['candidates']), provenance=deepcopy(report['provenance']),
                          policy=asdict(policy), snapshots={row['symbol']: deepcopy(prices.get(row['symbol'], [])[-15:])
                                                           for row in report['candidates']})
            journal['decisions'].append(dict(frozen, sha256=_hash(frozen), outcomes=[
                _seal_result(dict(symbol=row['symbol'], status='pending', net_return=None), frozen, row, prices, day)
                for row in frozen['candidates']]))
        journal['sha256'] = _hash({key: value for key, value in journal.items() if key != 'sha256'})
        _write(root / 'forward.json', journal)
    outcomes = [outcome for decision in journal['decisions'] for outcome in decision['outcomes']]
    revised_closed = sum(row['status'] == 'closed' and bool(row['source_revisions']) for row in outcomes)
    completed = [row['net_return'] for row in outcomes if row['status'] == 'closed'
                 and row['net_return'] is not None and not row['source_revisions']]
    counts = {state: sum(row['status'] == state for row in outcomes) for state in
              ('pending', 'open', 'unfilled', 'missing_session', 'source_revision', 'closed')}
    counts['source_revision'] += sum(row['status'] != 'source_revision' and bool(row['source_revisions']) for row in outcomes)
    return dict(decisions=len(journal['decisions']), matured=len(completed),
                win_rate=sum(value > 0 for value in completed)/len(completed) if completed else None,
                mean_net_return=sum(completed)/len(completed) if completed else None,
                counts=counts, excluded_revised_closed=revised_closed,
                revision_policy='preserve_terminal_result_exclude_revised_closed_from_statistics',
                basis='frozen_watchlist_next_open_outcomes_not_account_pnl')
