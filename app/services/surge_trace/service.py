"""Saved-price surge observations with recoverable, bounded evidence stages."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import re
import time

from filelock import FileLock

from app.utils.atomic_json import write_json_atomic
from app.utils.paths import BASE_DIR, DATA_DIR
from . import sources
from .common import clock, digest, normalized_name, safe_url, sports_title, stamp, title_matches

PROJECT_ROOT = Path(BASE_DIR)
ROOT = Path(DATA_DIR) / 'surge_trace'
POLICY = 'surge-v1-5pct-2b'
THRESHOLD = {'change_pct': 5, 'trading_value': 2_000_000_000}
ROW_FIELDS = ('id', 'symbol', 'name', 'market', 'session', 'first_detected_at',
              'price_observed_at', 'price', 'change_pct', 'trading_value',
              'status', 'summary', 'evidence', 'checks', 'limitations')
GROUPS = {
    'reported_driver': (),
    'contract': ('수주', '공급계약', '판매계약', '계약 체결', '계약체결', '계약 취소', '계약취소'),
    'earnings': ('실적', '매출', '영업이익', '순이익', '분기보고서', '반기보고서', '사업보고서'),
    'regulatory': ('허가', '승인', '규제', '제재', '인허가'),
    'capacity': ('증설', '시설투자', '설비투자', '신공장', '공장 준공', '공장 가동'),
    'capital_policy': ('자사주', '자기주식', '소각', '배당', '증자', '전환사채'),
    'risk': ('취소', '소송', '횡령', '배임', '적자', '하향', '유출', '회생', '영업정지'),
}
DRIVER_MOVE = re.compile(r'(?:국제\s*)?(?:유가|원유(?:\s*가격)?|원자재(?:\s*가격)?|환율|달러|금리)\s*'
                         r'(?:급락|하락|인하|급등|상승|인상|약세|강세)')
DRIVER_REACTION_GAP = re.compile(
    r'\s*(?:은|는|이|가)?\s*'
    r'(?:등\s+[가-힣A-Z]{2,12}주\s*)?'
    r'(?:주가(?:는|가|도)?\s*)?[,，:]?\s*'
    r'(?:(?:에|(?:으)?로|덕(?:분)?에|영향(?:으로)?|여파(?:로)?|수혜(?:로)?|때문(?:에)?)\s*)?'
    r'(?:주가(?:는|가|도)?\s*)?'
    r'(?:[+-]?\d+(?:\.\d+)?\s*%\s*(?:대|넘게|이상)?\s*)?'
    r'[\'"‘“]*\s*'
)
DRIVER_TO_TARGET = re.compile(
    r'\s*(?:에|(?:으)?로|덕(?:분)?에|영향으로|여파로|수혜로|때문에)\s*'
    r'(?:[가-힣A-Z]{2,12}주\s*[\'"‘“]*(?:급등|상승|강세|↑)[\'"’”]*[\s,….-]*)?'
)


def _read(root):
    try:
        state = json.loads((root / 'snapshot.json').read_bytes())
        if state.get('schema_version') != 1 or not isinstance(state.get('observations'), dict):
            raise ValueError('invalid_snapshot')
        return state
    except FileNotFoundError:
        return {'schema_version': 1, 'observations': {}, 'generated_at': None, 'source_as_of': None,
                'operation': {'state': 'waiting', 'last_run_at': None, 'source_status': 'unavailable',
                              'processed': 0, 'pending': 0}}


def _save(root, state):
    write_json_atomic(root / 'snapshot.json', state)


def _due(stage, now):
    if not stage:
        return True
    ttl = 15 if stage['status'] in {'ready', 'empty'} else 5
    return now >= stamp(stage['checked_at']) + timedelta(minutes=ttl)


def _reported_driver(title, issuer=None):
    """Recognize an explicit headline attribution, never infer a sector effect."""
    moves = list(DRIVER_MOVE.finditer(title))
    if not moves or not issuer or issuer not in title or re.search(r'에도|불구|반면|무관', title):
        return False
    issuer_start = title.index(issuer)
    issuer_end = issuer_start + len(issuer)
    for rise in re.finditer(r'급등|상승|강세|↑', title):
        if (not issuer_end <= rise.start() <= issuer_end + 100
                or any(move.start() <= rise.start() < move.end() for move in moves)):
            continue
        # The selected rise must belong to the named target under a closed
        # grammar, not another issuer or arbitrary text in a following clause.
        gap = DRIVER_MOVE.sub('', title[issuer_end:rise.start()])
        if not DRIVER_REACTION_GAP.fullmatch(gap):
            continue
        for move in moves:
            if move.end() > rise.start() or not re.match(
                    r'\s*(?:에(?!도)|(?:으)?로|덕(?:분)?에|영향|여파|수혜|덕분|때문)', title[move.end():]):
                continue
            # The cause either occurs within the target's own reaction clause
            # or directly introduces it (including an explicit sector lead-in).
            if issuer_end <= move.start() or (move.end() <= issuer_start and
                    DRIVER_TO_TARGET.fullmatch(title[move.end():issuer_start])):
                return True
    return False


def _category(title, issuer=None):
    if (any(term in title for term in ('기대', '전망', '예상', '가능성', '검토', '추정', '목표주가',
                                       '촉각', '우려', '불확실', '의문', '성장성', '봐야', '주목'))
            or (re.search(r'내년|내후년|다음\s*(?:해|분기)', title)
                and re.search(r'실적|영업이익|순이익|매출', title))
            or re.search(r'[?？]|(?:되나|될까|할까|일까|인가|받을까|올까)(?=$|[\s,?!…])', title)):
        return 'opinion'
    if _reported_driver(title, issuer):
        return 'reported_driver'
    return next((kind for kind, terms in GROUPS.items() if any(term in title for term in terms)),
                'price_movement' if any(term in title for term in ('주가', '급등', '상한가', '급락', '상승률')) else 'other')


def _direction(title, issuer=None):
    reported_driver = _reported_driver(title, issuer)
    direction_text = DRIVER_MOVE.sub('', title) if reported_driver else title
    negative = any(term in direction_text for term in ('취소', '감소', '적자', '하락', '하향', '소송', '횡령', '배임', '유출',
                                              '회생', '영업정지', '악화', '해지', '실패', '급감', '철회', '불허',
                                              '미승인', '감익', '손실', '부인', '중단', '불발', '반토막', '쇼크',
                                              '스캔들', '무산', '피해', '↓')) or bool(re.search(
        r'(?:규제|수출통제|제재)\s*(?:강화|확대)|수출\s*(?:금지|제한)', title))
    # A failed order/approval is not simultaneously a positive order/approval.
    positive_text = re.sub(r'(?:수주|계약|승인|체결)\s*(?:실패|해지|취소|불발)|미승인', '', direction_text)
    positive = any(term in positive_text for term in ('증가', '흑자', '성장', '최대', '개선', '상향', '승인', '수주', '체결', '↑')) or bool(
        re.search(r'(?:규제|수출통제|제재)\s*완화', positive_text))
    if reported_driver and not negative:
        return 'neutral'  # Attribution in a report is not independently verified direction.
    return 'mixed' if negative and positive else 'negative' if negative else 'positive' if positive else 'neutral'


def _evidence(raw, observation, now):
    if not isinstance(raw, dict):
        return None
    title = ' '.join(str(raw.get('title') or '').split())[:500]
    url = safe_url(raw.get('url'))
    kind = raw.get('kind')
    if not title or not url or kind not in {'news', 'disclosure'}:
        return None
    if kind == 'news' and (not title_matches(title, observation['name']) or sports_title(title, raw.get('publisher'))):
        return None
    if kind == 'disclosure' and raw.get('verification') != 'issuer_registry_match' and not title_matches(title, observation['name']):
        return None
    observed = stamp(observation['price_observed_at'])
    precision = raw.get('published_precision', 'unknown')
    published = raw.get('published_at')
    received = raw.get('first_received_at')
    timing = 'unknown'
    try:
        receipt = stamp(received) if received else None
        if receipt and receipt > now:
            return None
        if precision == 'timestamp':
            publication = stamp(published)
            if publication > now or now - publication > timedelta(days=7):
                return None
            if receipt and publication > receipt:
                return None
            published = publication.isoformat()
            timing = 'before_observation' if publication <= observed else 'after_observation'
        elif precision == 'date':
            day = date.fromisoformat(published)
            if day > now.date() or (now.date() - day).days > 7:
                return None
            timing = ('before_observation' if day < observed.date() else
                      'after_observation' if day > observed.date() else 'same_day_unknown')
        else:
            precision, published = 'unknown', None
    except (TypeError, ValueError):
        return None
    if raw.get('_revision'):
        timing = 'unknown'
    return {'id': digest(f'{kind}|{url}|{title}|{published}'), 'kind': kind, 'title': title, 'url': url,
            'source': str(raw.get('source') or 'unknown')[:80],
            'publisher': str(raw['publisher'])[:200] if raw.get('publisher') else None,
            'published_at': published, 'published_precision': precision,
            'first_received_at': receipt.isoformat() if receipt else None, 'timing': timing,
            'discovered_after_observation': receipt > observed if receipt else None,
            'category': _category(title, observation['name']), 'direction': _direction(title, observation['name']),
            'verification': str(raw.get('verification') or 'unverified')[:100], 'duplicate_count': 1,
            '_revision': bool(raw.get('_revision'))}


def _title_key(title):
    return re.sub(r'[^\w]', '', normalized_name(title))


def _merge_evidence(existing, incoming, history=None):
    # The first source receipt and original clocks survive all later retries.
    result = deepcopy(existing)
    history = history if history is not None else []
    for candidate in incoming:
        title_key = _title_key(candidate['title'])
        origin = digest(f'{candidate["source"]}|{candidate["url"]}')
        if any(_title_key(old['title']) == title_key and (old['url'] == candidate['url'] or origin in old.get('_origins', []))
               for old in history):
            continue  # A stale aggregate feed must not resurrect a corrected claim.
        match = next((item for item in result if item['kind'] == candidate['kind'] and
                      (item['url'] == candidate['url'] or origin in item.get('_origins', []) or
                       (item['kind'] == 'news' and _title_key(item['title']) == title_key and
                        (item.get('published_at') or '')[:10] == (candidate.get('published_at') or '')[:10]))), None)
        if match and _title_key(match['title']) != title_key:
            history.append(deepcopy(match))
            candidate['_origins'] = [origin]
            result[result.index(match)] = candidate
            continue
        if match:
            origins = match.setdefault('_origins', [])
            if origin not in origins:
                origins.append(origin)
            match['duplicate_count'] = max(1, len(origins))
        else:
            candidate['_origins'] = [origin]
            result.append(candidate)
    return result


def _refresh_row(row):
    # Classification is derived, unlike the sealed observation/source clocks.
    # Recompute old snapshots immediately when interpretation rules change.
    for item in row['evidence']:
        item['category'] = _category(item['title'], row['name'])
        item['direction'] = _direction(item['title'], row['name'])
    stages = row.get('_stages', {})
    row['checks'] = [{'source': name, 'status': stages.get(name, {}).get('status', 'pending'),
                      'checked_at': stages.get(name, {}).get('checked_at'),
                      'count': stages.get(name, {}).get('count', 0)} for name in sources.SOURCE_NAMES]
    material = [item for item in row['evidence'] if
                (item['category'] == 'reported_driver' and item['direction'] == 'neutral') or
                (item['category'] in GROUPS and item['category'] not in {'risk', 'reported_driver'}
                 and item['direction'] == 'positive')]
    before = sorted((item for item in material if item['timing'] == 'before_observation'),
                    key=lambda item: (item['category'] == 'reported_driver' and
                                      (item.get('published_at') or '')[:10] == row['session'],
                                      item.get('published_at') or ''), reverse=True)
    if before:
        row['status'] = 'prior_material'
        row['summary'] = (f'{before[0]["title"]} (보도된 상승 배경)' if before[0]['category'] == 'reported_driver'
                          else f'{before[0]["title"]} 관련 재료 후보')
    elif material:
        row['status'] = 'post_report' if any(item['timing'] == 'after_observation' for item in material) else 'unresolved'
        row['summary'] = ('관측 이후 나온 상승 배경의 사후 보도입니다. 인과관계는 확인되지 않았습니다.'
                          if any(item['category'] == 'reported_driver' and item['timing'] == 'after_observation' for item in material)
                          else '발표 선후 미확인 또는 관측 이후 보도된 재료 후보')
    elif any(item['category'] == 'price_movement' and item['timing'] == 'after_observation' for item in row['evidence']):
        row['status'] = 'post_report'
        row['summary'] = '관측 이후 주가 움직임을 설명한 사후 보도입니다. 상승 원인은 입증되지 않았습니다.'
    else:
        row['status'] = 'unresolved'
        row['summary'] = '급등과 연결할 구체적인 재료는 아직 확인되지 않았습니다.'
    limitations = list(row.get('_base_limitations', []))
    limitations.extend(limit for stage in stages.values() for limit in stage.get('limitations', []))
    limitations.append('causality_unproven')
    if any(item['direction'] in {'negative', 'mixed'} or item['category'] == 'risk' for item in row['evidence']):
        limitations.append('risk_or_opposing_evidence')
        if not material:
            row['summary'] = '위험·반대 재료가 확인되어 상승 이유는 아직 미확인입니다.'
    if any(item['discovered_after_observation'] for item in row['evidence']):
        limitations.append('retrospective_discovery')
    if any(item['published_precision'] == 'date' for item in row['evidence']):
        limitations.append('disclosure_intraday_timing_unknown')
    if any(item.get('_revision') for item in row['evidence']):
        limitations.append('evidence_revision_timing_unknown')
    if any(check['status'] == 'error' for check in row['checks']):
        limitations.append('source_errors')
    if any(stage.get('error_code') == 'issuer_mapping_unavailable' for stage in stages.values()):
        limitations.append('issuer_mapping_unavailable')
    if any(check['status'] in {'error', 'pending'} for check in row['checks']):
        row['status'] = 'source_incomplete'
    row['limitations'] = limitations


def _view(state, now):
    visible = [state['observations'][identifier] for identifier in state.get('_display_ids', [])
               if identifier in state['observations']]
    rows = sorted((row for row in visible if timedelta(0) <= now - stamp(row['price_observed_at']) <= timedelta(hours=72)),
                  key=lambda row: (row['session'], row['first_detected_at'], row['change_pct']), reverse=True)[:20]
    items = []
    for row in rows:
        current = deepcopy(row)
        _refresh_row(current)
        item = {key: current[key] for key in ROW_FIELDS}
        item['evidence'] = [{key: value for key, value in evidence.items() if not key.startswith('_')}
                            for evidence in sorted(item['evidence'], key=lambda e: e.get('first_received_at') or '', reverse=True)[:80]]
        items.append(item)
    operation = deepcopy(state['operation'])
    status = operation['state']
    if operation.get('last_run_at') and now - stamp(operation['last_run_at']) > timedelta(minutes=15):
        status = 'stale'
    return {'schema_version': 1, 'status': status, 'generated_at': state.get('generated_at'),
            'source_as_of': state.get('source_as_of'), 'threshold': dict(THRESHOLD),
            'items': items, 'operation': operation}


def read_view(root=ROOT, *, now=None):
    """Read saved artifacts only: no imports of producers, fetches or file writes."""
    try:
        return _view(_read(Path(root)), clock(now))
    except (OSError, ValueError, KeyError, TypeError):
        return {'schema_version': 1, 'status': 'unavailable', 'generated_at': None, 'source_as_of': None,
                'threshold': dict(THRESHOLD), 'items': [],
                'operation': {'state': 'unavailable', 'last_run_at': None, 'source_status': 'unavailable',
                              'processed': 0, 'pending': 0}}


def run_once(root=ROOT, *, project_root=PROJECT_ROOT, now=None, deadline=None):
    """Process at most five due symbols within an 80-second monotonic deadline."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    current = clock(now)
    deadline = min(time.monotonic() + 80, deadline) if deadline is not None else time.monotonic() + 80
    with FileLock(str(root / 'worker.lock'), timeout=0):
        state = _read(root)
        source = sources.load_market(project_root, current)
        last = state.get('source_as_of')
        if source['status'] in {'fresh', 'historical'} and last:
            if stamp(source['as_of']) < stamp(last):
                source['status'] = 'regressed'
            elif source['as_of'] == last and source['hash'] != state.get('_source_hash'):
                source['status'] = 'source_conflict'
        operation = {'state': 'ready', 'last_run_at': current.isoformat(), 'source_status': source['status'],
                     'processed': 0, 'pending': 0}
        state.update(operation=operation, generated_at=current.isoformat())
        if source['status'] not in {'fresh', 'historical'}:
            operation['state'] = 'partial' if state['observations'] else 'waiting'
            _save(root, state)
            return _view(state, current)
        state.update(source_as_of=source['as_of'], _source_hash=source['hash'])
        session = stamp(source['as_of']).date().isoformat()
        state['_display_ids'] = []
        for candidate in source['rows']:
            identifier = digest(f'{session}|{candidate["symbol"]}|{POLICY}')
            state['_display_ids'].append(identifier)
            if identifier in state['observations']:
                continue
            path = root / 'observations' / f'{identifier}.json'
            if path.is_file():
                row = json.loads(path.read_bytes())
            else:
                row = {'id': identifier, **candidate, 'session': session, 'first_detected_at': current.isoformat(),
                       'price_observed_at': source['as_of'], 'evidence': [], '_stages': {},
                       '_base_limitations': list(source.get('limitations', [])) +
                       (['historical_observation'] if source['status'] == 'historical' else [])}
                _refresh_row(row)
                write_json_atomic(path, row)
            state['observations'][identifier] = row
        _save(root, state)
        provider = sources.EvidenceSources(project_root, now=now)
        candidates = [row for row in state['observations'].values() if row['id'] in state['_display_ids'] and
                      any(_due(row.get('_stages', {}).get(name), current) for name in sources.SOURCE_NAMES)]
        candidates.sort(key=lambda row: (row.get('_last_attempt', ''), -row['change_pct']))
        for row in candidates[:5]:
            if time.monotonic() >= deadline:
                break
            operation['processed'] += 1
            row['_last_attempt'] = current.isoformat()
            for name in sources.SOURCE_NAMES:
                if time.monotonic() >= deadline:
                    break
                if not _due(row['_stages'].get(name), current):
                    continue
                stage = {'status': 'pending', 'checked_at': clock(now).isoformat(), 'count': 0}
                row['_stages'][name] = stage
                _refresh_row(row)
                _save(root, state)
                try:
                    raw = provider.collect(name, row, clock(now), deadline)
                    received = clock(now)
                    evidence = []
                    for value in raw[:100]:
                        if not isinstance(value, dict):
                            continue
                        url = safe_url(value.get('url'))
                        origin = digest(f'{value.get("source") or "unknown"}|{url}')
                        previous = next((item for item in row['evidence'] if item['url'] == url or
                                         origin in item.get('_origins', [])), None)
                        if previous and _title_key(previous['title']) != _title_key(str(value.get('title') or '')):
                            value = {**value, '_revision': True, 'first_received_at': received.isoformat()}
                        item = _evidence(value, row, received)
                        if item:
                            evidence.append(item)
                    row['evidence'] = _merge_evidence(row['evidence'], evidence, row.setdefault('_evidence_history', []))
                    error_code = getattr(raw, 'error_code', None)
                    stage.update(status='error' if error_code else 'ready' if evidence else 'empty', count=len(evidence))
                    stage['limitations'] = getattr(raw, 'limitations', [])
                    if error_code:
                        stage['error_code'] = error_code
                except Exception as exc:
                    # Provider exceptions may include full URLs with credentials.
                    # Only the source and failed stage cross the persistence boundary.
                    code = str(exc) if isinstance(exc, sources.SourceUnavailable) else 'source_failed'
                    stage.update(status='error', count=0, error_code=code if re.fullmatch(r'[a-z0-9_]{1,60}', code) else 'source_failed')
                _refresh_row(row)
                _save(root, state)
        current_rows = [row for row in state['observations'].values() if row['id'] in state['_display_ids']]
        operation['pending'] = sum(any(check['status'] in {'pending', 'error'} for check in row['checks']) for row in current_rows)
        operation['state'] = 'partial' if operation['pending'] else 'ready' if current_rows else 'no_surge'
        _save(root, state)
        return _view(state, clock(now))
