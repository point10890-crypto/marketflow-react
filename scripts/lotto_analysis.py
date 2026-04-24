"""
AI 로또 분석 — 매주 금요일 자동 게시 스크립트
통계 엔진 + 가중치 후보 생성 + Gemini 해석 + Nano Banana 이미지 → 커뮤니티 자동 게시

사용법:
  python scripts/lotto_analysis.py                # 분석 + 게시
  python scripts/lotto_analysis.py --dry-run      # 분석만 (게시 안 함)
"""

import argparse
import json
import math
import os
import random
import sys
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

DATA_FILE = os.path.join(BASE_DIR, 'data', 'lotto_history.json')
UPLOAD_DIR = os.path.join(BASE_DIR, 'data', 'uploads', 'community')
API_URL = "http://localhost:5001"
ADMIN_EMAIL = "point10890@gmail.com"
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
        print(f"[ERROR] {DATA_FILE} not found")
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


def fetch_draw(drw_no: int) -> dict | None:
    """동행복권 API fetch — host/UA 순환 + 세션 priming 재시도.
    성공 시 draw dict, 회차가 아직 없으면 None, 차단/오류 시 LottoFetchError 전파."""
    last_err: str | None = None
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
                    return None  # 아직 추첨 전
                last_err = f'{host} returnValue={rv}'
            except Exception as e:
                last_err = f'{host} {type(e).__name__}: {e}'
                continue
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
            print(f'[WARN] refresh fail #{no}: {e}')
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
        print(f'[DATA] {new_count}개 새 회차 추가 (최신: #{draws[-1]["drwNo"]})')
    if fetch_errors and new_count == 0:
        # 모든 fetch 가 에러로 끝났음 → 상위에서 staleness guard 가 판단
        print(f'[WARN] refresh_history 새 회차 확보 실패: {fetch_errors[0]}')
    return draws


def _expected_latest_draw_date(today: datetime | None = None) -> datetime:
    """오늘 기준 가장 최근에 지나간 '토요일'을 다음 예정 추첨일로 본다.
    토요일이면 오늘. 그 외 요일은 이전 토요일."""
    today = today or datetime.now()
    # weekday: Mon=0 ... Sat=5 Sun=6
    days_since_sat = (today.weekday() - 5) % 7
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
        print(msg)
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
        print("[ERROR] GEMINI_API_KEY not found in .env")
        sys.exit(1)
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

    return json.loads(text)


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
        print(f"[WARN] Image generation failed: {e}")
    return None


def save_image(image_data: bytes) -> str:
    """이미지 저장 후 URL 반환"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.png"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, 'wb') as f:
        f.write(image_data)
    return f"/api/community/uploads/{filename}"


def login() -> str:
    """관리자 로그인"""
    for pw in ['admin1234', 'Admin1234!', 'admin']:
        resp = requests.post(f"{API_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL, "password": pw,
        })
        if resp.status_code == 200:
            return resp.json()['token']
    print(f"[ERROR] Admin login failed for {ADMIN_EMAIL}")
    sys.exit(1)


def create_post(token: str, board: str, title: str, content: str) -> int:
    """게시글 생성"""
    resp = requests.post(
        f"{API_URL}/api/community/boards/{board}/posts",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"title": title, "content": content},
    )
    if resp.status_code not in (200, 201):
        print(f"[ERROR] Post creation failed: {resp.status_code} {resp.text[:200]}")
        sys.exit(1)
    post_id = resp.json()['id']
    print(f"[OK] Post created: id={post_id}")
    return post_id


def pin_notice(token: str, post_id: int):
    """공지 고정"""
    resp = requests.put(
        f"{API_URL}/api/community/posts/{post_id}/notice",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code == 200:
        print(f"[OK] Notice pinned: id={post_id}")
    else:
        print(f"[WARN] Pin failed: {resp.status_code}")


# ═══════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════

def run_lotto_analysis_post(dry_run: bool = False) -> bool:
    """전체 파이프라인 실행"""
    try:
        # 1. 데이터 로드 + 갱신 + 신선도 검증
        print("[1/6] 로또 데이터 로드 중...")
        draws = load_history()
        draws = refresh_history(draws)
        ensure_fresh_history(draws)  # 오래된 데이터로 분석 방지 (지난 추첨 누락 시 중단)
        print(f"[1/6] 총 {len(draws)}회차 데이터 (#{draws[0]['drwNo']} ~ #{draws[-1]['drwNo']})")

        # 2. 통계 계산
        print("[2/6] 통계 분석 중...")
        stats = compute_stats(draws)
        print(f"[2/6] 핫넘버(10회): {stats['hot_10'][:6]}")
        print(f"[2/6] 콜드넘버(10회): {stats['cold_10'][:6]}")

        # 3. 후보 생성
        print("[3/6] AI 후보 생성 중...")
        candidates = generate_candidates(stats, n_sets=4)
        for style, data in candidates.items():
            best = data['sets'][0] if data['sets'] else None
            if best:
                print(f"[3/6] {style}: {best['numbers']} (점수: {best['score']})")

        if dry_run:
            print("\n--- DRY RUN ---")
            print(f"Stats Summary:\n{build_stats_summary(stats)}")
            print(f"\nCandidates:\n{build_candidates_text(candidates)}")
            return True

        # 4. Gemini 글 생성
        print("[4/6] Gemini로 분석 글 작성 중...")
        client = get_gemini_client()
        result = generate_lotto_post(client, stats, candidates)
        title = result['title']
        content = result['content']
        image_prompt = result.get('image_prompt', '')
        print(f"[4/6] 제목: {title}")
        print(f"[4/6] 본문: {len(content)}자")

        # 5. 이미지 생성
        if image_prompt and '{{IMAGE}}' in content:
            print("[5/6] Nano Banana로 이미지 생성 중...")
            image_data = generate_image(client, image_prompt)
            if image_data:
                image_url = save_image(image_data)
                img_tag = f'<img src="{image_url}" alt="AI 로또 분석 일러스트" style="width:100%;max-width:680px;border-radius:12px;margin:16px auto;display:block;" />'
                content = content.replace('{{IMAGE}}', img_tag, 1)
                content = content.replace('{{IMAGE}}', '')
                print(f"[5/6] 이미지 생성 완료: {image_url}")
            else:
                content = content.replace('{{IMAGE}}', '')
                print("[5/6] 이미지 생성 실패 — 텍스트만 게시")
        else:
            content = content.replace('{{IMAGE}}', '')
            print("[5/6] 이미지 플레이스홀더 없음 — 스킵")

        # 6. 게시
        print("[6/6] 관리자 로그인 + 게시...")
        token = login()
        post_id = create_post(token, 'lotto-ai', title, content)
        pin_notice(token, post_id)

        print(f"\n=== 완료 ===")
        print(f"URL: /dashboard/community/post/{post_id}")
        return {
            'post_id': post_id,
            'title': title,
            'candidates': candidates,
        }

    except Exception as e:
        print(f"[ERROR] 로또 분석 실패: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="AI 로또 분석 — 통계 기반 추천 + Gemini 해석 + 자동 게시")
    parser.add_argument('--dry-run', action='store_true', help='분석만 하고 게시하지 않음')
    args = parser.parse_args()
    run_lotto_analysis_post(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
