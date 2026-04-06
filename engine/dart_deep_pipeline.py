"""
DART 10년 재무제표 × Gemini AI 심층분석 — 6단계 파이프라인.

파이프라인:
  Step 1: DART 10년 재무제표 수집               (필수, 실패 시 전체 중단)
  Step 2: Structured Output — 핵심지표/밸류에이션
  Step 3: Code Execution — DCF 적정가치 + 민감도
  Step 4: Grounding Search — 뉴스 교차검증
  Step 5: URL Context — 최신 사업보고서 요약
  Step 6: 결과 저장 + 상태 업데이트

Step 2~5 는 개별 실패해도 다음 단계 계속 진행 (비치명적).

실행 방식:
  - 백그라운드 스레드에서 `run_pipeline_background(stock_code, stock_name)` 호출
  - 진행 상태는 module-level `_JOBS` dict 에 저장 (폴링용)
  - 최종 결과는 `data/dart_deep/{stock_code}_{YYYYMMDD}.json` 에 저장
  - 24h 이내 같은 종목 재요청 시 디스크 캐시 재사용
"""

from __future__ import annotations

import os
import json
import time
import threading
import asyncio
import logging
from datetime import datetime, date, timezone, timedelta
from typing import Any, Dict, Optional

from engine.dart_collector import DARTCollector
from engine.llm.gemini_advanced import (
    generate_structured,
    generate_with_code_execution,
    generate_with_search,
    analyze_url,
)

logger = logging.getLogger("marketflow.dart_deep")

# ── 상수 ─────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_BASE_DIR, "data", "dart_deep")
_CACHE_TTL_HOURS = 24

STEPS = [
    ("collect", "DART 10년 재무제표 수집"),
    ("metrics", "핵심 지표 & 밸류에이션"),
    ("dcf", "DCF 적정가치 산출"),
    ("news", "뉴스 교차검증"),
    ("report", "사업보고서 요약"),
    ("save", "결과 저장"),
]

# ── 인메모리 Job Store ────────────────────────────────────────
# { job_id: { status, stock_code, stock_name, started_at, steps: [...], result, error } }
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()

# 종목당 동시 실행 1개 제한 (같은 종목 중복 호출 방지)
_ACTIVE_STOCKS: Dict[str, str] = {}  # stock_code -> job_id


# ── JSON 스키마 (Step 2 용) ──────────────────────────────────
_METRICS_SCHEMA = {
    "type": "object",
    "properties": {
        "yearly": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer"},
                    "revenue_eok": {"type": "number"},
                    "op_profit_eok": {"type": "number"},
                    "net_income_eok": {"type": "number"},
                    "roe_pct": {"type": "number"},
                    "op_margin_pct": {"type": "number"},
                    "debt_ratio_pct": {"type": "number"},
                },
                "required": ["year", "revenue_eok", "op_profit_eok"],
            },
        },
        "summary_10yr": {
            "type": "object",
            "properties": {
                "revenue_cagr_pct": {"type": "number"},
                "op_profit_cagr_pct": {"type": "number"},
                "best_year": {"type": "integer"},
                "worst_year": {"type": "integer"},
                "avg_roe_pct": {"type": "number"},
            },
        },
        "valuation": {
            "type": "object",
            "properties": {
                "grade": {"type": "string", "enum": ["S", "A", "B", "C", "D"]},
                "strengths": {"type": "array", "items": {"type": "string"}},
                "risks": {"type": "array", "items": {"type": "string"}},
                "one_liner": {"type": "string"},
            },
            "required": ["grade", "strengths", "risks", "one_liner"],
        },
    },
    "required": ["yearly", "summary_10yr", "valuation"],
}


# ── Public API ───────────────────────────────────────────────

def get_cached_result(stock_code: str) -> Optional[Dict[str, Any]]:
    """24h 이내 캐시된 결과가 있으면 반환."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_CACHE_TTL_HOURS)
    try:
        if not os.path.isdir(_DATA_DIR):
            return None
        for fname in os.listdir(_DATA_DIR):
            if not fname.startswith(f"{stock_code}_") or not fname.endswith(".json"):
                continue
            path = os.path.join(_DATA_DIR, fname)
            mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
            if mtime < cutoff:
                continue
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"get_cached_result: {e}")
    return None


def start_job(stock_code: str, stock_name: str) -> Dict[str, Any]:
    """
    분석 Job 시작. 이미 실행 중이거나 24h 캐시가 있으면 재사용.

    Returns:
        { "job_id", "status": "running|cached", "cached": bool }
    """
    # 1) 24h 캐시 체크
    cached = get_cached_result(stock_code)
    if cached:
        return {
            "job_id": f"cached_{stock_code}",
            "status": "cached",
            "cached": True,
            "result": cached,
        }

    # 2) 진행 중인 job 체크
    with _JOBS_LOCK:
        active_job_id = _ACTIVE_STOCKS.get(stock_code)
        if active_job_id and _JOBS.get(active_job_id, {}).get("status") == "running":
            return {"job_id": active_job_id, "status": "running", "cached": False}

        # 3) 신규 job 등록
        job_id = f"{stock_code}_{int(time.time())}"
        _JOBS[job_id] = {
            "job_id": job_id,
            "stock_code": stock_code,
            "stock_name": stock_name,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "steps": [
                {"key": k, "label": l, "status": "pending", "error": None}
                for k, l in STEPS
            ],
            "result": None,
            "error": None,
        }
        _ACTIVE_STOCKS[stock_code] = job_id

    # 4) 백그라운드 실행
    t = threading.Thread(
        target=_run_pipeline_thread,
        args=(job_id, stock_code, stock_name),
        daemon=True,
    )
    t.start()
    return {"job_id": job_id, "status": "running", "cached": False}


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Job 상태 조회 (폴링용)."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        return {
            "job_id": job["job_id"],
            "stock_code": job["stock_code"],
            "stock_name": job["stock_name"],
            "status": job["status"],
            "started_at": job["started_at"],
            "steps": [dict(s) for s in job["steps"]],
            "error": job["error"],
            # result 는 완료 후에만 포함
            "result": job["result"] if job["status"] in ("done", "error") else None,
        }


# ── 내부 구현 ─────────────────────────────────────────────────

def _update_step(job_id: str, key: str, status: str, error: Optional[str] = None):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        for step in job["steps"]:
            if step["key"] == key:
                step["status"] = status
                if error:
                    step["error"] = error
                break


def _finalize_job(job_id: str, status: str, result: Optional[Dict] = None, error: Optional[str] = None):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["status"] = status
        job["result"] = result
        job["error"] = error
        stock_code = job["stock_code"]
        if _ACTIVE_STOCKS.get(stock_code) == job_id:
            _ACTIVE_STOCKS.pop(stock_code, None)


def _run_pipeline_thread(job_id: str, stock_code: str, stock_name: str):
    try:
        result = asyncio.run(_run_pipeline(job_id, stock_code, stock_name))
        _finalize_job(job_id, "done", result=result)
    except Exception as e:
        logger.exception(f"dart_deep pipeline failed: {job_id}")
        _finalize_job(job_id, "error", error=f"{type(e).__name__}: {e}")


async def _run_pipeline(job_id: str, stock_code: str, stock_name: str) -> Dict[str, Any]:
    output: Dict[str, Any] = {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # ── Step 1: DART 10년 재무제표 수집 (필수) ────────────────
    _update_step(job_id, "collect", "running")
    collector = DARTCollector()
    financials = await collector.fetch_10yr_financials(stock_code, years=10)
    if not financials.get("years"):
        _update_step(job_id, "collect", "error", "재무제표 수집 실패")
        raise RuntimeError("Step 1 실패: DART 재무제표를 수집할 수 없습니다")

    output["financials"] = financials
    _update_step(job_id, "collect", "done")

    financials_text = _financials_to_text(stock_name, financials)

    # ── Step 2: Structured Output — 핵심지표 ──────────────────
    _update_step(job_id, "metrics", "running")
    metrics_prompt = f"""당신은 20년 경력의 CFA 한국 주식 애널리스트입니다.
아래는 {stock_name}({stock_code})의 10년 연결재무제표(억원 단위)입니다.

{financials_text}

다음 JSON 스키마에 맞춰 분석 결과를 반환하세요:
- yearly: 각 연도별 주요 지표 (ROE, 영업이익률, 부채비율)
- summary_10yr: 10년 CAGR, 최고/최악 연도, 평균 ROE
- valuation: 투자등급(S/A/B/C/D), 강점 3개, 리스크 3개, 한 줄 총평

[출력 언어 규칙] 반드시 한국어로만 작성하세요.
- strengths, risks, one_liner 를 포함한 모든 문자열 필드는 100% 한국어 문장이어야 합니다.
- 영어 단어/문구 사용 금지 (회사 고유명사·지표 약어 제외). 예: "CAGR", "ROE", "WACC" 같은 약어는 허용.
- 영어 문장을 번역한 듯한 어색한 표현 금지. 자연스러운 한국어 투자 애널리스트 문장으로 작성.

숫자는 반드시 제공된 데이터에서만 계산하세요. 추측 금지.
"""
    metrics = generate_structured(metrics_prompt, _METRICS_SCHEMA, temperature=0.2)
    if metrics:
        output["metrics"] = metrics
        _update_step(job_id, "metrics", "done")
    else:
        _update_step(job_id, "metrics", "error", "Gemini Structured Output 실패")
        output["metrics"] = None

    # ── Step 3: Code Execution — DCF ──────────────────────────
    _update_step(job_id, "dcf", "running")
    latest_year = max(financials["years"])
    latest = financials["data"][latest_year]
    dcf_prompt = f"""당신은 퀀트 애널리스트입니다. 아래 데이터를 바탕으로 Python 코드를 작성/실행하여 DCF 적정가치를 계산하세요.

기업: {stock_name} ({stock_code})
기준 연도: {latest_year}
최근 재무 (억원):
  매출액: {latest.get('revenue', 0):.0f}
  영업이익: {latest.get('op_profit', 0):.0f}
  당기순이익: {latest.get('net_income', 0):.0f}
  자산총계: {latest.get('total_assets', 0):.0f}
  부채총계: {latest.get('total_liab', 0):.0f}

가정:
  - FCF ≈ 영업이익 × (1 - 0.25) + 감가상각(매출의 10%) - CAPEX(매출의 5%)
  - WACC = 9%, 영구성장률 g = 2%
  - 5년 예측 + Terminal Value

실행할 것:
1. 기본 시나리오 DCF 적정가치(억원) 계산
2. WACC(7/8/9/10/11%) × g(1/2/3%) 민감도 그리드 출력
3. 마지막에 '적정가치(기본): {{value}}억원' 형태로 요약 출력

코드를 작성하고 실행해서 결과를 보여주세요.
"""
    try:
        dcf = generate_with_code_execution(dcf_prompt, temperature=0.2)
        if dcf.get("code_output") or dcf.get("text"):
            output["dcf"] = dcf
            _update_step(job_id, "dcf", "done")
        else:
            _update_step(job_id, "dcf", "error", "Code execution 결과 없음")
            output["dcf"] = None
    except Exception as e:
        _update_step(job_id, "dcf", "error", str(e))
        output["dcf"] = None

    # ── Step 4: Grounding Search — 뉴스 교차검증 ─────────────
    _update_step(job_id, "news", "running")
    valuation_summary = ""
    if output.get("metrics"):
        val = output["metrics"].get("valuation", {})
        valuation_summary = f"투자등급 {val.get('grade', '?')}, 요약: {val.get('one_liner', '')}"

    news_prompt = f"""당신은 한국 주식 시장 전문 애널리스트입니다.
{stock_name}({stock_code})의 10년 재무제표 분석 결과는 다음과 같습니다.

{valuation_summary}

최근 2주 동안의 주요 뉴스를 Google 검색으로 찾아서:
1. 재무 데이터가 보여주는 스토리와 현재 시장 컨센서스의 일치/불일치
2. 재무제표에서 드러나지 않는 리스크 또는 호재
3. 최종 판정: [매수 / 관망 / 매도] 중 하나를 제시

간결한 한국어 마크다운으로 답변하세요.
"""
    try:
        news = generate_with_search(news_prompt, temperature=0.4)
        if news.get("text"):
            output["news"] = news
            _update_step(job_id, "news", "done")
        else:
            _update_step(job_id, "news", "error", "Search 결과 없음")
            output["news"] = None
    except Exception as e:
        _update_step(job_id, "news", "error", str(e))
        output["news"] = None

    # ── Step 5: URL Context — 사업보고서 ──────────────────────
    _update_step(job_id, "report", "running")
    corp_code = financials.get("corp_code")
    if corp_code:
        # DART 최신 사업보고서 검색 후 URL 직접 분석은 제한적이라,
        # 기업 공시 상세페이지 링크로 대체
        report_url = f"https://opendart.fss.or.kr/disclosureinfo/public/cp-ann/main.do?corpCode={corp_code}"
        report_prompt = f"""다음 DART 공시 페이지를 읽고 {stock_name}의 최근 사업보고서에서 다음을 2~3문장으로 요약하세요:
- 주요 경영 리스크
- 향후 가이던스 또는 성장 전략
- 투자자가 주목할 특이사항

페이지에 접근할 수 없으면 "공시 페이지 접근 제한" 이라고 답변하세요.
"""
        try:
            report_text = analyze_url(report_url, report_prompt, temperature=0.3)
            if report_text:
                output["report"] = {"url": report_url, "summary": report_text}
                _update_step(job_id, "report", "done")
            else:
                _update_step(job_id, "report", "error", "URL Context 응답 없음")
                output["report"] = None
        except Exception as e:
            _update_step(job_id, "report", "error", str(e))
            output["report"] = None
    else:
        _update_step(job_id, "report", "error", "corp_code 없음")
        output["report"] = None

    # ── Step 6: 저장 ──────────────────────────────────────────
    _update_step(job_id, "save", "running")
    try:
        _save_result(stock_code, output)
        _update_step(job_id, "save", "done")
    except Exception as e:
        _update_step(job_id, "save", "error", str(e))

    return output


def _financials_to_text(stock_name: str, financials: Dict) -> str:
    """10년 재무 데이터를 LLM 프롬프트용 마크다운 테이블로 변환."""
    years = financials.get("years", [])
    data = financials.get("data", {})
    if not years:
        return "(데이터 없음)"

    lines = [
        f"종목: {stock_name}",
        f"데이터 출처: DART {financials.get('source') or '연결/개별'}",
        "",
        "| 연도 | 매출액 | 영업이익 | 당기순이익 | 자산총계 | 부채총계 | 자본총계 | 현금 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for y in sorted(years):
        d = data.get(y, {})
        lines.append(
            f"| {y} | "
            f"{d.get('revenue', 0):,.0f} | "
            f"{d.get('op_profit', 0):,.0f} | "
            f"{d.get('net_income', 0):,.0f} | "
            f"{d.get('total_assets', 0):,.0f} | "
            f"{d.get('total_liab', 0):,.0f} | "
            f"{d.get('total_equity', 0):,.0f} | "
            f"{d.get('cash', 0):,.0f} |"
        )
    lines.append("")
    lines.append("(단위: 억원)")
    return "\n".join(lines)


def _save_result(stock_code: str, result: Dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    path = os.path.join(
        _DATA_DIR, f"{stock_code}_{date.today().strftime('%Y%m%d')}.json"
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
