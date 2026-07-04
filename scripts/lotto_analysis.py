"""
AI 로또 분석 — 매주 금요일 자동 게시 스크립트
통계 엔진 + 가중치 후보 생성 + Gemini 해석 + Nano Banana 이미지 → 커뮤니티 자동 게시

사용법:
  python scripts/lotto_analysis.py                # 분석 + 게시
  python scripts/lotto_analysis.py --dry-run      # 분석만 (게시 안 함)
"""

import argparse
import json
import logging
import math
import os
import random
import sys
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import requests

logger = logging.getLogger('lotto_analysis')
# scheduler 데몬에서 호출되는 경우 부모 logger (`marketflow_scheduler` 또는 root) 에 propagate
# 단독 실행 (`python scripts/lotto_analysis.py`) 시 stdout 으로도 출력되도록 핸들러 추가
if not logger.handlers and not logging.getLogger().handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

DATA_FILE = os.path.join(BASE_DIR, 'data', 'lotto_history.json')
DB_FILE = os.path.join(BASE_DIR, 'data', 'users.db')
LOTTO_BOARD_SLUG = 'lotto-ai'
LOTTO_BOARD_ID = 7  # boards.slug='lotto-ai' 의 id (스키마 변경 시 helper 가 자동 fallback)
UPLOAD_DIR = os.path.join(BASE_DIR, 'data', 'uploads', 'community')
API_URL = os.getenv("MARKETFLOW_API_URL") or os.getenv("COMMUNITY_API_URL") or "http://localhost:5001"
ADMIN_EMAIL = os.getenv("MARKETFLOW_ADMIN_EMAIL") or os.getenv("COMMUNITY_ADMIN_EMAIL") or "point10890@gmail.com"
ADMIN_TOKEN = os.getenv("MARKETFLOW_ADMIN_TOKEN") or os.getenv("COMMUNITY_ADMIN_TOKEN")
ADMIN_PASSWORD = os.getenv("MARKETFLOW_ADMIN_PASSWORD") or os.getenv("COMMUNITY_ADMIN_PASSWORD")
LOTTO_API_HOSTS = [
    'https://www.dhlottery.co.kr',
    'https://dhlottery.co.kr',
]
LOTTO_UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]


class LottoFetchError(RuntimeError):
    """동행복권 fetch 실패 — 분석 중단 + 알림 트리거"""


def _alert_telegram(text: str) -> None:
    """실패 시 개인 텔레그램 봇으로 알림 (silent fail)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE_DIR, '.env'))
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat = os.getenv('TELEGRAM_CHAT_ID')
        if token and chat:
            requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat, 'text': text, 'parse_mode': 'HTML'},
                timeout=5,
            )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# Section A — 데이터 로더 + 자동 갱신
# ═══════════════════════════════════════════════════════════════

def load_history() -> list[dict]:
    """로또 당첨번호 히스토리 로드"""
    if not os.path.exists(DATA_FILE):
        logger.error(f"{DATA_FILE} not found")
        sys.exit(1)
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return sorted(data, key=lambda x: x['drwNo'])


def _parse_draw(data: dict) -> dict:
    return {
        'drwNo': data['drwNo'],
        'drwNoDate': data['drwNoDate'],
        'drwtNo1': data['drwtNo1'], 'drwtNo2': data['drwtNo2'],
        'drwtNo3': data['drwtNo3'], 'drwtNo4': data['drwtNo4'],
        'drwtNo5': data['drwtNo5'], 'drwtNo6': data['drwtNo6'],
        'bnusNo': data['bnusNo'],
    }


def _fetch_draw_from_lottolyzer(drw_no: int) -> dict | None:
    """lottolyzer.com HTML 미러에서 draw 파싱 — dhlottery 차단 시 fallback.

    페이지 한 번 로드로 최근 N회차 모두 캐시 가능하지만, 인터페이스 호환을 위해
    단일 회차 반환. 비싼 호출은 모듈 레벨 캐시로 최소화.
    """
    cached = _lottolyzer_cache_get(drw_no)
    if cached is not None:
        return cached if cached else None
    # 최신 50회 페이지 한 번에 fetch + 모두 캐시
    url = "https://en.lottolyzer.com/history/south-korea/6_45-lotto/page/1/per-page/50/winning-number-view"
    try:
        r = requests.get(url, headers={'User-Agent': LOTTO_UA_POOL[0]}, timeout=15)
        if r.status_code != 200:
            return None
        html = r.text
        # <td>회차</td>...<td class="sum-p1">YYYY-MM-DD</td>...<td class="sum-p1">N1,N2,N3,N4,N5,N6</td>...<td class="sum-p1">bonus</td>
        import re as _re
        pattern = _re.compile(
            r'<td>(\d+)</td>\s*<td[^>]*sum-p1[^>]*>([\d-]+)</td>\s*'
            r'<td[^>]*sum-p1[^>]*>([\d,\s]+?)</td>\s*'
            r'<td[^>]*sum-p1[^>]*>(\d+)\s*</td>',
            _re.DOTALL,
        )
        for m in pattern.finditer(html):
            try:
                d_no = int(m.group(1))
                d_date = m.group(2).strip()
                nums = [int(x.strip()) for x in m.group(3).split(',') if x.strip()]
                bonus = int(m.group(4))
                if len(nums) != 6:
                    continue
                draw = {
                    'drwNo': d_no,
                    'drwNoDate': d_date,
                    'drwtNo1': nums[0], 'drwtNo2': nums[1], 'drwtNo3': nums[2],
                    'drwtNo4': nums[3], 'drwtNo5': nums[4], 'drwtNo6': nums[5],
                    'bnusNo': bonus,
                }
                _lottolyzer_cache_set(d_no, draw)
            except (ValueError, IndexError):
                continue
        cached = _lottolyzer_cache_get(drw_no)
        return cached if cached else None
    except Exception:
        return None


_lottolyzer_cache: dict = {}


def _lottolyzer_cache_get(drw_no: int):
    return _lottolyzer_cache.get(drw_no)


def _lottolyzer_cache_set(drw_no: int, draw: dict):
    _lottolyzer_cache[drw_no] = draw


def fetch_draw(drw_no: int) -> dict | None:
    """Fetch chain: dhlottery (primary) → lottolyzer (fallback).

    dhlottery 가 일반 GET을 차단(2026-04 이후 302→/error.html)하므로
    lottolyzer.com HTML 미러를 fallback으로 사용. 모든 소스 실패 시 LottoFetchError.
    """
    last_err: str | None = None

    # 1) dhlottery 시도 (정상 응답 시 우선)
    for host in LOTTO_API_HOSTS:
        for ua in LOTTO_UA_POOL:
            try:
                s = requests.Session()
                s.headers.update({
                    'User-Agent': ua,
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
                    'Referer': f'{host}/gameResult.do?method=byWin',
                })
                s.get(f'{host}/common.do?method=main', timeout=8)
                r = s.get(f'{host}/common.do?method=getLottoNumber&drwNo={drw_no}', timeout=10)
                ct = (r.headers.get('content-type') or '').lower()
                if 'application/json' not in ct:
                    last_err = f'{host}/{ua[:20]} non-json ({ct})'
                    continue
                data = r.json()
                rv = data.get('returnValue')
                if rv == 'success':
                    return _parse_draw(data)
                if rv == 'fail':
                    # 회차 없음 또는 추첨 전 — fallback 도 시도
                    last_err = f'{host} returnValue=fail'
                    break  # UA 순환 무의미
                last_err = f'{host} returnValue={rv}'
            except Exception as e:
                last_err = f'{host} {type(e).__name__}: {e}'
                continue

    # 2) lottolyzer fallback
    fallback = _fetch_draw_from_lottolyzer(drw_no)
    if fallback is not None:
        return fallback

    # 회차 없음 판정:
    # (a) dhlottery returnValue=fail
    # (b) lottolyzer 캐시가 채워졌고 (1회차 이상 성공) drw_no 가 최대 캐시 회차보다 큼 → 아직 추첨 전
    if last_err and 'returnValue=fail' in last_err:
        return None
    if _lottolyzer_cache:
        max_cached = max(_lottolyzer_cache.keys())
        if drw_no > max_cached:
            return None  # 아직 추첨 전 회차

    raise LottoFetchError(f'fetch_draw({drw_no}) 모든 소스 실패 — last_err={last_err}')


def refresh_history(draws: list[dict]) -> list[dict]:
    """마지막 회차 이후 새 데이터 fetch — 최대 5회 시도. 네트워크 차단 시 LottoFetchError."""
    if not draws:
        return draws
    last_no = draws[-1]['drwNo']
    new_count = 0
    fetch_errors: list[str] = []
    for no in range(last_no + 1, last_no + 6):
        try:
            draw = fetch_draw(no)
        except LottoFetchError as e:
            fetch_errors.append(str(e))
            logger.warning(f'refresh fail #{no}: {e}')
            break
        if draw is None:
            # 아직 추첨 전 → 여기서 중단 (미래 회차 조회 금지)
            break
        draws.append(draw)
        new_count += 1
        time.sleep(0.3)
    if new_count > 0:
        draws.sort(key=lambda x: x['drwNo'])
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(draws, f, ensure_ascii=False, indent=2)
        logger.info(f'[DATA] {new_count}개 새 회차 추가 (최신: #{draws[-1]["drwNo"]})')
    if fetch_errors and new_count == 0:
        # 모든 fetch 가 에러로 끝났음 → 상위에서 staleness guard 가 판단
        logger.warning(f'refresh_history 새 회차 확보 실패: {fetch_errors[0]}')
    return draws


def _expected_latest_draw_date(today: datetime | None = None) -> datetime:
    """오늘 기준 가장 최근에 지나간 '토요일'을 다음 예정 추첨일로 본다.
    토요일이면 오늘. 그 외 요일은 이전 토요일."""
    today = today or datetime.now()
    # weekday: Mon=0 ... Sat=5 Sun=6
    days_since_sat = (today.weekday() - 5) % 7
    # Lotto draws are finalized on Saturday evening. Before that cutoff, the
    # newest reliable history is still the previous Saturday's draw.
    if today.weekday() == 5 and (today.hour, today.minute) < (21, 0):
        days_since_sat = 7
    return (today - timedelta(days=days_since_sat)).replace(hour=0, minute=0, second=0, microsecond=0)


def ensure_fresh_history(draws: list[dict]) -> None:
    """lotto_history.json 신선도 검증 — 최근 토요일 대비 7일 이상 뒤처지면 중단."""
    if not draws:
        raise LottoFetchError('lotto_history.json 비어있음')
    last = draws[-1]
    last_date = datetime.strptime(last['drwNoDate'], '%Y-%m-%d')
    expected = _expected_latest_draw_date()
    lag_days = (expected - last_date).days
    # 일반 실행 (금요일 등) 에서는 아직 이번주 토요일이 안 지났으니 lag 가 <7
    # lag >= 7 이면 지난 추첨 데이터가 최소 한 주 빠진 상태 → 분석 무의미
    if lag_days >= 7:
        msg = (f'[BLOCK] lotto_history 최신 #{last["drwNo"]} ({last["drwNoDate"]}) — '
               f'예상 최신 토요일 {expected.strftime("%Y-%m-%d")} 대비 {lag_days}일 지연')
        logger.error(msg)
        _alert_telegram(
            f'⚠️ <b>AI 로또 분석 중단</b>\n'
            f'lotto_history 최신: #{last["drwNo"]} ({last["drwNoDate"]})\n'
            f'예상 최신: {expected.strftime("%Y-%m-%d")}  (지연 {lag_days}일)\n'
            f'동행복권 API 차단 가능 — 수동 확인 필요'
        )
        raise LottoFetchError(msg)


def get_numbers(draw: dict) -> list[int]:
    """회차 데이터에서 6개 번호 추출"""
    return [draw[f'drwtNo{i}'] for i in range(1, 7)]


# ═══════════════════════════════════════════════════════════════
# Section B — 통계 엔진
# ═══════════════════════════════════════════════════════════════

def compute_stats(draws: list[dict]) -> dict:
    """전체 통계 계산"""
    all_numbers = []
    for d in draws:
        all_numbers.extend(get_numbers(d))

    # 전체 출현 빈도
    freq = Counter(all_numbers)
    for n in range(1, 46):
        freq.setdefault(n, 0)

    # 최근 N회 핫/콜드 계산
    def hot_cold(n_recent: int):
        recent = draws[-n_recent:] if len(draws) >= n_recent else draws
        nums = []
        for d in recent:
            nums.extend(get_numbers(d))
        cnt = Counter(nums)
        for n in range(1, 46):
            cnt.setdefault(n, 0)
        sorted_nums = sorted(cnt.items(), key=lambda x: x[1], reverse=True)
        hot = [n for n, _ in sorted_nums[:10]]
        cold = [n for n, _ in sorted_nums[-10:]]
        return hot, cold, dict(cnt)

    hot_10, cold_10, freq_10 = hot_cold(10)
    hot_30, cold_30, freq_30 = hot_cold(30)

    # 홀짝 비율
    odd_count = sum(1 for n in all_numbers if n % 2 == 1)
    total = len(all_numbers)
    odd_pct = round(odd_count / total * 100, 1) if total else 50
    even_pct = round(100 - odd_pct, 1)

    # 합계 통계
    sums = [sum(get_numbers(d)) for d in draws]
    mean_sum = round(sum(sums) / len(sums), 1) if sums else 0
    variance = sum((s - mean_sum) ** 2 for s in sums) / len(sums) if sums else 0
    std_sum = round(math.sqrt(variance), 1)

    # 구간 분포
    sections = {'1-9': 0, '10-19': 0, '20-29': 0, '30-39': 0, '40-45': 0}
    for n in all_numbers:
        if n <= 9:
            sections['1-9'] += 1
        elif n <= 19:
            sections['10-19'] += 1
        elif n <= 29:
            sections['20-29'] += 1
        elif n <= 39:
            sections['30-39'] += 1
        else:
            sections['40-45'] += 1
    section_pct = {k: round(v / total * 100, 1) for k, v in sections.items()}

    # 연속번호 출현 빈도
    consec_count = 0
    for d in draws:
        nums = sorted(get_numbers(d))
        has_consec = any(nums[i + 1] - nums[i] == 1 for i in range(5))
        if has_consec:
            consec_count += 1
    consec_pct = round(consec_count / len(draws) * 100, 1)

    # 미출현 기간 (각 번호별 최근 몇 회 동안 안 나왔는지)
    gap = {}
    for n in range(1, 46):
        last_seen = 0
        for i, d in enumerate(reversed(draws)):
            if n in get_numbers(d):
                last_seen = i
                break
            last_seen = i + 1
        gap[n] = last_seen

    last_draw = draws[-1]

    return {
        'total_draws': len(draws),
        'last_draw': {
            'drwNo': last_draw['drwNo'],
            'date': last_draw['drwNoDate'],
            'numbers': get_numbers(last_draw),
            'bonus': last_draw['bnusNo'],
        },
        'frequency': dict(sorted(freq.items())),
        'freq_10': freq_10,
        'freq_30': freq_30,
        'hot_10': hot_10,
        'cold_10': cold_10,
        'hot_30': hot_30,
        'cold_30': cold_30,
        'gap': gap,
        'odd_even': {'odd_pct': odd_pct, 'even_pct': even_pct},
        'sum_stats': {'mean': mean_sum, 'stddev': std_sum, 'min': min(sums), 'max': max(sums)},
        'section_dist': section_pct,
        'consecutive_pct': consec_pct,
    }


# ═══════════════════════════════════════════════════════════════
# Section C — 후보 생성 + 스코어링
# ═══════════════════════════════════════════════════════════════

STYLES = {
    '안정형': {'hot_weight': 0.7, 'cold_weight': 0.1, 'sum_range': (110, 175), 'desc': '핫넘버 중심, 안정적 분포'},
    '균형형': {'hot_weight': 0.5, 'cold_weight': 0.2, 'sum_range': (100, 180), 'desc': '핫+콜드 균형'},
    '실험형': {'hot_weight': 0.2, 'cold_weight': 0.5, 'sum_range': (80, 200), 'desc': '콜드넘버 집중, 역발상'},
}


def build_weight_pool(stats: dict, style_cfg: dict) -> dict[int, float]:
    """1~45 각 번호에 가중치 부여"""
    weights = {}
    hot_30 = set(stats['hot_30'])
    cold_30 = set(stats['cold_30'])
    freq = stats['frequency']
    max_freq = max(freq.values()) if freq else 1

    for n in range(1, 46):
        base = freq.get(n, 0) / max_freq
        w = 0.3 + base * 0.4  # 0.3 ~ 0.7 base

        if n in hot_30:
            w += style_cfg['hot_weight']
        if n in cold_30:
            w += style_cfg['cold_weight']

        # 미출현 보너스 (오래 안 나올수록 약간 가중)
        gap = stats['gap'].get(n, 0)
        if gap >= 10:
            w += 0.15
        elif gap >= 5:
            w += 0.05

        weights[n] = max(w, 0.1)

    return weights


def weighted_sample(weights: dict[int, float], k: int = 6) -> list[int]:
    """가중치 기반 비복원 추출"""
    pool = list(weights.keys())
    w_list = [weights[n] for n in pool]
    selected = []
    for _ in range(k):
        total = sum(w_list)
        r = random.uniform(0, total)
        cumulative = 0
        for i, w in enumerate(w_list):
            cumulative += w
            if cumulative >= r:
                selected.append(pool[i])
                pool.pop(i)
                w_list.pop(i)
                break
    return sorted(selected)


def score_set(numbers: list[int], stats: dict) -> float:
    """조합 균형 점수 (0~100)"""
    score = 0.0

    # 1. 합계 범위 (30점)
    s = sum(numbers)
    mean = stats['sum_stats']['mean']
    std = stats['sum_stats']['stddev']
    if mean - std <= s <= mean + std:
        score += 30
    elif mean - 2 * std <= s <= mean + 2 * std:
        score += 15
    else:
        score += 5

    # 2. 홀짝 균형 (20점) — 2:4 ~ 4:2가 이상적
    odd = sum(1 for n in numbers if n % 2 == 1)
    even = 6 - odd
    if 2 <= odd <= 4:
        score += 20
    elif odd in (1, 5):
        score += 10
    else:
        score += 0

    # 3. 구간 분산 (25점) — 3개 이상 구간에 분포
    sections_hit = set()
    for n in numbers:
        if n <= 9: sections_hit.add('1-9')
        elif n <= 19: sections_hit.add('10-19')
        elif n <= 29: sections_hit.add('20-29')
        elif n <= 39: sections_hit.add('30-39')
        else: sections_hit.add('40-45')
    if len(sections_hit) >= 4:
        score += 25
    elif len(sections_hit) == 3:
        score += 15
    else:
        score += 5

    # 4. 연속번호 회피 (15점) — 연속 3개 이상이면 감점
    sorted_nums = sorted(numbers)
    max_consec = 1
    cur_consec = 1
    for i in range(1, 6):
        if sorted_nums[i] - sorted_nums[i - 1] == 1:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 1
    if max_consec <= 2:
        score += 15
    elif max_consec == 3:
        score += 5
    else:
        score += 0

    # 5. 최근 당첨번호 중복 회피 (10점)
    last_nums = set(stats['last_draw']['numbers'])
    overlap = len(set(numbers) & last_nums)
    if overlap <= 1:
        score += 10
    elif overlap == 2:
        score += 5
    else:
        score += 0

    return round(score, 1)


def generate_candidates(stats: dict, n_sets: int = 4) -> dict:
    """성향별 후보 생성"""
    results = {}
    for style_name, style_cfg in STYLES.items():
        weights = build_weight_pool(stats, style_cfg)
        sets = []
        attempts = 0
        while len(sets) < n_sets and attempts < 100:
            candidate = weighted_sample(weights)
            sc = score_set(candidate, stats)
            if sc >= 40:
                sets.append({'numbers': candidate, 'score': sc})
            attempts += 1
        # 점수순 정렬
        sets.sort(key=lambda x: x['score'], reverse=True)
        results[style_name] = {
            'sets': sets,
            'desc': style_cfg['desc'],
        }
    return results


# ═══════════════════════════════════════════════════════════════
# Section D — Gemini 글 생성 + 이미지 + 자동 게시
# ═══════════════════════════════════════════════════════════════

def get_gemini_client():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        logger.error("GEMINI_API_KEY not found in .env")
        raise RuntimeError("GEMINI_API_KEY not found")
    from google import genai
    return genai.Client(api_key=api_key)


def build_stats_summary(stats: dict) -> str:
    """통계 요약 텍스트 생성 (Gemini 프롬프트용)"""
    ld = stats['last_draw']
    lines = [
        f"- 분석 회차: 총 {stats['total_draws']}회",
        f"- 최근 당첨 (제{ld['drwNo']}회, {ld['date']}): {ld['numbers']} + 보너스 {ld['bonus']}",
        f"- 최근 10회 핫넘버: {stats['hot_10'][:6]}",
        f"- 최근 10회 콜드넘버: {stats['cold_10'][:6]}",
        f"- 최근 30회 핫넘버: {stats['hot_30'][:6]}",
        f"- 최근 30회 콜드넘버: {stats['cold_30'][:6]}",
        f"- 홀짝 비율: 홀수 {stats['odd_even']['odd_pct']}% / 짝수 {stats['odd_even']['even_pct']}%",
        f"- 번호 합계: 평균 {stats['sum_stats']['mean']}, 표준편차 {stats['sum_stats']['stddev']}",
        f"- 구간 분포: {stats['section_dist']}",
        f"- 연속번호 출현율: {stats['consecutive_pct']}%",
    ]
    # 미출현 상위 5개
    top_gap = sorted(stats['gap'].items(), key=lambda x: x[1], reverse=True)[:5]
    gap_str = ', '.join(f"{n}번({g}회 미출현)" for n, g in top_gap)
    lines.append(f"- 장기 미출현: {gap_str}")
    return '\n'.join(lines)


def build_candidates_text(candidates: dict) -> str:
    """후보 텍스트 생성"""
    lines = []
    for style_name, data in candidates.items():
        lines.append(f"\n{style_name} ({data['desc']}):")
        for i, s in enumerate(data['sets'], 1):
            nums_str = ', '.join(str(n) for n in s['numbers'])
            lines.append(f"  세트 {i}: {nums_str}  [점수: {s['score']}]")
    return '\n'.join(lines)


def generate_lotto_post_fallback(stats: dict, candidates: dict, reason: str = "") -> dict:
    """Build a deterministic lotto post when the LLM provider is unavailable."""
    from html import escape

    last = stats['last_draw']
    next_drw = last['drwNo'] + 1
    title = f"제{next_drw}회 AI 로또 분석 — 이번 주 추천 번호"

    style_blocks = []
    for style_name, data in candidates.items():
        rows = []
        for idx, item in enumerate(data.get('sets', [])[:4], 1):
            numbers = ', '.join(str(n) for n in item.get('numbers', []))
            score = item.get('score', 0)
            rows.append(
                "<li>"
                f"<strong>{escape(numbers)}</strong>"
                f" <span style=\"color:#64748b;\">({idx}세트 · 점수 {score})</span>"
                "</li>"
            )
        style_blocks.append(
            f"<h3>{escape(style_name)} — {escape(data.get('desc', ''))}</h3>"
            f"<ul>{''.join(rows)}</ul>"
        )

    top_gap = sorted(stats['gap'].items(), key=lambda x: x[1], reverse=True)[:8]
    gap_text = ', '.join(f"{num}번({gap}회 미출현)" for num, gap in top_gap)
    fallback_note = (
        "<p style=\"color:#64748b;\">"
        f"LLM 문장 생성기는 일시적으로 사용할 수 없어 통계 엔진 산출물을 기반으로 자동 게시했습니다."
        f"{' 사유: ' + escape(reason[:180]) if reason else ''}"
        "</p>"
    )

    content = f"""
<p>안녕하세요, MarketFlow AI 로또 분석입니다.</p>
{fallback_note}
<h2>🎯 AI 추천 번호 (제{next_drw}회)</h2>
{''.join(style_blocks)}
<h2>📌 최근 당첨 복기</h2>
<p>최근 회차는 <strong>제{last['drwNo']}회 ({escape(str(last['date']))})</strong>이며,
당첨 번호는 <strong>{', '.join(str(n) for n in last['numbers'])}</strong>,
보너스 번호는 <strong>{last['bonus']}</strong>입니다.</p>
<h2>🔥 핫넘버 / ❄️ 콜드넘버</h2>
<p>최근 10회 핫넘버: <strong>{', '.join(str(n) for n in stats['hot_10'][:6])}</strong></p>
<p>최근 10회 콜드넘버: <strong>{', '.join(str(n) for n in stats['cold_10'][:6])}</strong></p>
<h2>📊 번호 분포 패턴</h2>
<p>홀짝 비율: 홀수 <strong>{stats['odd_even']['odd_pct']}%</strong> /
짝수 <strong>{stats['odd_even']['even_pct']}%</strong></p>
<p>번호 합계 평균: <strong>{stats['sum_stats']['mean']}</strong>,
표준편차: <strong>{stats['sum_stats']['stddev']}</strong></p>
<p>장기 미출현 번호: <strong>{escape(gap_text)}</strong></p>
<h2>⚠️ 면책 고지</h2>
<p><strong>본 분석은 통계 기반 참고용이며 당첨을 보장하지 않습니다. 로또는 완전한 확률 게임으로,
어떤 분석도 당첨을 예측할 수 없습니다. 과도한 구매를 삼가해 주세요.</strong></p>
""".strip()

    return {
        'title': title,
        'content': content,
        'image_prompt': '',
        'fallback': True,
    }


def _parse_llm_json(text: str) -> dict:
    """Parse LLM JSON output even when HTML content includes raw control chars."""
    cleaned = (text or '').strip()
    if cleaned.startswith('```'):
        cleaned = cleaned.split('\n', 1)[1] if '\n' in cleaned else cleaned[3:]
    if cleaned.endswith('```'):
        cleaned = cleaned[:-3]
    if cleaned.startswith('json'):
        cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as first_error:
        try:
            return json.loads(cleaned, strict=False)
        except json.JSONDecodeError:
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start >= 0 and end > start:
                try:
                    return json.loads(cleaned[start:end + 1], strict=False)
                except json.JSONDecodeError:
                    pass
            logger.error("LLM JSON parse failed: %s", first_error)
            raise


def generate_lotto_post(client, stats: dict, candidates: dict) -> dict:
    """Gemini로 분석 글 생성"""
    stats_summary = build_stats_summary(stats)
    candidates_text = build_candidates_text(candidates)
    next_drw = stats['last_draw']['drwNo'] + 1

    prompt = f"""당신은 MarketFlow의 AI 로또 분석 시스템입니다.
아래 한국 로또 6/45 통계 분석 결과를 바탕으로 커뮤니티 'AI 로또 분석' 게시판에 올릴
블로그 스타일의 HTML 글을 작성하세요.

## 이번 회차 정보
{stats_summary}

## AI 추천 번호 세트
{candidates_text}

## 요구사항
1. JSON 형식으로만 반환: {{"title": "제목", "content": "HTML 본문", "image_prompt": "영어 이미지 프롬프트"}}
2. 제목: "제{next_drw}회 AI 로또 분석 — 이번 주 추천 번호" (회차 포함)
3. HTML 본문 구조:
   - <p>인사: "안녕하세요, MarketFlow AI 로또 분석입니다."</p>
   - <h2>📊 지난 회차 복기 (제{stats['last_draw']['drwNo']}회)</h2> — 지난 당첨번호 분석
   - {{{{IMAGE}}}}
   - <h2>🔥 핫넘버 & 🧊 콜드넘버</h2> — 최근 트렌드 분석
   - <h2>📐 번호 분포 패턴</h2> — 홀짝, 구간, 합계 분석
   - <h2>🎯 AI 추천 번호 (제{next_drw}회)</h2> — 각 성향별 추천 세트
   - 추천 번호는 볼드 숫자로: <strong>3, 11, 19, 28, 34, 42</strong> 형식
   - 각 세트마다 성향 이름과 점수, 한 줄 설명
   - <h2>⚠️ 면책 고지</h2>
   - <p><strong>본 분석은 통계 기반 참고용이며 당첨을 보장하지 않습니다. 로또는 완전한 확률 게임으로, 어떤 분석도 당첨을 예측할 수 없습니다. 과도한 구매를 삼가해 주세요.</strong></p>
4. 톤: 친근하고 분석적, 데이터 중심, 재미있게
5. image_prompt: colorful lottery balls floating in the air with sparkles, bright cheerful illustration, no text (영어)
6. 반드시 유효한 JSON만 반환. 다른 텍스트 없이.
"""

    from google.genai import types
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.7),
    )

    text = response.text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
    if text.endswith('```'):
        text = text[:-3]
    if text.startswith('json'):
        text = text[4:]
    text = text.strip()

    return _parse_llm_json(text)


def generate_image(client, prompt: str) -> bytes | None:
    """Nano Banana로 이미지 생성"""
    from google.genai import types
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=prompt + ". No text, no watermark, clean illustration style.",
            config=types.GenerateContentConfig(
                response_modalities=['TEXT', 'IMAGE'],
            ),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data
    except Exception as e:
        logger.warning(f"Image generation failed: {e}")
    return None


def save_image(image_data: bytes) -> str:
    """이미지 저장 후 URL 반환"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, 'wb') as f:
        f.write(image_data)
    return f"/api/community/uploads/{filename}"


def _existing_lotto_post_for_draw(draw_no: int) -> dict | None:
    """Return an existing visible lotto post for the draw, if one already exists."""
    if not os.path.exists(DB_FILE):
        return None
    try:
        import sqlite3
        with sqlite3.connect(DB_FILE, timeout=5) as con:
            cur = con.cursor()
            cur.execute("PRAGMA table_info(posts)")
            post_columns = {row[1] for row in cur.fetchall()}
            hidden_clause = "AND COALESCE(p.is_hidden, 0) = 0" if 'is_hidden' in post_columns else ""
            cur.execute(
                f"""
                SELECT p.id, p.title
                FROM posts p
                JOIN boards b ON p.board_id = b.id
                WHERE b.slug = ?
                  {hidden_clause}
                  AND p.title LIKE ?
                ORDER BY p.created_at DESC
                LIMIT 1
                """,
                (LOTTO_BOARD_SLUG, f"%{draw_no}%"),
            )
            row = cur.fetchone()
            if row:
                return {'post_id': row[0], 'title': row[1]}
    except Exception as e:
        logger.warning("Lotto duplicate guard failed: %s: %s", type(e).__name__, e)
    return None


def _local_admin_token() -> str | None:
    """관리자 토큰을 sqlite3 + HMAC-SHA256 으로 직접 발급 (경량화).

    v4 변경 — 과거에는 `from app import create_app; create_app()` 으로 Flask 인스턴스를
    매번 새로 만들어 background worker (Pro/AI Brain expiry, screener, alpha scanner,
    MCP auto-runner 등) 가 데몬 안에서 폭증하던 결함 ⑤ 를 일으켰음. 이제는 단일
    sqlite3 SELECT + 1개 HMAC 계산으로 동일 효과 달성, worker spawn 0건.

    Token 포맷은 `app/auth/decorators.py:generate_token()` 과 비트-동일.
    SECRET_KEY 는 같은 env var 를 읽으므로 Flask 측의 validate_token 이 그대로 통과.
    """
    # Kill-switch — runtime 평가 (env 토글이 daemon 재시작 없이 즉시 반영되도록).
    if os.getenv("MARKETFLOW_ALLOW_LOCAL_ADMIN_TOKEN", "1").strip().lower() in ("0", "false", "no", "off"):
        logger.warning("Local admin token: disabled via MARKETFLOW_ALLOW_LOCAL_ADMIN_TOKEN=0")
        return None

    import sqlite3
    import hmac
    import hashlib

    if not os.path.exists(DB_FILE):
        logger.warning("Local admin token: users.db not found at %s", DB_FILE)
        return None

    # 1) admin user_id 조회 — ADMIN_EMAIL 우선, 없으면 첫 admin role
    # users 테이블은 `role` 컬럼 사용 ('admin' / 'user' 등). `is_admin` 은 User 모델의 property 이므로 SQL 에서 직접 못 씀.
    try:
        with sqlite3.connect(DB_FILE, timeout=5) as con:
            cur = con.cursor()
            cur.execute(
                "SELECT id FROM users WHERE email = ? AND role = 'admin' LIMIT 1",
                (ADMIN_EMAIL,)
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    "SELECT id FROM users WHERE role = 'admin' ORDER BY id ASC LIMIT 1"
                )
                row = cur.fetchone()
            if not row:
                logger.warning("Local admin token: no admin user found in DB")
                return None
            user_id = row[0]
    except Exception as e:
        logger.warning(f"Local admin token: DB query failed: {type(e).__name__}: {e}")
        return None

    # 2) Token 생성 — Flask 의 generate_token 과 동일 알고리즘
    secret = os.getenv("SECRET_KEY", "marketflow-secret-key-change-in-production")
    expiry = int(time.time()) + 86400 * 30  # TOKEN_EXPIRY = 30 days
    payload = f"{user_id}:{expiry}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    token = f"{payload}:{sig}"

    logger.debug(f"Local admin token issued for user_id={user_id}")
    return token


def login() -> str:
    """관리자 로그인 — 3단 fallback.

    1) ADMIN_TOKEN env (static, 운영 비추) → 즉시 반환
    2) ADMIN_PASSWORD env → Flask HTTP /api/auth/login → JWT 토큰
    3) _local_admin_token() → sqlite3 + HMAC 직접 발급 (경량, 기본 경로)
    """
    # 1) Static token from env (모듈 로드 시 캡쳐 — daemon 재시작으로 갱신)
    if ADMIN_TOKEN:
        logger.debug("Admin auth: using static token from env")
        return ADMIN_TOKEN

    # 2) HTTP password login (only if password is set)
    if ADMIN_PASSWORD:
        password = ADMIN_PASSWORD
        try:
            resp = requests.post(
                f"{API_URL}/api/auth/login",
                json={"email": ADMIN_EMAIL, "password": password},
                timeout=15,
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Admin login HTTP request failed: {e}") from e
        if resp.status_code == 200:
            logger.debug("Admin auth: HTTP login succeeded")
            return resp.json()['token']
        raise RuntimeError(
            f"Admin login failed for {ADMIN_EMAIL}: {resp.status_code} {resp.text[:200]}"
        )

    # 3) Local admin token (경량화 — create_app 호출 없음)
    local_token = _local_admin_token()
    if local_token:
        logger.debug("Admin auth: local token via sqlite+HMAC")
        return local_token

    raise RuntimeError(
        "Admin auth 실패: ADMIN_TOKEN/ADMIN_PASSWORD 미설정 + local admin token 발급 실패 "
        "(DB 또는 admin user 누락 추정)"
    )


def create_post(token: str, board: str, title: str, content: str) -> int:
    """게시글 생성"""
    resp = requests.post(
        f"{API_URL}/api/community/boards/{board}/posts",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"title": title, "content": content},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Post creation failed: {resp.status_code} {resp.text[:200]}")
        raise RuntimeError(f"Post creation failed: {resp.status_code}")
    post_id = resp.json()['id']
    logger.info(f"Post created: id={post_id}")
    return post_id


def pin_notice(token: str, post_id: int):
    """공지 고정"""
    resp = requests.put(
        f"{API_URL}/api/community/posts/{post_id}/notice",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_notice": True},
        timeout=15,
    )
    if resp.status_code == 200:
        logger.info(f"Notice pinned: id={post_id}")
    else:
        logger.warning(f"Pin failed: {resp.status_code}")


# ═══════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════

def run_lotto_analysis_post(dry_run: bool = False) -> bool:
    """전체 파이프라인 실행"""
    try:
        # 1. 데이터 로드 + 갱신 + 신선도 검증
        logger.info("[1/6] 로또 데이터 로드 중...")
        draws = load_history()
        draws = refresh_history(draws)
        ensure_fresh_history(draws)  # 오래된 데이터로 분석 방지 (지난 추첨 누락 시 중단)
        logger.info(f"[1/6] 총 {len(draws)}회차 데이터 (#{draws[0]['drwNo']} ~ #{draws[-1]['drwNo']})")

        # 2. 통계 계산
        logger.info("[2/6] 통계 분석 중...")
        stats = compute_stats(draws)
        if not dry_run:
            next_drw = stats['last_draw']['drwNo'] + 1
            existing = _existing_lotto_post_for_draw(next_drw)
            if existing:
                logger.info(
                    "[GUARD] Lotto draw #%s already posted as id=%s; skipping duplicate post.",
                    next_drw,
                    existing.get('post_id'),
                )
                return {
                    'post_id': existing.get('post_id'),
                    'title': existing.get('title', f'Lotto draw #{next_drw}'),
                    'candidates': {},
                    'skipped': True,
                }
        logger.info(f"[2/6] 핫넘버(10회): {stats['hot_10'][:6]}")
        logger.info(f"[2/6] 콜드넘버(10회): {stats['cold_10'][:6]}")

        # 3. 후보 생성
        logger.info("[3/6] AI 후보 생성 중...")
        candidates = generate_candidates(stats, n_sets=4)
        for style, data in candidates.items():
            best = data['sets'][0] if data['sets'] else None
            if best:
                logger.info(f"[3/6] {style}: {best['numbers']} (점수: {best['score']})")

        if dry_run:
            logger.info("--- DRY RUN ---")
            logger.info("Stats Summary:\n%s", build_stats_summary(stats))
            logger.info("Candidates:\n%s", build_candidates_text(candidates))
            return True

        # 4. Gemini 글 생성
        logger.info("[4/6] Gemini로 분석 글 작성 중...")
        client = None
        try:
            client = get_gemini_client()
            result = generate_lotto_post(client, stats, candidates)
        except Exception as e:
            logger.warning(
                "[4/6] LLM post generation failed; using deterministic fallback: %s: %s",
                type(e).__name__,
                e,
            )
            result = generate_lotto_post_fallback(stats, candidates, reason=f"{type(e).__name__}: {e}")
        title = result['title']
        content = result['content']
        image_prompt = result.get('image_prompt', '')
        logger.info(f"[4/6] 제목: {title}")
        logger.info(f"[4/6] 본문: {len(content)}자")

        # 5. 이미지 생성
        if client and image_prompt and '{{IMAGE}}' in content:
            logger.info("[5/6] Nano Banana로 이미지 생성 중...")
            image_data = generate_image(client, image_prompt)
            if image_data:
                image_url = save_image(image_data)
                img_tag = f'<img src="{image_url}" alt="AI 로또 분석 일러스트" style="width:100%;max-width:680px;border-radius:12px;margin:16px auto;display:block;" />'
                content = content.replace('{{IMAGE}}', img_tag, 1)
                content = content.replace('{{IMAGE}}', '')
                logger.info(f"[5/6] 이미지 생성 완료: {image_url}")
            else:
                content = content.replace('{{IMAGE}}', '')
                logger.warning("[5/6] 이미지 생성 실패 — 텍스트만 게시")
        else:
            content = content.replace('{{IMAGE}}', '')
            logger.info("[5/6] 이미지 플레이스홀더 없음 — 스킵")

        # 6. 게시
        logger.info("[6/6] 관리자 로그인 + 게시...")
        token = login()
        post_id = create_post(token, 'lotto-ai', title, content)
        pin_notice(token, post_id)

        logger.info("=== 완료 ===")
        logger.info(f"URL: /dashboard/community/post/{post_id}")
        return {
            'post_id': post_id,
            'title': title,
            'candidates': candidates,
        }

    except Exception:
        logger.exception("로또 분석 실패")  # exc_info=True 자동 포함
        return False


def main():
    parser = argparse.ArgumentParser(description="AI 로또 분석 — 통계 기반 추천 + Gemini 해석 + 자동 게시")
    parser.add_argument('--dry-run', action='store_true', help='분석만 하고 게시하지 않음')
    args = parser.parse_args()
    run_lotto_analysis_post(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
