#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lead-Lag Analysis - LLM Interpreter Module
Uses Gemini to provide natural language interpretation of quantitative results.

ULTRATHINK Design:
- Takes statistical results as input
- Generates investment insights in Korean/English
- Identifies limitations and caveats
- Suggests additional indicators to monitor
"""
import os
import logging
from typing import Dict, List, Optional
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_gemini_model():
    """Initialize Gemini model"""
    try:
        import google.generativeai as genai
        from dotenv import load_dotenv

        load_dotenv()
        api_key = os.getenv("GOOGLE_API_KEY")

        if not api_key:
            logger.error("GOOGLE_API_KEY not found in environment")
            return None

        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-3-flash-preview")

    except ImportError:
        logger.error("google-generativeai not installed")
        return None
    except Exception as e:
        logger.error(f"Failed to initialize Gemini: {e}")
        return None


def _generate_with_fallback(prompt: str) -> Optional[str]:
    """LLM 텍스트 생성 — Gemini 우선, 소진/실패 시 DeepSeek V4 → OpenAI 폴백.

    2026-06-10 Gemini 선불 크레딧 소진 (429) 대응. 모든 provider 실패 시 None
    반환 — 호출부는 기존 정적 fallback 사용.
    """
    model = get_gemini_model()
    if model is not None:
        try:
            response = model.generate_content(prompt)
            text = (response.text or '').strip()
            if text:
                return text
        except Exception as e:
            logger.warning(f"Gemini failed, trying fallback chain: {e}")

    try:
        import sys as _sys
        from pathlib import Path as _Path
        # crypto-analytics/crypto_market/lead_lag/ → 프로젝트 루트
        _root = str(_Path(__file__).resolve().parents[3])
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from llm_fallback import generate_text_fallback

        text, provider = generate_text_fallback(prompt, max_tokens=4096, temperature=0.5)
        if text:
            logger.info(f"Fallback LLM succeeded via {provider}")
            return text
    except Exception as e:
        logger.error(f"Fallback chain failed: {e}")
    return None


def interpret_lead_lag_results(
    results: List[Dict],
    target: str = "BTC",
    current_conditions: Optional[Dict] = None,
    lang: str = "ko"
) -> str:
    """
    Use LLM to interpret lead-lag analysis results.
    
    Args:
        results: List of analysis results (from LeadLagResult.to_dict())
        target: Target variable being analyzed
        current_conditions: Current values of indicators (optional)
        lang: Output language ('ko' or 'en')
    
    Returns:
        LLM-generated interpretation
    """
    # Format results for LLM (provider 선택/폴백은 _generate_with_fallback 이 처리)
    results_text = json.dumps(results, indent=2, ensure_ascii=False)
    
    if lang == "ko":
        prompt = f"""
당신은 매크로 경제와 암호화폐 시장 전문가입니다.
아래 Lead-Lag 상관관계 분석 결과를 해석하고 투자 인사이트를 제공해주세요.

## 분석 대상: {target}

## Lead-Lag 분석 결과:
{results_text}

## 현재 시장 상황:
{json.dumps(current_conditions, indent=2, ensure_ascii=False) if current_conditions else "정보 없음"}

## 요청 사항:
1. **핵심 발견사항**: 가장 중요한 선행/후행 관계 3가지를 설명해주세요.
2. **투자 시사점**: 현재 선행지표들의 상태를 고려할 때 {target}의 향후 전망은?
3. **주의사항**: 이 분석의 한계점과 주의해야 할 점
4. **추가 모니터링**: 추가로 확인해야 할 지표나 이벤트

간결하고 실용적인 답변을 부탁드립니다.
"""
    else:
        prompt = f"""
You are an expert in macroeconomics and cryptocurrency markets.
Interpret the following Lead-Lag correlation analysis results and provide investment insights.

## Target Asset: {target}

## Lead-Lag Analysis Results:
{results_text}

## Current Market Conditions:
{json.dumps(current_conditions, indent=2) if current_conditions else "Not provided"}

## Requested Analysis:
1. **Key Findings**: Explain the 3 most important lead-lag relationships.
2. **Investment Implications**: Given current leading indicators, what's the outlook for {target}?
3. **Caveats**: Limitations and risks of this analysis
4. **Additional Monitoring**: What other indicators or events should be tracked?

Please provide concise, actionable insights.
"""
    
    text = _generate_with_fallback(prompt)
    if text:
        return text
    logger.error("All LLM providers failed for lead-lag interpretation")
    return _fallback_interpretation(results, target, lang)


def interpret_granger_results(
    granger_results: List[Dict],
    target: str = "BTC",
    lang: str = "ko"
) -> str:
    """
    Use LLM to interpret Granger causality results.
    """
    results_text = json.dumps(granger_results, indent=2, ensure_ascii=False)
    
    if lang == "ko":
        prompt = f"""
당신은 계량경제학과 시계열 분석 전문가입니다.
아래 Granger 인과관계 테스트 결과를 해석해주세요.

## 분석 대상: {target}

## Granger 인과관계 테스트 결과:
{results_text}

## 설명:
- Granger 인과관계란: 과거 값이 미래 예측에 도움이 되는지 테스트
- p-value < 0.05: 통계적으로 유의한 예측력 존재
- best_lag: 가장 강한 예측력을 보이는 시차

## 요청:
1. 어떤 지표가 {target}을 가장 잘 예측하나요?
2. 각 지표의 예측 시차(lag)는 무엇을 의미하나요?
3. 실제 트레이딩에 어떻게 활용할 수 있나요?
4. 주의해야 할 점은?

실용적인 관점에서 간결하게 답변해주세요.
"""
    else:
        prompt = f"""
You are an expert in econometrics and time series analysis.
Interpret the following Granger causality test results.

## Target Asset: {target}

## Granger Causality Test Results:
{results_text}

## Context:
- Granger causality tests whether past values help predict future values
- p-value < 0.05: Statistically significant predictive power
- best_lag: The lag with strongest predictive power

## Please explain:
1. Which indicators best predict {target}?
2. What do the lag periods mean for each indicator?
3. How can this be used in trading?
4. What are the caveats?

Please provide concise, practical insights.
"""
    
    text = _generate_with_fallback(prompt)
    if text:
        return text
    logger.error("All LLM providers failed for Granger interpretation")
    return _fallback_granger_interpretation(granger_results, target, lang)


def generate_trading_signal_interpretation(
    lead_lag_results: List[Dict],
    current_values: Dict,
    target: str = "BTC",
    lang: str = "ko"
) -> str:
    """
    Generate trading signal based on current leading indicator values.
    """
    if lang == "ko":
        prompt = f"""
당신은 퀀트 트레이더입니다.
Lead-Lag 분석 결과와 현재 선행지표 값을 바탕으로 {target}에 대한 신호를 생성해주세요.

## Lead-Lag 관계:
{json.dumps(lead_lag_results, indent=2, ensure_ascii=False)}

## 현재 선행지표 값:
{json.dumps(current_values, indent=2, ensure_ascii=False)}

## 분석 요청:
1. **신호**: BULLISH / BEARISH / NEUTRAL 중 하나
2. **신뢰도**: 1-10점
3. **예상 시점**: 언제쯤 {target}에 영향이 나타날지
4. **근거**: 어떤 선행지표가 이 신호를 지지하는지
5. **리스크**: 이 신호가 틀릴 수 있는 시나리오

JSON 형식으로 답변해주세요:
{{
  "signal": "BULLISH/BEARISH/NEUTRAL",
  "confidence": 7,
  "expected_timing": "1-2개월 후",
  "rationale": "...",
  "risk_factors": ["..."]
}}
"""
    else:
        prompt = f"""
You are a quant trader.
Generate a signal for {target} based on lead-lag analysis and current indicator values.

## Lead-Lag Relationships:
{json.dumps(lead_lag_results, indent=2)}

## Current Leading Indicator Values:
{json.dumps(current_values, indent=2)}

## Please provide:
1. **Signal**: BULLISH / BEARISH / NEUTRAL
2. **Confidence**: 1-10 scale
3. **Expected Timing**: When the effect should materialize
4. **Rationale**: Which indicators support this signal
5. **Risks**: Scenarios where this could be wrong

Reply in JSON format:
{{
  "signal": "BULLISH/BEARISH/NEUTRAL",
  "confidence": 7,
  "expected_timing": "1-2 months",
  "rationale": "...",
  "risk_factors": ["..."]
}}
"""
    
    text = _generate_with_fallback(prompt)
    if text:
        return text
    logger.error("All LLM providers failed for signal generation")
    return '{"signal": "NEUTRAL", "confidence": 1, "error": "LLM unavailable"}'


def _fallback_interpretation(results: List[Dict], target: str, lang: str) -> str:
    """Fallback interpretation when LLM is unavailable"""
    if lang == "ko":
        lines = [f"## {target} Lead-Lag 분석 결과 요약\n"]
        
        for r in results[:5]:
            lag = r.get('optimal_lag', 0)
            corr = r.get('optimal_correlation', 0)
            var1 = r.get('var1', 'Unknown')
            
            if lag > 0:
                lines.append(f"- **{var1}**: {target}보다 {lag}기간 선행 (상관계수: {corr:.3f})")
            elif lag < 0:
                lines.append(f"- **{var1}**: {target}보다 {-lag}기간 후행 (상관계수: {corr:.3f})")
            else:
                lines.append(f"- **{var1}**: {target}과 동시 변동 (상관계수: {corr:.3f})")
        
        return "\n".join(lines)
    else:
        lines = [f"## {target} Lead-Lag Analysis Summary\n"]
        
        for r in results[:5]:
            lag = r.get('optimal_lag', 0)
            corr = r.get('optimal_correlation', 0)
            var1 = r.get('var1', 'Unknown')
            
            if lag > 0:
                lines.append(f"- **{var1}**: Leads {target} by {lag} periods (corr: {corr:.3f})")
            elif lag < 0:
                lines.append(f"- **{var1}**: Lags {target} by {-lag} periods (corr: {corr:.3f})")
            else:
                lines.append(f"- **{var1}**: Moves with {target} simultaneously (corr: {corr:.3f})")
        
        return "\n".join(lines)


def _fallback_granger_interpretation(results: List[Dict], target: str, lang: str) -> str:
    """Fallback interpretation for Granger results"""
    if lang == "ko":
        lines = [f"## {target} Granger 인과관계 분석 요약\n"]
        
        for r in results:
            cause = r.get('cause', 'Unknown')
            p_val = r.get('best_p_value', 1.0)
            lag = r.get('best_lag', 0)
            
            if p_val < 0.05:
                lines.append(f"- **{cause}** → {target}: {lag}기간 선행하여 예측 가능 (p={p_val:.4f})")
        
        return "\n".join(lines) if len(lines) > 1 else "유의한 Granger 인과관계가 발견되지 않았습니다."
    else:
        lines = [f"## {target} Granger Causality Summary\n"]
        
        for r in results:
            cause = r.get('cause', 'Unknown')
            p_val = r.get('best_p_value', 1.0)
            lag = r.get('best_lag', 0)
            
            if p_val < 0.05:
                lines.append(f"- **{cause}** → {target}: Predicts at {lag} periods ahead (p={p_val:.4f})")
        
        return "\n".join(lines) if len(lines) > 1 else "No significant Granger-causal relationships found."


if __name__ == "__main__":
    print("\n🤖 LLM Interpreter Test\n")
    
    # Test with sample results
    sample_results = [
        {"var1": "DXY", "var2": "BTC", "optimal_lag": -2, "optimal_correlation": -0.45},
        {"var1": "M2", "var2": "BTC", "optimal_lag": 6, "optimal_correlation": 0.61},
        {"var1": "VIX", "var2": "BTC", "optimal_lag": 0, "optimal_correlation": -0.52},
    ]
    
    interpretation = interpret_lead_lag_results(sample_results, "BTC", lang="ko")
    print(interpretation)
