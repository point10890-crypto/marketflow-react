"""
Gemini Vision 한국 주식 차트 분석기
코스피/코스닥 상위 100개 종목의 캔들차트를 자동 생성 → Gemini/OpenAI Vision API로 기술적 분석
"""

import os
import sys
import re
import json
import asyncio
import base64
import logging
from concurrent.futures import ThreadPoolExecutor

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import mplfinance as mpf
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ── 로깅 ──
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ── 환경변수 ──
load_dotenv()
API_KEY = os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
# Vision 폴백 모델. 하드코딩된 gpt-4o-mini 는 이 계정에 접근 권한이 없어
# (403 model_not_found) 폴백이 항상 실패했다. 계정에서 쓸 수 있는 모델로 두고
# 환경변수로 교체 가능하게 한다.
OPENAI_VISION_MODEL = os.getenv('KR_CHART_OPENAI_MODEL') or os.getenv('OPENAI_MODEL') or 'gpt-5.5'

if not API_KEY and not OPENAI_API_KEY:
    logger.error("GEMINI_API_KEY, OPENAI_API_KEY 둘 다 .env에 없습니다.")
    sys.exit(1)

# ── 한글 폰트 ──
if sys.platform == 'win32':
    font_path = 'C:/Windows/Fonts/malgun.ttf'
elif sys.platform == 'darwin':
    font_path = '/System/Library/Fonts/AppleSDGothicNeo.ttc'
else:
    # Linux: Noto Sans CJK 우선, 없으면 나눔고딕
    _linux_fonts = [
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
    ]
    font_path = next((f for f in _linux_fonts if os.path.exists(f)), None)

if font_path and os.path.exists(font_path):
    fm.fontManager.addfont(font_path)
    prop = fm.FontProperties(fname=font_path)
    plt.rcParams['font.family'] = prop.get_name()
plt.rcParams['axes.unicode_minus'] = False

# ── 출력 디렉토리 ──
CHARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'charts_kr')
os.makedirs(CHARTS_DIR, exist_ok=True)

# ── 종목 리스트 (코스피 상위 75 + 코스닥 상위 25) ──
# 2026-08-15 KRX 상장 기준으로 재생성. 이전 목록은 상장폐지된
# 쌍용C&E(003410) 를 매 회차 조회 실패시키고 ETF(KODEX 200) 까지 섞여 있었다.
# 갱신: scripts/refresh_kr_chart_universe.py --write
STOCKS = {
    # 코스피 (시총 상위 75)
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "402340.KS": "SK스퀘어",
    "009150.KS": "삼성전기", "005380.KS": "현대차", "373220.KS": "LG에너지솔루션",
    "207940.KS": "삼성바이오로직스", "032830.KS": "삼성생명", "028260.KS": "삼성물산",
    "012450.KS": "한화에어로스페이스", "105560.KS": "KB금융", "000270.KS": "기아",
    "329180.KS": "HD현대중공업", "034020.KS": "두산에너빌리티", "055550.KS": "신한지주",
    "012330.KS": "현대모비스", "068270.KS": "셀트리온", "034730.KS": "SK",
    "006400.KS": "삼성SDI", "086790.KS": "하나금융지주", "035420.KS": "NAVER",
    "066570.KS": "LG전자", "010120.KS": "LS ELECTRIC", "042660.KS": "한화오션",
    "267260.KS": "HD현대일렉트릭", "298040.KS": "효성중공업", "000810.KS": "삼성화재",
    "009540.KS": "HD한국조선해양", "005490.KS": "POSCO홀딩스", "010130.KS": "고려아연",
    "316140.KS": "우리금융지주", "042700.KS": "한미반도체", "096770.KS": "SK이노베이션",
    "017670.KS": "SK텔레콤", "015760.KS": "한국전력", "006800.KS": "미래에셋증권",
    "000150.KS": "두산", "011200.KS": "HMM", "051910.KS": "LG화학",
    "010140.KS": "삼성중공업", "138040.KS": "메리츠금융지주", "018260.KS": "삼성에스디에스",
    "267250.KS": "HD현대", "033780.KS": "KT&G", "003550.KS": "LG",
    "079550.KS": "LIG디펜스앤에어로스페이스", "035720.KS": "카카오", "010950.KS": "S-Oil",
    "024110.KS": "기업은행", "064350.KS": "현대로템", "086280.KS": "현대글로비스",
    "011070.KS": "LG이노텍", "272210.KS": "한화시스템", "003670.KS": "포스코퓨처엠",
    "278470.KS": "에이피알", "047810.KS": "한국항공우주", "030200.KS": "KT",
    "307950.KS": "현대오토에버", "000720.KS": "현대건설", "005830.KS": "DB손해보험",
    "071050.KS": "한국금융지주", "259960.KS": "크래프톤", "078930.KS": "GS",
    "005940.KS": "NH투자증권", "323410.KS": "카카오뱅크", "006260.KS": "LS",
    "028050.KS": "삼성E&A", "003490.KS": "대한항공", "003230.KS": "삼양식품",
    "047050.KS": "포스코인터내셔널", "161390.KS": "한국타이어앤테크놀로지", "443060.KS": "HD현대마린솔루션",
    "016360.KS": "삼성증권", "180640.KS": "한진칼", "009830.KS": "한화솔루션",
    # 코스닥 (시총 상위 25)
    "196170.KQ": "알테오젠", "086520.KQ": "에코프로", "247540.KQ": "에코프로비엠",
    "277810.KQ": "레인보우로보틱스", "036930.KQ": "주성엔지니어링", "028300.KQ": "HLB",
    "240810.KQ": "원익IPS", "058470.KQ": "리노공업", "039030.KQ": "이오테크닉스",
    "298380.KQ": "에이비엘바이오", "087010.KQ": "펩트론", "000250.KQ": "삼천당제약",
    "141080.KQ": "리가켐바이오", "214450.KQ": "파마리서치", "108490.KQ": "로보티즈",
    "222800.KQ": "심텍", "319660.KQ": "피에스케이", "095340.KQ": "ISC",
    "214370.KQ": "케어젠", "403870.KQ": "HPSP", "310210.KQ": "보로노이",
    "440110.KQ": "파두", "145020.KQ": "휴젤", "319400.KQ": "현대무벡스",
    "084370.KQ": "유진테크",
}

# ── Gemini 분석 프롬프트 ──
ANALYSIS_PROMPT = """당신은 25년 경력의 기술적 분석 전문가입니다.

이 {name}({ticker}) 한국 주식 차트를 분석해주세요.

다음 항목을 확인하세요:
1. 이동평균선(20/50/200) 배열 상태
2. RSI가 30 이하(과매도) 또는 70 이상(과매수)인지
3. 거래량이 최근 20일 평균 대비 증감
4. 볼린저밴드 상/하단 터치 여부

반드시 아래 JSON 형식으로만 답변하세요:
{{
  "signal": "BUY 또는 HOLD 또는 SELL",
  "confidence": 0~100 사이의 정수,
  "reasons": ["이유1", "이유2", "이유3"],
  "ma_status": "정배열 또는 역배열 또는 혼조",
  "rsi_zone": "과매도 또는 중립 또는 과매수",
  "volume_trend": "증가 또는 감소 또는 보합"
}}"""


# ════════════════════════════════════════════════
# Step 1: 차트 생성
# ════════════════════════════════════════════════

def render_chart(df: 'pd.DataFrame', ticker: str, name: str) -> str | None:
    """OHLCV 프레임으로 캔들차트 PNG 생성 → 파일 경로 반환.

    가격 출처와 렌더링을 분리해 둔다. yfinance 가 스로틀링에 걸리면 로컬
    daily_prices.csv 같은 다른 소스로 같은 차트를 그릴 수 있어야 한다
    (scripts/screen_buy_candidates.py). 차트 모양이 같아야 Vision 판정도
    서로 비교 가능하다.

    df: DatetimeIndex + Open/High/Low/Close/Volume 컬럼.
    """
    try:
        if df is None or df.empty or len(df) < 20:
            logger.warning(f"[SKIP] {name}({ticker}): 데이터 부족 ({0 if df is None else len(df)}행)")
            return None

        # 이동평균선 addplot
        ap = []
        for period, color in [(20, 'cyan'), (50, 'orange'), (200, 'red')]:
            ma = df['Close'].rolling(period).mean()
            if ma.notna().sum() > 0:
                ap.append(mpf.make_addplot(ma, color=color, width=0.8))

        # 파일명
        code = ticker.split('.')[0]
        safe_name = name.replace('/', '_').replace(' ', '_')
        filepath = os.path.join(CHARTS_DIR, f"{code}_{safe_name}.png")

        # mplfinance 차트 생성
        mc = mpf.make_marketcolors(up='#ef5350', down='#26a69a', edge='inherit',
                                   wick='inherit', volume='in', ohlc='i')
        # 한글 폰트를 rc에 직접 주입 (mplfinance는 자체 rcParams 사용)
        font_name = plt.rcParams.get('font.family', ['sans-serif'])
        if isinstance(font_name, list):
            font_name = font_name[0] if font_name else 'sans-serif'
        s = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='charles',
                               gridcolor='#333333', facecolor='#1a1a2e',
                               figcolor='#1a1a2e', rc={'font.family': font_name,
                                                        'axes.unicode_minus': False,
                                                        'axes.labelcolor': 'white',
                                                        'xtick.color': 'white',
                                                        'ytick.color': 'white'})

        mpf.plot(df, type='candle', style=s, volume=True, addplot=ap if ap else None,
                 title=f'\n{name} ({ticker})', figratio=(16, 9), figscale=1.2,
                 savefig=dict(fname=filepath, dpi=150, facecolor='#1a1a2e',
                              bbox_inches='tight'))
        plt.close('all')

        return filepath
    except Exception as e:
        logger.error(f"[CHART ERROR] {name}({ticker}): {e}")
        plt.close('all')
        return None


def generate_chart(ticker: str, name: str) -> str | None:
    """yfinance 1년치를 받아 캔들차트 생성."""
    try:
        df = yf.download(ticker, period='1y', progress=False)
        if df is None or df.empty:
            logger.warning(f"[SKIP] {name}({ticker}): 가격 데이터 없음")
            return None

        # MultiIndex 컬럼 처리
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel('Ticker', axis=1)

        # 인덱스 정리 (timezone 제거)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        return render_chart(df, ticker, name)
    except Exception as e:
        logger.error(f"[CHART ERROR] {name}({ticker}): {e}")
        plt.close('all')
        return None


# ════════════════════════════════════════════════
# Step 2: Gemini Vision 분석
# ════════════════════════════════════════════════

_executor = ThreadPoolExecutor(max_workers=10)


def _extract_json(text: str) -> dict | None:
    """Gemini 응답에서 JSON 추출 (마크다운 펜스, 잘림 대응)"""
    text = text.strip()

    # 마크다운 코드 펜스 제거
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    # 1차: 직접 파싱
    try:
        data = json.loads(text)
        return data[0] if isinstance(data, list) and data else data
    except json.JSONDecodeError:
        pass

    # 2차: 잘린 JSON 복구 — 미닫힌 문자열/배열/객체 닫기
    if '{' in text:
        candidate = text[text.index('{'):]

        # 미닫힌 문자열 닫기 (홀수 개의 이스케이프 안 된 따옴표)
        in_string = False
        last_char = ''
        for ch in candidate:
            if ch == '"' and last_char != '\\':
                in_string = not in_string
            last_char = ch
        if in_string:
            candidate += '"'

        # 마지막 불완전 요소 제거 후 배열/객체 닫기
        # trailing comma 제거
        candidate = re.sub(r',\s*$', '', candidate)

        # 미닫힌 배열 닫기
        open_brackets = candidate.count('[') - candidate.count(']')
        if open_brackets > 0:
            candidate += ']' * open_brackets

        # 미닫힌 객체 닫기
        open_braces = candidate.count('{') - candidate.count('}')
        if open_braces > 0:
            candidate += '}' * open_braces

        try:
            data = json.loads(candidate)
            return data
        except json.JSONDecodeError:
            pass

    return None


def _call_gemini(client: genai.Client, ticker: str, name: str, image_path: str) -> dict | None:
    """동기 Gemini API 호출"""
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()

        prompt = ANALYSIS_PROMPT.format(name=name, ticker=ticker)

        response = client.models.generate_content(
            model=MODEL,
            contents=[
                types.Part.from_bytes(data=image_data, mime_type='image/png'),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
                max_output_tokens=4096,
            ),
        )

        text = response.text.strip()
        data = _extract_json(text)

        if data is None:
            logger.error(f"[PARSE FAIL] {name}({ticker}): 응답 파싱 실패 — {text[:200]}")

        return data
    except Exception as e:
        logger.error(f"[GEMINI ERROR] {name}({ticker}): {e}")
        return None


def _openai_chat_with_token_limit(client, *, model: str, messages: list,
                                  max_output_tokens: int, **kwargs):
    """토큰 한도 파라미터명을 모델에 맞춰 협상하는 chat 호출.

    구형 모델은 `max_tokens`, 신형(gpt-5 계열)은 `max_completion_tokens` 만
    받는다. 모델명으로 분기하면 모델을 바꿀 때마다 다시 깨지므로 거부 응답을
    보고 재시도한다 (engine/llm_analyzer.py 의 동일 패턴).
    """
    try:
        return client.chat.completions.create(
            model=model, messages=messages, max_tokens=max_output_tokens, **kwargs
        )
    except Exception as exc:
        text = str(exc)
        if 'max_completion_tokens' not in text:
            raise
        return client.chat.completions.create(
            model=model, messages=messages,
            max_completion_tokens=max_output_tokens, **kwargs
        )


def _call_openai_vision(ticker: str, name: str, image_path: str) -> dict | None:
    """OpenAI Vision 폴백 — Gemini 실패 시 차트 분석"""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        with open(image_path, 'rb') as f:
            image_data = f.read()
        b64_image = base64.b64encode(image_data).decode('utf-8')

        prompt = ANALYSIS_PROMPT.format(name=name, ticker=ticker)

        response = _openai_chat_with_token_limit(
            client,
            model=OPENAI_VISION_MODEL,
            messages=[
                {"role": "system", "content": "You are a professional technical chart analyst. Respond only in valid JSON."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}", "detail": "high"}},
                ]},
            ],
            max_output_tokens=4096,
        )

        text = response.choices[0].message.content.strip()
        data = _extract_json(text)

        if data is None:
            logger.error(f"[OPENAI PARSE FAIL] {name}({ticker}): 응답 파싱 실패 — {text[:200]}")

        return data
    except Exception as e:
        logger.error(f"[OPENAI ERROR] {name}({ticker}): {e}")
        return None


# ── Gemini 세션 내 가용 상태 추적 ──
# 2026-08-15: 예전에는 단 1건이라도 실패하면 곧바로 Gemini 를 껐다. 삼성전기
# 한 종목의 JSON 파싱 실패가 래치를 트립시켜 나머지 62종목이 전부 (권한 없는)
# OpenAI 폴백으로 넘어가 통째로 드롭됐다 — 100종목 중 37종목만 분석된 원인.
# 이제는 "연속" 실패가 임계치를 넘을 때만(=키 소진·인증 실패 같은 지속적 장애)
# 끈다. 간헐적 실패는 종목 단위 재시도로 흡수한다.
GEMINI_FAILURE_THRESHOLD = max(1, int(os.getenv('KR_CHART_GEMINI_FAILURE_THRESHOLD', '8')))
GEMINI_ITEM_RETRIES = max(0, int(os.getenv('KR_CHART_GEMINI_RETRIES', '1')))

_gemini_consecutive_failures = 0
_gemini_disabled = False


def reset_vision_health() -> None:
    """세션 상태 초기화 (테스트/재실행용)."""
    global _gemini_consecutive_failures, _gemini_disabled
    _gemini_consecutive_failures = 0
    _gemini_disabled = False


def gemini_is_available() -> bool:
    return not _gemini_disabled


def _record_gemini_outcome(success: bool, ticker: str, name: str) -> None:
    global _gemini_consecutive_failures, _gemini_disabled
    if success:
        _gemini_consecutive_failures = 0
        return
    _gemini_consecutive_failures += 1
    if _gemini_consecutive_failures >= GEMINI_FAILURE_THRESHOLD and not _gemini_disabled:
        _gemini_disabled = True
        logger.warning(
            f"[FALLBACK] Gemini 연속 {_gemini_consecutive_failures}종목 실패 "
            f"→ 남은 종목은 OpenAI Vision 으로 전환 (마지막: {name}({ticker}))"
        )


async def analyze_chart(client: genai.Client, ticker: str, name: str,
                        image_path: str, semaphore: asyncio.Semaphore) -> dict | None:
    """비동기 래핑: Gemini Vision → OpenAI Vision 폴백"""
    async with semaphore:
        loop = asyncio.get_event_loop()
        result = None

        # Gemini 시도 (지속적 장애로 꺼진 경우에만 스킵)
        if gemini_is_available() and API_KEY:
            for attempt in range(GEMINI_ITEM_RETRIES + 1):
                result = await loop.run_in_executor(
                    _executor, _call_gemini, client, ticker, name, image_path)
                if result is not None:
                    break
                if attempt < GEMINI_ITEM_RETRIES:
                    logger.info(f"  ↻ Gemini 재시도 {attempt + 1}/{GEMINI_ITEM_RETRIES}: {name}({ticker})")
            _record_gemini_outcome(result is not None, ticker, name)

        # OpenAI Vision 폴백
        if result is None and OPENAI_API_KEY:
            result = await loop.run_in_executor(_executor, _call_openai_vision, ticker, name, image_path)

        if result:
            market = '코스피' if ticker.endswith('.KS') else '코스닥'
            code = ticker.split('.')[0]
            result['종목코드'] = code
            result['종목명'] = name
            result['시장'] = market
            logger.info(f"  ✓ {name} → {result.get('signal', '?')} (confidence: {result.get('confidence', '?')})")
        return result


# ════════════════════════════════════════════════
# Step 3: 결과 종합
# ════════════════════════════════════════════════

def summarize_results(results: list[dict]) -> pd.DataFrame:
    """분석 결과를 DataFrame으로 정리 + CSV 저장"""
    records = []
    for r in results:
        if not r:
            continue
        records.append({
            '종목코드': r.get('종목코드', ''),
            '종목명': r.get('종목명', ''),
            '시장': r.get('시장', ''),
            'signal': r.get('signal', ''),
            'confidence': r.get('confidence', 0),
            'ma_status': r.get('ma_status', ''),
            'rsi_zone': r.get('rsi_zone', ''),
            'volume_trend': r.get('volume_trend', ''),
            'reasons': ' | '.join(r.get('reasons', [])) if isinstance(r.get('reasons'), list) else str(r.get('reasons', '')),
        })

    df = pd.DataFrame(records)
    if df.empty:
        logger.warning("분석 결과가 없습니다.")
        return df

    df = df.sort_values('confidence', ascending=False).reset_index(drop=True)

    # 통계 출력
    print("\n" + "=" * 60)
    print("📊 분석 결과 요약")
    print("=" * 60)

    counts = df['signal'].value_counts()
    for signal in ['BUY', 'HOLD', 'SELL']:
        cnt = counts.get(signal, 0)
        emoji = '🟢' if signal == 'BUY' else '🟡' if signal == 'HOLD' else '🔴'
        print(f"  {emoji} {signal}: {cnt}개")

    buy_df = df[df['signal'] == 'BUY']
    if not buy_df.empty:
        print(f"\n{'─' * 60}")
        print("🟢 BUY 시그널 종목 상세:")
        print(f"{'─' * 60}")
        for _, row in buy_df.iterrows():
            print(f"  {row['종목명']:12s} ({row['종목코드']}) {row['시장']:4s} | "
                  f"conf={row['confidence']:3d} | MA:{row['ma_status']} | "
                  f"RSI:{row['rsi_zone']} | Vol:{row['volume_trend']}")

    # CSV 저장
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gemini_chart_analysis_kr.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n💾 결과 저장: {csv_path}")
    print(f"   총 {len(df)}개 종목 분석 완료\n")

    return df


# ════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════

async def main():
    print("=" * 60)
    print("🔍 Gemini Vision 한국 주식 차트 분석기")
    print(f"   모델: {MODEL}")
    print(f"   종목: {len(STOCKS)}개 (코스피+코스닥)")
    print("=" * 60)

    # ── Step 1: 차트 생성 ──
    print(f"\n📈 Step 1: 캔들차트 생성 중... ({len(STOCKS)}개)")
    chart_map: dict[str, str] = {}  # ticker → filepath
    for i, (ticker, name) in enumerate(STOCKS.items(), 1):
        print(f"  [{i:3d}/{len(STOCKS)}] {name}({ticker})...", end=' ')
        filepath = generate_chart(ticker, name)
        if filepath:
            chart_map[ticker] = filepath
            print("✓")
        else:
            print("✗ (스킵)")

    print(f"\n  → 차트 생성 완료: {len(chart_map)}/{len(STOCKS)}개")

    if not chart_map:
        logger.error("생성된 차트가 없습니다. 종료합니다.")
        return

    # ── Step 2: Gemini Vision 분석 ──
    print(f"\n🤖 Step 2: Gemini Vision 분석 중... ({len(chart_map)}개)")
    client = genai.Client(api_key=API_KEY)
    semaphore = asyncio.Semaphore(10)

    tasks = []
    for ticker, filepath in chart_map.items():
        name = STOCKS[ticker]
        tasks.append(analyze_chart(client, ticker, name, filepath, semaphore))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 예외 필터링
    valid_results = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"  분석 실패: {r}")
        elif r is not None:
            valid_results.append(r)

    print(f"\n  → 분석 완료: {len(valid_results)}/{len(chart_map)}개")

    # ── Step 3: 결과 종합 ──
    print("\n📋 Step 3: 결과 종합...")
    summarize_results(valid_results)


if __name__ == '__main__':
    asyncio.run(main())
