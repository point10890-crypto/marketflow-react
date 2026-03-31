"""
Gemini Vision 한국 주식 차트 분석기
코스피/코스닥 상위 100개 종목의 캔들차트를 자동 생성 → Gemini Vision API로 기술적 분석
"""

import os
import sys
import re
import json
import asyncio
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
MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')

if not API_KEY:
    logger.error("GOOGLE_API_KEY 또는 GEMINI_API_KEY가 .env에 설정되지 않았습니다.")
    sys.exit(1)

# ── 한글 폰트 ──
if sys.platform == 'win32':
    font_path = 'C:/Windows/Fonts/malgun.ttf'
elif sys.platform == 'darwin':
    font_path = '/System/Library/Fonts/AppleSDGothicNeo.ttc'
else:
    font_path = None

if font_path and os.path.exists(font_path):
    fm.fontManager.addfont(font_path)
    prop = fm.FontProperties(fname=font_path)
    plt.rcParams['font.family'] = prop.get_name()
plt.rcParams['axes.unicode_minus'] = False

# ── 출력 디렉토리 ──
CHARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'charts_kr')
os.makedirs(CHARTS_DIR, exist_ok=True)

# ── 종목 리스트 (코스피/코스닥 상위 100) ──
STOCKS = {
    # 코스피
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "373220.KS": "LG에너지솔루션",
    "207940.KS": "삼성바이오로직스", "005380.KS": "현대차", "000270.KS": "기아",
    "006400.KS": "삼성SDI", "051910.KS": "LG화학", "035420.KS": "NAVER",
    "035720.KS": "카카오", "005490.KS": "POSCO홀딩스", "055550.KS": "신한지주",
    "105560.KS": "KB금융", "003670.KS": "포스코퓨처엠", "012330.KS": "현대모비스",
    "066570.KS": "LG전자", "003550.KS": "LG", "032830.KS": "삼성생명",
    "086790.KS": "하나금융지주", "034730.KS": "SK", "015760.KS": "한국전력",
    "096770.KS": "SK이노베이션", "017670.KS": "SK텔레콤", "030200.KS": "KT",
    "316140.KS": "우리금융지주", "009150.KS": "삼성전기", "010130.KS": "고려아연",
    "028260.KS": "삼성물산", "034020.KS": "두산에너빌리티", "011200.KS": "HMM",
    "018260.KS": "삼성에스디에스", "033780.KS": "KT&G", "000810.KS": "삼성화재",
    "010950.KS": "S-Oil", "009540.KS": "HD한국조선해양", "267250.KS": "HD현대",
    "003490.KS": "대한항공", "036570.KS": "엔씨소프트", "011170.KS": "롯데케미칼",
    "024110.KS": "기업은행", "000720.KS": "현대건설", "010140.KS": "삼성중공업",
    "047050.KS": "포스코인터내셔널", "009240.KS": "한샘", "090430.KS": "아모레퍼시픽",
    "051900.KS": "LG생활건강", "329180.KS": "HD현대중공업", "004020.KS": "현대제철",
    "000100.KS": "유한양행", "011780.KS": "금호석유", "016360.KS": "삼성증권",
    "006800.KS": "미래에셋증권", "138040.KS": "메리츠금융지주", "003410.KS": "쌍용C&E",
    "069500.KS": "KODEX 200", "352820.KS": "하이브", "259960.KS": "크래프톤",
    "042660.KS": "한화오션", "402340.KS": "SK스퀘어", "361610.KS": "SK아이이테크놀로지",
    "001570.KS": "금양", "271560.KS": "오리온", "000080.KS": "하이트진로",
    "002790.KS": "아모레G", "088350.KS": "한화생명", "161390.KS": "한국타이어앤테크놀로지",
    "004170.KS": "신세계", "021240.KS": "코웨이", "006360.KS": "GS건설",
    "071050.KS": "한국금융지주", "139480.KS": "이마트", "326030.KS": "SK바이오팜",
    "180640.KS": "한진칼", "032640.KS": "LG유플러스", "078930.KS": "GS",
    # 코스닥
    "247540.KQ": "에코프로비엠", "086520.KQ": "에코프로", "377300.KQ": "카카오페이",
    "263750.KQ": "펄어비스", "068270.KQ": "셀트리온", "196170.KQ": "알테오젠",
    "145020.KQ": "휴젤", "041510.KQ": "에스엠", "293490.KQ": "카카오게임즈",
    "112040.KQ": "위메이드", "035900.KQ": "JYP Ent.", "357780.KQ": "솔브레인",
    "028300.KQ": "에이치엘비", "095340.KQ": "ISC", "039030.KQ": "이오테크닉스",
    "058470.KQ": "리노공업", "005290.KQ": "동진쎄미켐", "383220.KQ": "F&F",
    "454910.KQ": "에이피알", "322510.KQ": "제이엘케이", "236810.KQ": "엔비티",
    "403870.KQ": "HPSP", "067310.KQ": "하나마이크론", "218410.KQ": "RFHIC",
    "041920.KQ": "메디아나",
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

def generate_chart(ticker: str, name: str) -> str | None:
    """종목 1년치 캔들차트 PNG 생성 → 파일 경로 반환"""
    try:
        df = yf.download(ticker, period='1y', progress=False)

        if df.empty or len(df) < 20:
            logger.warning(f"[SKIP] {name}({ticker}): 데이터 부족 ({len(df)}행)")
            return None

        # MultiIndex 컬럼 처리
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel('Ticker', axis=1)

        # 인덱스 정리 (timezone 제거)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

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


async def analyze_chart(client: genai.Client, ticker: str, name: str,
                        image_path: str, semaphore: asyncio.Semaphore) -> dict | None:
    """비동기 래핑: Gemini Vision 차트 분석"""
    async with semaphore:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_executor, _call_gemini, client, ticker, name, image_path)
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
