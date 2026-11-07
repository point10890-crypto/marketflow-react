"""Bounded, local-only evidence for institutional collection coverage and age."""
from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import io
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
MAX_STATUS_BYTES = 4_000_000
MAX_METADATA_BYTES = 256_000
MAX_CSV_BYTES = 16_000_000
MAX_CODES = 10_000
SOURCE = 'naver_finance_trend_api'
FILES = ('institutional_collection_status.json', 'all_institutional_metadata.csv',
         'all_institutional_trend_data.csv')


class InvalidEvidence(ValueError):
    pass


def _require(condition):
    if not condition:
        raise InvalidEvidence('inconsistent_collection_evidence')


def _read(path: Path, limit: int) -> str:
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    _require(len(raw) <= limit)
    return raw.decode('utf-8-sig')


def _csv(path: Path, limit: int):
    reader = csv.DictReader(io.StringIO(_read(path, limit)))
    _require(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)))
    rows = list(reader)
    _require(len(rows) <= MAX_CODES and all(None not in row for row in rows))
    return rows


def _integer(value, *, text=False):
    if text:
        _require(isinstance(value, str) and re.fullmatch(r'\d+', value) is not None)
        value = int(value)
    _require(type(value) is int and 0 <= value <= MAX_CODES)
    return value


def _timestamp(value):
    _require(isinstance(value, str) and bool(value))
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return (result if result.tzinfo else result.replace(tzinfo=KST)).astimezone(KST)


def _trading_day(day):
    from app.services.kis_screener import _is_kr_trading_day
    return day.weekday() < 5 and _is_kr_trading_day(day)


def _required_session(now):
    # After the close, allow the existing KR pipeline two hours to persist its
    # source observations. A weekend/holiday never advances this requirement.
    candidate = now.date()
    if now.time() < time(17, 30) or not _trading_day(candidate):
        candidate -= timedelta(days=1)
    for _ in range(40):
        if _trading_day(candidate):
            return candidate
        candidate -= timedelta(days=1)
    raise InvalidEvidence('calendar_unavailable')


def _fingerprints(paths):
    result = []
    for path in paths:
        try:
            stat = path.stat()
            result.append((stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            result.append(None)
    return result


def _unknown():
    return {'status': 'unknown', 'requested': None, 'successful': None, 'failed': None,
            'skipped': None, 'source_date': None, 'collected_at': None,
            'detail': '수급 수집 증빙이 없거나 유효하지 않아 품질을 확인할 수 없습니다.'}


def read_institutional_collection(data_dir, now: datetime | None = None):
    """Do not infer usable coverage from a file's existence or modification time.

    A verified zero-success attempt is a failure even if its failed producer
    intentionally kept the previous CSV/metadata. Successful attempts require
    matching ledger, metadata and actual CSV source rows before any OK result.
    """
    now = now or datetime.now(KST)
    now = (now if now.tzinfo else now.replace(tzinfo=KST)).astimezone(KST)
    paths = [Path(data_dir)/name for name in FILES]
    try:
        before = _fingerprints(paths)
        ledger = json.loads(_read(paths[0], MAX_STATUS_BYTES))
        _require(isinstance(ledger, dict))
        collected = _timestamp(ledger['collected_at'])
        _require(collected <= now + timedelta(seconds=5))
        counts = {key: _integer(ledger[field]) for key,field in
                  [('requested','attempted'),('successful','successful'),('failed','failed'),('skipped','skipped')]}
        _require(0 < counts['requested'] == sum(counts[key] for key in ('successful','failed','skipped')))
        requested = ledger['requested_codes']
        _require(isinstance(requested,list) and len(requested) == counts['requested'])
        _require(all(isinstance(code,str) and re.fullmatch(r'[0-9A-Z]{6}',code) for code in requested))
        _require(len(set(requested)) == len(requested))
        raw_outcomes = ledger['outcomes']
        _require(isinstance(raw_outcomes,list) and len(raw_outcomes) == len(requested))
        outcomes = {row['ticker']:row for row in raw_outcomes if isinstance(row,dict)}
        _require(set(outcomes) == set(requested))
        groups = {state:[code for code in requested if outcomes[code].get('status') == state]
                  for state in ('success','failed','skipped')}
        _require(all(len(groups[state]) == counts[field] for state,field in
                     [('success','successful'),('failed','failed'),('skipped','skipped')]))
        _require(ledger['failed_codes'] == groups['failed'])
        expected_state = 'failed' if not counts['successful'] else ('partial' if counts['failed'] else 'completed')
        _require(ledger['status'] == expected_state and _integer(ledger['usable_results']) == counts['successful'])
        result = dict(_unknown(), **counts, collected_at=collected.isoformat())
        if not counts['successful']:
            _require(before == _fingerprints(paths))
            return dict(result, status='failed', detail=f"유효 수집 0/{counts['requested']:,} · 실패 {counts['failed']:,} · 이력 부족 {counts['skipped']:,}")

        metadata_rows = _csv(paths[1], MAX_METADATA_BYTES)
        _require(len(metadata_rows) == 1)
        metadata = metadata_rows[0]
        metadata_time = _timestamp(metadata['collection_date'])
        _require(collected-timedelta(seconds=1) <= metadata_time <= min(now+timedelta(seconds=5),collected+timedelta(minutes=5)))
        for key,field in [('requested','attempted_scrapes'),('successful','successful_scrapes'),
                          ('failed','failed_scrapes'),('skipped','skipped_scrapes')]:
            _require(_integer(metadata[field],text=True) == counts[key])
        _require(json.loads(metadata['requested_codes']) == requested)
        _require(json.loads(metadata['failed_codes']) == groups['failed'])
        _require(SOURCE in metadata['data_source'].split(','))
        _require(_integer(metadata['updated_stocks'],text=True) == counts['successful'])
        stored_rows = _csv(paths[2], MAX_CSV_BYTES)
        stored = {row['ticker']:row for row in stored_rows}
        _require(len(stored) == len(stored_rows) == _integer(metadata['total_stocks'],text=True))
        _require(_integer(metadata['retained_stocks'],text=True) == len(stored)-counts['successful'])
        _require(paths[2].stat().st_mtime >= collected.timestamp()-1)
        source_days = []
        for code in groups['success']:
            row, outcome = stored[code], outcomes[code]
            source_day = date.fromisoformat(row['data_date'])
            scraped = date.fromisoformat(row['scrape_date'])
            _require(source_day <= now.date() and _trading_day(source_day))
            _require(source_day <= scraped <= collected.date())
            _require(row['data_source'] == SOURCE and row['data_date'] == outcome['data_date'])
            _require(outcome['reason'] == 'current_source_history')
            _require(_integer(row['total_days'],text=True) == _integer(outcome['total_days']) >= 5)
            for field in ('foreign_net_buy_5d','institutional_net_buy_5d'):
                value = Decimal(row[field])
                _require(value.is_finite() and value == value.to_integral_value())
            source_days.append(source_day)
        for code in groups['skipped']:
            outcome = outcomes[code]
            day = date.fromisoformat(outcome['data_date'])
            _require(outcome['reason'] == 'insufficient_history' and 0 < _integer(outcome['total_days']) < 5)
            _require(day <= now.date() and _trading_day(day))
        _require(metadata['latest_source_date'] == max(source_days).isoformat())
        _require(before == _fingerprints(paths))
        source_day = min(source_days)
        result['source_date'] = source_day.isoformat()
        coverage = f"유효 수집 {counts['successful']:,}/{counts['requested']:,} · 실패 {counts['failed']:,} · 이력 부족 {counts['skipped']:,}"
        required = _required_session(now)
        if source_day < required:
            return dict(result,status='stale',detail=f'{coverage} · 원본 {source_day.isoformat()}, 필요 거래일 {required.isoformat()}')
        return dict(result,status='partial' if counts['failed'] or counts['skipped'] else 'ok',
                    detail=f'{coverage} · 원본 {source_day.isoformat()}')
    except (OSError,ValueError,TypeError,KeyError,OverflowError,RecursionError,csv.Error,InvalidOperation):
        return _unknown()
