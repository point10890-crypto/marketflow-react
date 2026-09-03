"""주도주LIVE Layer 2 보강 엔진
- Gemini Flash 뉴스분석 (왜 오르는지 AI 해석)
- 연속 주도주 추적 (며칠 연속 등장)
- 시가총액 분류 (대형/중형/소형)
- 15분 주기 비동기 보강 → 메인 스코어러 결과에 머지

토큰 비용 (Gemini 2.0 Flash):
  - Input $0.10/1M, Output $0.40/1M
  - 호출당 ~$0.00004 (150 input + 50 output tokens)
  - 10종목 × 26사이클/일 × 22일 ≈ $0.23/월
"""
import os
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from threading import Lock

from app.utils.paths import DATA_DIR

logger = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


def _get_gemini_key():
    """Lazy load — .env가 Flask 시작 후 로드되므로 호출 시점에 읽기"""
    return os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")

# ─── 캐시 ───
_enrichment_cache = {}   # {code: {"data": {...}, "ts": float}}
_enrichment_lock = Lock()
_ENRICH_TTL = 900        # 15분 (초)
_last_enrich_ts = 0      # 마지막 보강 실행 시각


def _safe_int(val, default=0):
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default


# ─── 1. Gemini 뉴스 분석 ───

def _analyze_news_gemini(stock_name, stock_code, change_pct):
    """Gemini 2.0 Flash로 종목 상승/하락 이유 분석.

    비용: ~$0.00004/call (150 input + 50 output tokens)
    """
    api_key = _get_gemini_key()
    if not api_key:
        return {"ai_score": 0, "ai_reason": "", "themes": []}

    prompt = (
        f"한국 주식 '{stock_name}'({stock_code})이 오늘 {change_pct:+.1f}% 변동.\n"
        f"상승/하락 이유를 분석하세요.\n\n"
        f'JSON만 응답: {{"ai_score":0-3,"ai_reason":"이유20자이내","themes":["테마"]}}\n'
        f"점수: 3=확실한호재 2=긍정적 1=불분명 0=근거없음"
    )

    try:
        res = requests.post(
            f"{GEMINI_URL}?key={api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 150,
                    "responseMimeType": "application/json",
                },
            },
            timeout=15,
        )
        if res.status_code == 200:
            text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
            # Gemini가 배열 [{...}]로 응답할 수 있음
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            if not isinstance(data, dict):
                data = {}
            return {
                "ai_score": min(3, max(0, int(data.get("ai_score", 0) or 0))),
                "ai_reason": str(data.get("ai_reason", ""))[:30],
                "themes": [str(t)[:10] for t in data.get("themes", [])][:3],
            }
        elif res.status_code == 429:
            logger.warning("Gemini Rate Limit — 스킵")
        else:
            logger.warning(f"Gemini {res.status_code}: {res.text[:100]}")
    except requests.exceptions.Timeout:
        logger.warning(f"Gemini 타임아웃: {stock_name}")
    except Exception as e:
        logger.warning(f"Gemini 분석 실패 {stock_name}: {e}")

    return {"ai_score": 0, "ai_reason": "", "themes": []}


def _analyze_news_llm(stock_name, stock_code, change_pct):
    """주도주 뉴스분석 — DeepSeek → OpenAI 우선, Gemini REST 는 백업 (2026-09-02 순위 변경)."""
    prompt = (
        f"한국 주식 '{stock_name}'({stock_code})이 오늘 {change_pct:+.1f}% 변동.\n"
        f"상승/하락 이유를 분석하세요.\n\n"
        f'JSON만 응답: {{"ai_score":0-3,"ai_reason":"이유20자이내","themes":["테마"]}}\n'
        f"점수: 3=확실한호재 2=긍정적 1=불분명 0=근거없음"
    )
    try:
        from llm_fallback import generate_json_fallback
        data, provider = generate_json_fallback(prompt, max_tokens=150, temperature=0.3)
        if isinstance(data, dict) and data:
            return {
                "ai_score": min(3, max(0, int(data.get("ai_score", 0) or 0))),
                "ai_reason": str(data.get("ai_reason", ""))[:30],
                "themes": [str(t)[:10] for t in data.get("themes", [])][:3],
            }
    except Exception as e:
        logger.warning(f"DeepSeek/OpenAI 주도주 분석 실패 {stock_name}: {e}")
    return _analyze_news_gemini(stock_name, stock_code, change_pct)


# ─── 1-b. 수치 검증 (L4 number_guard) ───

AI_REASON_GUARD_FALLBACK = "AI 사유 수치 불일치로 생략"


def _guard_ai_reason(ai, row):
    """LLM 이 만든 `ai_reason` 의 숫자를 종목 행(원천)과 대조한다.

    NUMBER_GUARD_POLICY=enforce(기본): 모순이면 사유를 정직한 짧은 문구로 교체.
    NUMBER_GUARD_POLICY=shadow: 사유 유지, 집계만 첨부. 검증 실패는 보강을 막지 않는다.
    """
    try:
        from app.services.mirofish.number_guard import guard_text_against, resolve_policy

        reason = str((ai or {}).get("ai_reason") or "")
        if not reason.strip():
            return ai
        policy = resolve_policy(default="enforce")
        row = row if isinstance(row, dict) else {}
        truth = {
            "change_pct": row.get("change_pct"),
            "price": row.get("price"),
            "trading_value": row.get("trading_value"),
            "trading_value_eok": row.get("trading_value_eok"),
            "volume_ratio": row.get("volume_ratio"),
        }
        truth = {k: float(v) for k, v in truth.items()
                 if isinstance(v, (int, float)) and not isinstance(v, bool)}
        verdict = guard_text_against(reason, truth, policy=policy)
        out = dict(ai)
        out["ai_reason_guard"] = verdict.to_dict()
        if verdict.should_drop:
            logger.warning(f"[number_guard] 주도주 AI 사유 폐기 {row.get('name', '')}: {reason!r}")
            out["ai_reason"] = AI_REASON_GUARD_FALLBACK
        return out
    except Exception as e:  # noqa: BLE001 — 검증 실패가 보강을 막지 않는다
        logger.warning(f"[number_guard] 주도주 사유 검증 건너뜀: {e}")
        return ai


# ─── 2. 연속 주도주 추적 ───

def _count_consecutive_days(stock_code):
    """최근 10영업일간 주도주(B등급 이상) 등장 횟수"""
    count = 0
    today = datetime.now()
    for i in range(1, 15):  # 캘린더 14일 ≈ 영업일 10일
        d = today - timedelta(days=i)
        if d.weekday() >= 5:  # 주말 스킵
            continue
        date_str = d.strftime("%Y%m%d")
        path = os.path.join(DATA_DIR, f"screener_leading_{date_str}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            codes = {r["code"] for r in data.get("results", [])}
            if stock_code in codes:
                count += 1
        except Exception:
            pass
    return count


# ─── 3. 시가총액 분류 ───

def _classify_market_cap(market_cap_eok):
    """시가총액(억원) 기준 분류"""
    if not market_cap_eok or market_cap_eok <= 0:
        return "미분류"
    if market_cap_eok >= 100000:   # 10조 이상
        return "대형"
    if market_cap_eok >= 10000:    # 1조 이상
        return "중형"
    if market_cap_eok >= 3000:     # 3000억 이상
        return "중소형"
    return "소형"


# ─── 메인: 보강 실행 ───

def should_enrich():
    """15분 주기 체크"""
    global _last_enrich_ts
    return (time.time() - _last_enrich_ts) >= _ENRICH_TTL


def enrich_stocks(results, price_details=None):
    """Layer 2 보강 실행.

    Args:
        results: run_screening() 결과의 results 리스트
        price_details: {code: price_detail_dict} (시가총액 추출용)

    Returns:
        {code: enrichment_data} 딕셔너리
    """
    global _last_enrich_ts
    _last_enrich_ts = time.time()

    enriched = {}
    # A등급 이상만 Gemini 분석 (비용 절약), B등급은 연속/시총만
    for r in results:
        code = r.get("code", "")
        if not code:
            continue

        # 캐시 확인
        with _enrichment_lock:
            cached = _enrichment_cache.get(code)
            if cached and (time.time() - cached["ts"]) < _ENRICH_TTL:
                enriched[code] = cached["data"]
                continue

        grade = r.get("grade", "C")
        name = r.get("name", "")
        change_pct = r.get("change_pct", 0)

        # 1) LLM 뉴스분석 (A등급 이상만 — 비용 최적화, DeepSeek 우선)
        if grade in ("S", "A"):
            ai = _guard_ai_reason(_analyze_news_llm(name, code, change_pct), r)
            time.sleep(1.5)  # Rate limit 완충 (구 Gemini free tier 기준 유지)
        else:
            ai = {"ai_score": 0, "ai_reason": "", "themes": []}

        # 2) 연속 주도주
        consecutive = _count_consecutive_days(code)

        # 3) 시가총액
        market_cap_eok = 0
        cap_tier = "미분류"
        if price_details and code in price_details:
            pd = price_details[code]
            # hts_avls: HTS 시가총액 (억원)
            raw_cap = pd.get("hts_avls", "0")
            market_cap_eok = _safe_int(raw_cap)
            cap_tier = _classify_market_cap(market_cap_eok)

        data = {
            **ai,
            "consecutive_days": consecutive,
            "market_cap_eok": market_cap_eok,
            "market_cap_tier": cap_tier,
            "enriched_at": datetime.now().isoformat(),
        }

        enriched[code] = data

        with _enrichment_lock:
            _enrichment_cache[code] = {"data": data, "ts": time.time()}

    logger.info(f"[Enricher] {len(enriched)}종목 보강 완료 (Gemini: {sum(1 for r in results if r.get('grade') in ('S','A'))}건)")
    return enriched


def get_cached_enrichment():
    """현재 캐시된 모든 보강 데이터 반환"""
    now = time.time()
    result = {}
    with _enrichment_lock:
        for code, entry in _enrichment_cache.items():
            if (now - entry["ts"]) < _ENRICH_TTL * 2:  # 30분까지 유효
                result[code] = entry["data"]
    return result


def get_stock_enrichment(code):
    """단일 종목 보강 데이터 반환"""
    with _enrichment_lock:
        cached = _enrichment_cache.get(code)
        if cached and (time.time() - cached["ts"]) < _ENRICH_TTL * 2:
            return cached["data"]
    return None
