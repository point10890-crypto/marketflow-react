# 뉴스 사건을 분류하고 최초 가격 검출과의 시간 관계만 공개한다.
"""Pure, bounded supporting news context; never a selection or approval input."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import unquote, urlsplit, urlunsplit

from app.services.omni.funnel import match_symbols

from . import opportunity_store, store

POLICY = 'alpha-catalyst-context-v1'
HYPOTHESIS = 'price_setup_leads_catalyst_72h_v1'
HORIZON_HOURS = 72
MAX_ROWS = 3
MAX_EVENTS = 8
MAX_CONTEXT_BYTES = 65536
IDENTITY_KEYS = ('decision_id', 'input_fingerprint', 'source_audit_hash')
MEDIA_HOSTS = ('yna.co.kr', 'yna.kr', 'hankyung.com', 'mk.co.kr', 'mt.co.kr', 'asiae.co.kr')
STAGES = frozenset(('valuation_opinion', 'site_inspection', 'infrastructure', 'investment', 'contract', 'earnings', 'other'))
POLARITIES = frozenset(('supportive', 'adverse', 'mixed', 'unknown'))
TIMINGS = frozenset(('captured_before_first', 'published_before_captured_after', 'reported_after_first'))
CONTEXT_KEYS = {'schema_version', 'policy_version', *IDENTITY_KEYS, 'decision_at', 'captured_at',
    'snapshot_id', 'status', 'used_in_selection', 'association_status', 'rows', 'validation'}
ROW_KEYS = {'symbol', 'name', 'first_detected_at', 'first_decision_id', 'events'}
EVENT_KEYS = {'event_id', 'event_group', 'title', 'url', 'source', 'grade', 'published_at',
    'collected_at', 'stage', 'polarity', 'timing'}
VALIDATION_KEYS = {'status', 'hypothesis', 'horizon_hours', 'started_at', 'enrolled_decisions',
    'matured_decisions', 'coincidence_rejected'}
KST = timezone(timedelta(hours=9))
UNSAFE_TEXT = re.compile(r'[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069<>\\]'
    r'|(?:^|[\s"\'/])[A-Za-z]:/|/(?:home|srv|tmp|users|private|etc|var|root)\b|\.env\b'
    r'|(?:미래|예상|상승|하락)\s*(?:승률|확률)\s*[:=]?\s*\d|(?:수익|승률).*보장', re.IGNORECASE)
PRIVATE_TEXT = re.compile(r'(?:^|[^a-z0-9])(?:api[_-]?key|access[_-]?token|secret|password|credentials?'
    r'|authorization|bearer|traceback|token[_-]?cache)(?:$|[^a-z0-9])', re.IGNORECASE)


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return result.astimezone(timezone.utc) if isinstance(result, datetime) and result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _clock(now=None):
    current = datetime.now(timezone.utc) if now is None else _time(now)
    if current is None:
        raise ValueError('catalyst_clock_invalid')
    return current


def _stamp(value):
    parsed = _time(value)
    if parsed is None:
        raise ValueError('catalyst_clock_invalid')
    return parsed.isoformat().replace('+00:00', 'Z')


def _hex(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _text(value, limit):
    # UTF-16 units match browser string limits, including astral Unicode glyphs.
    return (isinstance(value, str) and bool(value.strip()) and len(value.encode('utf-16-le'))//2 <= limit
        and UNSAFE_TEXT.search(value) is None and PRIVATE_TEXT.search(value) is None)


def _safe_url(value):
    if not _text(value, 2000) or any(c.isspace() for c in value):
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme not in ('http', 'https') or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443 if parsed.scheme == 'https' else 80)
                or not any(host == item or host.endswith('.'+item) for item in MEDIA_HOSTS)):
            return False
        decoded = value
        for _ in range(3):
            if re.search(r'%(?![a-fA-F0-9]{2})', decoded):
                return False
            following = unquote(decoded, errors='strict')
            if not _text(following, 2000) or re.search(r'(?:javascript|data|file):', following, re.IGNORECASE):
                return False
            if following == decoded:
                break
            decoded = following
        return True
    except (ValueError, TypeError):
        return False


def _url_key(value):
    parsed = urlsplit(value)
    # Fragments do not identify different news reports; query/path remain intact.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ''))


def _binding(board):
    try:
        binding = opportunity_store._binding(board)
        if any(not _text(row.get('name') or row['symbol'], 120) for row in board['candidates']):
            raise ValueError('catalyst_identity_invalid')
        return binding
    except (ValueError, KeyError, TypeError):
        raise ValueError('catalyst_identity_invalid') from None


def _validation(value, captured):
    if (not isinstance(value, dict) or set(value) != VALIDATION_KEYS or value.get('status') != 'collecting'
            or value.get('hypothesis') != HYPOTHESIS or type(value.get('horizon_hours')) is not int
            or value['horizon_hours'] != HORIZON_HOURS or _time(value.get('started_at')) is None
            or _time(value['started_at']) > captured or type(value.get('enrolled_decisions')) is not int
            or not 0 <= value['enrolled_decisions'] <= opportunity_store.MAX_ISSUED
            or type(value.get('matured_decisions')) is not int or value['matured_decisions'] != 0
            or value.get('coincidence_rejected') is not False):
        raise ValueError('catalyst_validation_invalid')
    return dict(deepcopy(value), started_at=_stamp(value['started_at']))


def _asserted_positive(text, start, end):
    """A bounded literal guard; planning or denying an action is not completion."""
    boundary = r'[,.;!?…]|하지만|다만|반면|그러나'
    before = re.split(boundary, text[max(0, start-12):start])[-1]
    after = re.split(boundary, text[end:end+24])[0]
    blocked_before = re.search(r'(미|불|못)$|(검토중|예정|계획|미확정).{0,6}$', before)
    blocked_after = re.search(r'검토|예정|계획|논의|협의|추진|기대|전망|예상|가능|여부|미정|불확실|위해'
        r'|실패|불발|부인|아니|않|되지|안(됐|되|돼|한|해|했)|못(됐|되|돼|한|해|했)|없', after)
    return not blocked_before and not blocked_after


def classify_event(title, summary=''):
    """Classify literal reporting semantics, independently of source importance."""
    text = ' '.join((str(title or '')[:260], str(summary or '')[:500]))
    compact = re.sub(r'\s+', '', text)
    has = lambda words: any(word in compact for word in words)
    def asserted(words):
        return any(_asserted_positive(compact, match.start(), match.end())
            for word in words for match in re.finditer(re.escape(word), compact))
    if (has(('부지점검', '부지현장', '현장점검', '현장시찰', '현장방문', '부지시찰'))
            or re.search(r'부지.{0,20}(점검|시찰|방문|찾은)', compact)):
        stage = 'site_inspection'
    elif has(('전력', '용수', '인프라', '송전망', '전력망')):
        stage = 'infrastructure'
    elif has(('저평가', '고평가', '목표주가', '매수의견', '투자의견')):
        stage = 'valuation_opinion'
    elif has(('공급계약', '계약체결', '계약해지', '수주')):
        stage = 'contract'
    elif has(('영업이익', '영업익', '순이익', '실적', '매출', '흑자', '적자')):
        stage = 'earnings'
    elif has(('투자', '증설', '착공', '신규공장')):
        stage = 'investment'
    else:
        stage = 'other'

    positive = negative = False
    if stage == 'valuation_opinion':
        positive = asserted(('저평가', '매수의견', '상향'))
        negative = has(('고평가', '하향', '매도의견'))
    elif stage == 'site_inspection':
        negative = has(('중단', '취소', '불허', '무산'))
    elif stage == 'infrastructure':
        positive = asserted(('확충', '확대', '구축', '공급확정', '지원확정', '공급지원'))
        negative = has(('부족', '중단', '지연', '취소', '불허', '무산'))
    elif stage == 'investment':
        negative = has(('취소', '중단', '철회', '축소', '무산'))
        positive = asserted(('확정', '발표', '착공', '완공')) and not negative
    elif stage == 'contract':
        negative = has(('실패', '무산', '해지', '취소', '불발'))
        positive = asserted(('체결', '수주', '계약성공')) and not negative
    elif stage == 'earnings':
        positive = asserted(('증가', '증익', '급증', '흑자전환', '사상최대', '최대실적'))
        negative = has(('감소', '감익', '급감', '적자', '실적악화'))
    else:
        # A released halt is a different assertion from an active halt.
        release_pattern = re.compile(r'(거래정지|상장폐지위험|위험).{0,12}?(해소|해제|종료)')
        def reported(match):
            return _asserted_positive(compact, match.start(2), match.end(2))
        released = any(reported(match) for match in release_pattern.finditer(compact))
        positive = released or asserted(('거래재개',))
        risk_text = release_pattern.sub(lambda match: '' if reported(match) else match.group(), compact)
        negative = any(word in risk_text for word in ('거래정지', '상장폐지', '횡령', '부도', '회계부정'))
    polarity = 'mixed' if positive and negative else 'supportive' if positive else 'adverse' if negative else 'unknown'
    return dict(stage=stage, polarity=polarity)


def _timing(published, collected, first):
    return ('captured_before_first' if collected <= first else
            'published_before_captured_after' if published <= first else 'reported_after_first')


def _group(symbol, event):
    """Conservative topic/day groups are descriptive, never independent trials."""
    title = event['title']
    anchors = [word for word in ('용인', '이천', '청주', '평택', '미국', '일본', '중국', 'HBM') if word in title]
    topic = 'trading_halt' if '거래정지' in title or '거래재개' in title else event['stage']
    if topic == 'other':
        topic = re.sub(r'[^가-힣A-Za-z0-9]', '', title).lower()
    return store._hash(dict(symbol=symbol, topic=topic, anchors=anchors,
        day=_time(event['published_at']).astimezone(KST).date().isoformat()))


def _events(raw_events, symbol, name, first, captured):
    normalized = []
    for raw in raw_events:
        if not isinstance(raw, dict) or symbol not in (raw.get('symbols') or []):
            continue
        published, collected = _time(raw.get('published_ts')), _time(raw.get('collected_at'))
        title = ' '.join(str(raw.get('title') or '').split())[:260]
        url, source = raw.get('link'), raw.get('source')
        if (published is None or collected is None or not published <= collected <= captured
                or not _hex(raw.get('content_hash')) or raw.get('grade') != 'B'
                or not _text(title, 260) or not _text(source, 64) or not _safe_url(url)
                or symbol not in match_symbols(title, {symbol:name})):
            continue
        event = dict(title=title, url=url, source=source, grade='B', published_at=_stamp(published),
            collected_at=_stamp(collected), **classify_event(title, raw.get('summary')),
            timing=_timing(published, collected, first))
        event['event_id'] = store._hash(dict(symbol=symbol, content_hash=raw['content_hash'], **event))
        event['event_group'] = _group(symbol, event)
        normalized.append((event, raw['content_hash'], _url_key(url)))
    normalized.sort(key=lambda row: (_time(row[0]['collected_at']), _time(row[0]['published_at']), row[0]['event_id']))
    # Union components retain the earliest actual capture even with chained URL/hash duplicates.
    components = []
    for event, digest, url in normalized:
        hits = [component for component in components if digest in component['hashes'] or url in component['urls']]
        if not hits:
            components.append(dict(event=event, hashes={digest}, urls={url}))
            continue
        keep = hits[0]
        keep['hashes'].add(digest); keep['urls'].add(url)
        for other in hits[1:]:
            keep['hashes'].update(other['hashes']); keep['urls'].update(other['urls'])
            components.remove(other)
    events = [item['event'] for item in components]
    if len(events) > MAX_EVENTS:
        # Retain both capture periods. Follow-up volume cannot consume all
        # pre-detection slots; sparse periods leave space for recent remaining reports.
        quota = MAX_EVENTS//2
        chosen = [row for row in events if row['timing'] == 'captured_before_first'][-quota:]
        chosen += [row for row in events if row['timing'] != 'captured_before_first'][-quota:]
        free = MAX_EVENTS-len(chosen)
        if free:
            ids = {row['event_id'] for row in chosen}
            chosen += [row for row in events if row['event_id'] not in ids][-free:]
        events = chosen
        events.sort(key=lambda row: (_time(row['collected_at']), _time(row['published_at']), row['event_id']))
    return events


def _first_detection(journal, symbol, decision):
    # Callers validate the journal and current issue before consulting history.
    history = [row['board'] for row in journal['issued']
        if any(item['symbol'] == symbol for item in row['board']['candidates'])
        and _time(row['board']['generated_at']) <= decision]
    if not history:
        raise ValueError('catalyst_journal_unavailable')
    return min(history, key=lambda row: (_time(row['generated_at']), row['decision_id']))


def build_catalyst_context(board, journal, events, *, validation, now=None):
    """Build current observations tied to a sealed decision and earliest issued clocks."""
    current = _clock(now); binding = _binding(board); decision = _time(board['generated_at'])
    if decision > current:
        raise ValueError('catalyst_identity_invalid')
    try:
        opportunity_store._validate_journal(journal)
        issued = next((row['board'] for row in journal['issued'] if row['decision_id'] == binding['decision_id']), None)
        if issued is None or opportunity_store._stable(issued) != opportunity_store._stable(board) or _time(issued['generated_at']) != decision:
            raise ValueError('catalyst_journal_unavailable')
    except (ValueError, KeyError, TypeError):
        raise ValueError('catalyst_journal_unavailable') from None
    if not isinstance(events, list) or len(events) > MAX_ROWS*512:
        raise ValueError('catalyst_news_capacity')
    rows = []
    for candidate in board['candidates']:
        symbol = candidate['symbol']
        first = _first_detection(journal, symbol, decision)
        first_at = _time(first['generated_at'])
        rows.append(dict(symbol=symbol, name=candidate.get('name') or symbol,
            first_detected_at=_stamp(first_at), first_decision_id=first['decision_id'],
            events=_events(events, symbol, candidate.get('name') or symbol, first_at, current)))
    value = dict(schema_version=1, policy_version=POLICY, **binding, decision_at=_stamp(decision),
        captured_at=_stamp(current), status='ready', used_in_selection=False, association_status='unproven',
        rows=rows, validation=_validation(validation, current))
    value['snapshot_id'] = store._hash(value)
    if public_catalyst_context(value, board, now=current) is None:
        raise ValueError('catalyst_context_invalid')
    return value


def public_catalyst_context(value, board, *, now=None):
    """Validate an owned JSON projection; no providers, DB, files, or repairs."""
    try:
        current = _clock(now); binding = _binding(board)
        if (not isinstance(value, dict) or set(value) != CONTEXT_KEYS
                or type(value.get('schema_version')) is not int or value['schema_version'] != 1
                or value.get('policy_version') != POLICY or any(value.get(k) != v for k,v in binding.items())
                or not _hex(value.get('snapshot_id')) or value['snapshot_id'] != store._hash({k:v for k,v in value.items() if k != 'snapshot_id'})
                or value.get('decision_at') != _stamp(board['generated_at']) or value.get('status') not in ('ready', 'unavailable')
                or value.get('used_in_selection') is not False or value.get('association_status') != 'unproven'
                or len(store._encode(value)) > MAX_CONTEXT_BYTES):
            return None
        decision, captured = _time(value['decision_at']), _time(value['captured_at'])
        if captured is None or not decision <= captured <= current:
            return None
        _validation(value['validation'], captured)
        rows = value['rows']
        if not isinstance(rows, list) or len(rows) != len(board['candidates']) or len(rows) > MAX_ROWS:
            return None
        for row, candidate in zip(rows, board['candidates']):
            if (not isinstance(row, dict) or set(row) != ROW_KEYS or row.get('symbol') != candidate['symbol']
                    or row.get('name') != (candidate.get('name') or candidate['symbol'])
                    or not _text(row['name'], 120) or not _hex(row.get('first_decision_id'))):
                return None
            first = _time(row.get('first_detected_at'))
            events = row['events']
            if first is None or first > decision or not isinstance(events, list) or len(events) > MAX_EVENTS:
                return None
            seen_ids, seen_urls = set(), set()
            for event in events:
                if (not isinstance(event, dict) or set(event) != EVENT_KEYS
                        or not _hex(event.get('event_id')) or not _hex(event.get('event_group'))
                        or not _text(event.get('title'), 260) or not _text(event.get('source'), 64)
                        or not _safe_url(event.get('url')) or event.get('grade') != 'B'
                        or row['symbol'] not in match_symbols(event['title'], {row['symbol']:row['name']})
                        or event.get('stage') not in STAGES or event.get('polarity') not in POLARITIES
                        or event.get('timing') not in TIMINGS):
                    return None
                published, collected = _time(event['published_at']), _time(event['collected_at'])
                if (published is None or collected is None or not published <= collected <= captured
                        or event['timing'] != _timing(published, collected, first)
                        or event['event_group'] != _group(row['symbol'], event)
                        or event['event_id'] in seen_ids or _url_key(event['url']) in seen_urls):
                    return None
                seen_ids.add(event['event_id']); seen_urls.add(_url_key(event['url']))
        return deepcopy(value)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return None
