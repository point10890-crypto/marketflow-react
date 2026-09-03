"""
Gemini Vision 한국 주식 차트 분석기
코스피/코스닥 상위 100개 종목의 캔들차트를 자동 생성 → Gemini/OpenAI Vision API로 기술적 분석
"""

import os
import sys
import re
import json
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import mplfinance as mpf
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from google import genai
from PIL import Image

from app.services.ai_routing.contracts import (
    AnalysisStatus,
    Operation,
    ProviderErrorClass,
    RoutingRequest,
    RoutingResult,
    TokenUsage,
    VisionImage,
)
from app.services.ai_routing.router import route_vision

# ── 로깅 ──
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ── 환경변수 ──
load_dotenv()
API_KEY = os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
MODEL = os.getenv('AI_GEMINI_VISION_MODEL') or os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
# Vision 폴백 모델. 하드코딩된 gpt-4o-mini 는 이 계정에 접근 권한이 없어
# (403 model_not_found) 폴백이 항상 실패했다. 계정에서 쓸 수 있는 모델로 두고
# 환경변수로 교체 가능하게 한다.
OPENAI_VISION_MODEL = os.getenv('KR_CHART_OPENAI_MODEL') or os.getenv('OPENAI_MODEL') or 'gpt-5.5'
try:
    _configured_vision_limit = int(os.getenv('KR_CHART_VISION_MAX_CANDIDATES', '20'))
except (TypeError, ValueError):
    _configured_vision_limit = 20
VISION_MAX_CANDIDATES = max(1, min(20, _configured_vision_limit))

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


def reset_vision_health() -> None:
    """Legacy no-op: central modality-specific breakers now own health state."""


def gemini_is_available() -> bool:
    """Compatibility helper; the central vision breaker decides per request."""
    return True


def _ranked_vision_candidates(chart_map: dict[str, str]) -> list[tuple[str, str]]:
    """Bound paid image analysis to the deterministic market-cap input order."""
    return list(chart_map.items())[:VISION_MAX_CANDIDATES]


def _chart_domain_validator(payload: object) -> ProviderErrorClass | None:
    if not isinstance(payload, dict):
        return ProviderErrorClass.INVALID_JSON
    if payload.get('signal') not in {'BUY', 'HOLD', 'SELL'}:
        return ProviderErrorClass.INVALID_JSON
    confidence = payload.get('confidence')
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return ProviderErrorClass.INVALID_JSON
    if not 0 <= confidence <= 100:
        return ProviderErrorClass.INVALID_JSON
    return None


def _normalize_chart_json(text: str) -> str | None:
    """Return locally repaired chart JSON for central schema validation.

    This is deterministic normalization only; it never triggers another model
    call.  The original provider text is retained by the routing result and is
    parsed through the same helper at the business boundary.
    """
    parsed = _extract_json(text)
    if not isinstance(parsed, dict):
        return None
    return json.dumps(parsed, ensure_ascii=False, separators=(',', ':'))


def _enum_value(value: object) -> object:
    return getattr(value, 'value', value)


def _usage_metadata(result: RoutingResult) -> dict[str, object]:
    usage = result.usage
    complete = (
        usage.input_tokens is not None
        and usage.output_tokens is not None
        and not usage.usage_estimated
        and usage.mapping_status != 'quarantined'
    )
    return {
        'input_tokens': usage.input_tokens,
        'cached_input_tokens': usage.cached_input_tokens,
        'output_tokens': usage.output_tokens,
        'reasoning_tokens': usage.reasoning_tokens,
        'total_tokens': usage.total_tokens,
        'usage_estimated': usage.usage_estimated,
        'raw_total_tokens': usage.raw_total_tokens,
        'mapping_version': usage.mapping_version,
        'mapping_status': usage.mapping_status,
        'complete': complete,
    }


def _routing_metadata(
    result: RoutingResult,
    *,
    run_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, object]:
    first_attempt = result.attempts[0] if result.attempts else None
    return {
        'run_id': run_id or (first_attempt.run_id if first_attempt else None),
        'request_id': request_id or (
            first_attempt.request_id if first_attempt else None
        ),
        'analysis_status': result.analysis_status.value,
        'primary_provider': result.primary_provider,
        'actual_provider': result.actual_provider,
        'model': result.model,
        'fallback_used': result.fallback_used,
        'fallback_reason': _enum_value(result.fallback_reason),
        'retry_reason': _enum_value(result.retry_reason),
        'usage': _usage_metadata(result),
        'estimated_cost_usd': (
            str(result.estimated_cost_usd)
            if isinstance(result.estimated_cost_usd, Decimal)
            else result.estimated_cost_usd
        ),
        'attempt_count': len(result.attempts),
        'attempts': [
            {
                'provider': attempt.provider,
                'model': attempt.model,
                'status': attempt.status,
                'error_class': _enum_value(attempt.error_class),
                'fallback_from': attempt.fallback_from,
                'fallback_reason': _enum_value(attempt.fallback_reason),
            }
            for attempt in result.attempts
        ],
    }


def _chart_image_error_class(image_data: bytes) -> str | None:
    """Return one bounded local-input error code without exposing decoder detail."""
    if not image_data:
        return 'input_empty'
    try:
        with Image.open(BytesIO(image_data)) as image:
            if image.format != 'PNG':
                return 'input_corrupt'
            image.verify()
    except Exception:
        return 'input_corrupt'
    return None


def _unavailable_chart_artifact(
    ticker: str,
    name: str,
    routed: RoutingResult,
    *,
    run_id: str,
    request_id: str,
    error_class: str | None = None,
) -> dict[str, object]:
    routing = _routing_metadata(
        routed,
        run_id=run_id,
        request_id=request_id,
    )
    if error_class is not None:
        routing['error_class'] = error_class
        routing['failure_reason'] = error_class
    return {
        '종목코드': ticker.split('.')[0],
        '종목명': name,
        '시장': '코스피' if ticker.endswith('.KS') else '코스닥',
        'image_analysis_status': 'unavailable',
        'routing': routing,
    }


def _chart_input_failure_artifact(
    ticker: str,
    name: str,
    *,
    run_id: str,
    request_id: str,
    error_class: str,
) -> dict[str, object]:
    routed = RoutingResult(
        text=None,
        analysis_status=AnalysisStatus.FAILED_TECHNICAL,
        primary_provider=None,
        usage=TokenUsage(
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            raw_total_tokens=0,
        ),
        estimated_cost_usd=Decimal('0'),
    )
    return _unavailable_chart_artifact(
        ticker,
        name,
        routed,
        run_id=run_id,
        request_id=request_id,
        error_class=error_class,
    )


async def analyze_chart(client: genai.Client, ticker: str, name: str,
                        image_path: str, semaphore: asyncio.Semaphore, *,
                        run_id: str | None = None,
                        candidate_rank: int | None = None) -> dict | None:
    """Analyze one chart through the budgeted central vision route."""
    async with semaphore:
        loop = asyncio.get_event_loop()
        effective_run_id = run_id or f'kr-chart:{uuid4()}'
        request_id = f'{effective_run_id}:{ticker}'
        try:
            with open(image_path, 'rb') as image_file:
                image_data = image_file.read()
        except OSError:
            error_class = 'input_unreadable'
            logger.error(
                '[VISION INPUT ERROR] %s(%s): class=%s',
                name,
                ticker,
                error_class,
            )
            return _chart_input_failure_artifact(
                ticker,
                name,
                run_id=effective_run_id,
                request_id=request_id,
                error_class=error_class,
            )

        input_error_class = _chart_image_error_class(image_data)
        if input_error_class is not None:
            logger.error(
                '[VISION INPUT ERROR] %s(%s): class=%s',
                name,
                ticker,
                input_error_class,
            )
            return _chart_input_failure_artifact(
                ticker,
                name,
                run_id=effective_run_id,
                request_id=request_id,
                error_class=input_error_class,
            )

        request = RoutingRequest(
            operation=Operation.VISION,
            prompt=ANALYSIS_PROMPT.format(name=name, ticker=ticker),
            system='You are a professional technical chart analyst. Respond only in valid JSON.',
            run_id=effective_run_id,
            request_id=request_id,
            symbol=ticker.split('.')[0],
            market='KOSPI' if ticker.endswith('.KS') else 'KOSDAQ',
            json_mode=True,
            max_output_tokens=768,
            images=(VisionImage(data=image_data, mime_type='image/png', detail='high'),),
            caller_endpoint='main_kr.analyze_chart',
            domain_validator=_chart_domain_validator,
            response_normalizer=_normalize_chart_json,
            # An unranked legacy caller cannot prove top-five eligibility and
            # therefore must not consume the bounded OpenAI fallback pool.
            openai_fallback_allowed=(
                candidate_rank is not None and 1 <= candidate_rank <= 5
            ),
        )
        routed = await loop.run_in_executor(_executor, route_vision, request)
        result = _extract_json(routed.text) if routed.text else None

        if isinstance(result, dict):
            market = '코스피' if ticker.endswith('.KS') else '코스닥'
            code = ticker.split('.')[0]
            result['종목코드'] = code
            result['종목명'] = name
            result['시장'] = market
            result['image_analysis_status'] = 'available'
            result['routing'] = _routing_metadata(
                routed,
                run_id=effective_run_id,
                request_id=request.request_id,
            )
            logger.info(f"  ✓ {name} → {result.get('signal', '?')} (confidence: {result.get('confidence', '?')})")
            return result
        logger.warning(
            '[VISION UNAVAILABLE] %s(%s): status=%s reason=%s',
            name,
            ticker,
            routed.analysis_status.value,
            _enum_value(routed.fallback_reason),
        )
        return _unavailable_chart_artifact(
            ticker,
            name,
            routed,
            run_id=effective_run_id,
            request_id=request.request_id,
        )


# ════════════════════════════════════════════════
# Step 3: 결과 종합
# ════════════════════════════════════════════════

def summarize_results(results: list[dict]) -> pd.DataFrame:
    """분석 결과를 DataFrame으로 정리 + CSV 저장"""
    records = []
    for r in results:
        if not r:
            continue
        routing = r.get('routing') if isinstance(r.get('routing'), dict) else {}
        usage = routing.get('usage') if isinstance(routing.get('usage'), dict) else {}
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
            'image_analysis_status': r.get('image_analysis_status', 'available'),
            'ai_run_id': routing.get('run_id'),
            'ai_request_id': routing.get('request_id'),
            'ai_analysis_status': routing.get('analysis_status'),
            'ai_primary_provider': routing.get('primary_provider'),
            'ai_actual_provider': routing.get('actual_provider'),
            'ai_model': routing.get('model'),
            'ai_fallback_used': routing.get('fallback_used', False),
            'ai_fallback_reason': routing.get('fallback_reason'),
            'ai_error_class': routing.get('error_class'),
            'ai_failure_reason': routing.get('failure_reason'),
            'ai_total_tokens': usage.get('total_tokens'),
            'ai_usage_complete': usage.get('complete'),
            'ai_estimated_cost_usd': routing.get('estimated_cost_usd'),
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
    ranked_charts = _ranked_vision_candidates(chart_map)
    print(f"\n🤖 Step 2: Gemini Vision 분석 중... ({len(ranked_charts)}개)")
    # Provider clients are lazy-built by the central router.  Keep the legacy
    # positional argument as None so external callers retain the same signature.
    client = None
    semaphore = asyncio.Semaphore(10)
    run_id = f'kr-chart:{uuid4()}'

    tasks = []
    for candidate_rank, (ticker, filepath) in enumerate(ranked_charts, 1):
        name = STOCKS[ticker]
        tasks.append(
            analyze_chart(
                client,
                ticker,
                name,
                filepath,
                semaphore,
                run_id=run_id,
                candidate_rank=candidate_rank,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 예외 필터링
    valid_results = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"  분석 실패: {r}")
        elif r is not None:
            valid_results.append(r)

    print(f"\n  → 분석 완료: {len(valid_results)}/{len(ranked_charts)}개")

    # ── Step 3: 결과 종합 ──
    print("\n📋 Step 3: 결과 종합...")
    summarize_results(valid_results)


if __name__ == '__main__':
    asyncio.run(main())
