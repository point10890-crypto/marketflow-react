"""
AI 자동 브리핑 생성기
- 조간 브리핑 (09:05 KST): US 시장 중심
- 마감 브리핑 (16:05 KST): KR 시장 중심
- Gemini 2.5 Flash + Google Search Grounding
"""
import os
import json
import asyncio
import logging
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BASE_DIR, 'data')
_BRIEFING_DIR = os.path.join(_DATA_DIR, 'briefing')
_US_OUTPUT = os.path.join(_BASE_DIR, 'us_market', 'output')
_CRYPTO_OUTPUT = os.path.join(_BASE_DIR, 'crypto-analytics', 'crypto_market', 'output')


class BriefingGenerator:

    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.client = None
        self.model = "gemini-2.5-flash"
        if api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=api_key)
            except Exception as e:
                logger.error(f"Gemini client init failed: {e}")
        os.makedirs(_BRIEFING_DIR, exist_ok=True)

    # ── Data helpers ──

    @staticmethod
    def _load_json(path: str) -> dict | None:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _fmt_pct(val) -> str:
        if val is None:
            return 'N/A'
        return f"{val:+.2f}%"

    @staticmethod
    def _fmt_price(val) -> str:
        if val is None:
            return 'N/A'
        if val >= 10000:
            return f"{val:,.0f}"
        return f"{val:,.2f}"

    # ── Data collection ──

    def _collect_morning_data(self) -> dict:
        """US-focused data for morning briefing"""
        data = {}

        # Market briefing (indices, futures, bonds, currencies, commodities, VIX, F&G)
        mb = self._load_json(os.path.join(_US_OUTPUT, 'market_briefing.json'))
        if mb:
            md = mb.get('market_data', {})
            data['indices'] = md.get('indices', {})
            data['futures'] = md.get('futures', {})
            data['bonds'] = md.get('bonds', {})
            data['currencies'] = md.get('currencies', {})
            data['commodities'] = md.get('commodities', {})
            data['korean_indices'] = md.get('korean_indices', {})
            data['vix'] = mb.get('vix', {})
            data['fear_greed'] = mb.get('fear_greed', {})

        # Macro analysis
        macro = self._load_json(os.path.join(_US_OUTPUT, 'macro_analysis.json'))
        if macro:
            data['macro'] = {
                'summary': macro.get('summary', ''),
                'key_points': macro.get('key_points', [])[:5],
            }

        # Decision signal
        signal = self._load_json(os.path.join(_US_OUTPUT, 'decision_signal_snapshot.json'))
        if signal:
            data['decision_signal'] = {
                'signal': signal.get('signal', ''),
                'confidence': signal.get('confidence', 0),
                'components': signal.get('components', {}),
            }

        # Smart money
        sm = self._load_json(os.path.join(_US_OUTPUT, 'smart_money_snapshot.json'))
        if sm:
            picks = sm.get('picks', sm.get('top_picks', []))
            data['smart_money'] = [
                {'ticker': p.get('ticker', ''), 'name': p.get('name', ''),
                 'score': p.get('final_score', p.get('composite_score', 0))}
                for p in (picks[:5] if isinstance(picks, list) else [])
            ]

        # Sector rotation
        sr = self._load_json(os.path.join(_US_OUTPUT, 'sector_rotation.json'))
        if sr:
            data['sector_rotation'] = sr.get('content', sr.get('summary', ''))[:500]

        # Risk alerts
        risk = self._load_json(os.path.join(_US_OUTPUT, 'risk_alerts.json'))
        if risk:
            alerts = risk.get('alerts', risk.get('risk_alerts', []))
            data['risk_alerts'] = alerts[:5] if isinstance(alerts, list) else []

        # Earnings
        earn = self._load_json(os.path.join(_US_OUTPUT, 'earnings_analysis.json'))
        if earn:
            upcoming = earn.get('upcoming_earnings', earn.get('details', []))
            data['earnings'] = upcoming[:5] if isinstance(upcoming, list) else []

        # Options flow
        opt = self._load_json(os.path.join(_US_OUTPUT, 'options_flow.json'))
        if opt:
            data['options_flow'] = opt.get('summary', str(opt)[:300])

        # Crypto dominance
        crypto = self._load_json(os.path.join(_DATA_DIR, 'crypto_dominance_cache.json'))
        if crypto:
            data['crypto'] = {
                'btc_dominance': crypto.get('btc_dominance', ''),
                'total_market_cap': crypto.get('total_market_cap', ''),
            }

        # KR market gate
        gate = self._load_json(os.path.join(_DATA_DIR, 'market_gate_cache.json'))
        if gate:
            data['kr_gate'] = {
                'status': gate.get('status', ''),
                'score': gate.get('score', 0),
                'label': gate.get('label', ''),
                'reasons': gate.get('reasons', [])[:3],
            }

        return data

    def _collect_closing_data(self) -> dict:
        """KR-focused data for closing briefing"""
        data = {}

        # Jongga V2
        jongga = self._load_json(os.path.join(_DATA_DIR, 'jongga_v2_latest.json'))
        if jongga:
            signals = jongga.get('signals', [])
            top_signals = []
            for s in signals[:10]:
                score = s.get('score', {})
                top_signals.append({
                    'name': s.get('stock_name', ''),
                    'code': s.get('stock_code', ''),
                    'grade': s.get('grade', ''),
                    'total': score.get('total', 0),
                    'change_pct': s.get('change_pct', 0),
                    'trading_value': s.get('trading_value', 0),
                    'reason': score.get('llm_reason', ''),
                })
            data['jongga'] = {
                'date': jongga.get('date', ''),
                'total': jongga.get('filtered_count', len(signals)),
                'by_grade': jongga.get('by_grade', {}),
                'signals': top_signals,
            }

        # Market gate
        gate = self._load_json(os.path.join(_DATA_DIR, 'market_gate_cache.json'))
        if gate:
            data['kr_gate'] = {
                'status': gate.get('status', ''),
                'score': gate.get('score', 0),
                'label': gate.get('label', ''),
                'reasons': gate.get('reasons', []),
                'sectors': gate.get('sectors', [])[:5],
            }

        # Global context (US market)
        mb = self._load_json(os.path.join(_US_OUTPUT, 'market_briefing.json'))
        if mb:
            md = mb.get('market_data', {})
            idx = md.get('indices', {})
            data['us_context'] = {
                'spy': idx.get('SPY', {}),
                'qqq': idx.get('QQQ', {}),
                'vix': mb.get('vix', {}),
                'fear_greed': mb.get('fear_greed', {}),
                'futures': md.get('futures', {}),
                'usdkrw': md.get('currencies', {}).get('USDKRW=X', {}),
            }

        # Crypto
        crypto = self._load_json(os.path.join(_CRYPTO_OUTPUT, 'overview_snapshot.json'))
        if crypto:
            data['crypto'] = {
                'btc': crypto.get('btc', crypto.get('BTC', {})),
                'eth': crypto.get('eth', crypto.get('ETH', {})),
            }

        return data

    # ── Prompt builders ──

    def _build_morning_prompt(self, data: dict) -> str:
        lines = [
            "당신은 월가 경력 20년의 한국인 수석 전략가입니다.",
            "오늘 한국 투자자를 위한 **조간 브리핑**을 작성해주세요.",
            "Google Search를 활용해 최신 뉴스와 이슈를 반영하세요.",
            "",
            "## 제공 데이터",
        ]

        # Indices
        if 'indices' in data:
            lines.append("\n### 미국 주요 지수 (어젯밤 마감)")
            for k, v in data['indices'].items():
                lines.append(f"- {v.get('name', k)}: {self._fmt_price(v.get('price'))} ({self._fmt_pct(v.get('change'))})")

        # Futures
        if 'futures' in data:
            lines.append("\n### 선물")
            for k, v in data['futures'].items():
                lines.append(f"- {v.get('name', k)}: {self._fmt_price(v.get('price'))} ({self._fmt_pct(v.get('change'))})")

        # Bonds
        if 'bonds' in data:
            lines.append("\n### 채권")
            for k, v in data['bonds'].items():
                lines.append(f"- {v.get('name', k)}: {v.get('price', 'N/A')}")

        # Currencies
        if 'currencies' in data:
            lines.append("\n### 환율")
            for k, v in data['currencies'].items():
                lines.append(f"- {v.get('name', k)}: {self._fmt_price(v.get('price'))} ({self._fmt_pct(v.get('change'))})")

        # VIX & Fear/Greed
        if 'vix' in data:
            v = data['vix']
            lines.append(f"\n### VIX: {v.get('value', 'N/A')} ({v.get('level', '')})")
        if 'fear_greed' in data:
            fg = data['fear_greed']
            lines.append(f"### Fear & Greed: {fg.get('score', 'N/A')} ({fg.get('level', '')})")

        # Decision signal
        if 'decision_signal' in data:
            ds = data['decision_signal']
            lines.append(f"\n### AI Decision Signal: {ds.get('signal', 'N/A')} (confidence: {ds.get('confidence', 0)})")

        # Smart money
        if 'smart_money' in data:
            lines.append("\n### Smart Money Top Picks")
            for p in data['smart_money']:
                lines.append(f"- {p['ticker']} ({p['name']}): score {p['score']}")

        # Macro
        if 'macro' in data:
            lines.append(f"\n### 매크로 요약\n{data['macro'].get('summary', '')[:500]}")

        # Risk
        if 'risk_alerts' in data and data['risk_alerts']:
            lines.append("\n### 리스크 알림")
            for a in data['risk_alerts']:
                if isinstance(a, dict):
                    lines.append(f"- {a.get('title', a.get('message', str(a)))}")
                else:
                    lines.append(f"- {a}")

        # KR Gate
        if 'kr_gate' in data:
            kg = data['kr_gate']
            lines.append(f"\n### 한국 시장 레짐: {kg.get('label', '')} (score: {kg.get('score', 0)})")

        # Crypto
        if 'crypto' in data:
            lines.append(f"\n### 크립토: BTC dominance {data['crypto'].get('btc_dominance', 'N/A')}")

        # Output format
        lines.append("""
## 출력 형식 (반드시 아래 JSON 스키마를 따르세요)
```json
{
  "title": "M/DD 조간브리핑: [핵심 한줄 요약]",
  "summary": "2-3문장으로 오늘 핵심 요약. 한국 투자자 관점.",
  "sections": [
    {"heading": "🇺🇸 미국 시장 마감", "content": "주요 지수 등락, 섹터별 동향, 특이사항"},
    {"heading": "📰 핵심 이슈 & 뉴스", "content": "Google Search로 찾은 최신 글로벌 뉴스 3-5개"},
    {"heading": "📊 매크로 환경", "content": "VIX, 금리, 환율, 원자재 분석"},
    {"heading": "💰 Smart Money 동향", "content": "기관 매매, Top Picks 변동"},
    {"heading": "🎯 오늘의 투자 전략", "content": "한국 시장 영향 + 구체적 전략 제안"},
    {"heading": "⚠️ 리스크 요인", "content": "주의 사항, 경계 이벤트"}
  ],
  "market_sentiment": "BULLISH 또는 NEUTRAL 또는 BEARISH",
  "confidence": 0.0~1.0,
  "key_events": ["오늘 주목할 이벤트 3-5개"],
  "sources": ["참고한 뉴스 출처"]
}
```
- sections의 content는 마크다운 형식 (볼드, 리스트, 표 등 사용 가능)
- 한국어로 작성
- 데이터에 없는 내용은 Google Search로 보완
""")
        return '\n'.join(lines)

    def _build_closing_prompt(self, data: dict) -> str:
        lines = [
            "당신은 한국 증시 경력 20년의 수석 전략가입니다.",
            "오늘 장 마감 후 투자자를 위한 **마감 브리핑**을 작성해주세요.",
            "Google Search를 활용해 최신 뉴스와 장중 이슈를 반영하세요.",
            "",
            "## 제공 데이터",
        ]

        # KR market gate
        if 'kr_gate' in data:
            kg = data['kr_gate']
            lines.append(f"\n### 한국 시장 레짐: {kg.get('label', '')} (score: {kg.get('score', 0)})")
            for r in kg.get('reasons', []):
                lines.append(f"  - {r}")
            if kg.get('sectors'):
                lines.append("  섹터:")
                for s in kg['sectors']:
                    lines.append(f"  - {s.get('name', '')}: {s.get('signal', '')} ({self._fmt_pct(s.get('change_pct'))})")

        # Jongga signals
        if 'jongga' in data:
            j = data['jongga']
            lines.append(f"\n### 종가베팅 시그널 ({j.get('date', '')})")
            lines.append(f"총 {j.get('total', 0)}개 | 등급별: {json.dumps(j.get('by_grade', {}), ensure_ascii=False)}")
            for s in j.get('signals', []):
                lines.append(
                    f"- [{s['grade']}] {s['name']}({s['code']}): "
                    f"점수 {s['total']}, 등락 {self._fmt_pct(s['change_pct'])}, "
                    f"사유: {s.get('reason', '')[:80]}"
                )

        # US context
        if 'us_context' in data:
            uc = data['us_context']
            spy = uc.get('spy', {})
            qqq = uc.get('qqq', {})
            lines.append(f"\n### 미국 시장 (글로벌 컨텍스트)")
            lines.append(f"- S&P 500: {self._fmt_price(spy.get('price'))} ({self._fmt_pct(spy.get('change'))})")
            lines.append(f"- NASDAQ: {self._fmt_price(qqq.get('price'))} ({self._fmt_pct(qqq.get('change'))})")
            vix = uc.get('vix', {})
            lines.append(f"- VIX: {vix.get('value', 'N/A')} ({vix.get('level', '')})")
            usdkrw = uc.get('usdkrw', {})
            lines.append(f"- USD/KRW: {self._fmt_price(usdkrw.get('price'))}")

        # Crypto
        if 'crypto' in data:
            lines.append("\n### 크립토")
            for k, v in data['crypto'].items():
                if isinstance(v, dict):
                    lines.append(f"- {k.upper()}: {self._fmt_price(v.get('price', v.get('current_price')))}")

        # Output format
        lines.append("""
## 출력 형식 (반드시 아래 JSON 스키마를 따르세요)
```json
{
  "title": "M/DD 마감브리핑: [핵심 한줄 요약]",
  "summary": "2-3문장으로 오늘 장 마감 핵심 요약.",
  "sections": [
    {"heading": "🇰🇷 한국 시장 마감", "content": "KOSPI/KOSDAQ 등락, 섹터별 동향, 수급 특징"},
    {"heading": "🔥 종가베팅 시그널", "content": "오늘 S/A급 종목 분석, 핵심 테마"},
    {"heading": "📰 장중 이슈 & 뉴스", "content": "Google Search로 찾은 한국 시장 뉴스"},
    {"heading": "🌍 글로벌 컨텍스트", "content": "미국 선물, 환율, 크립토 동향"},
    {"heading": "🎯 내일 전략", "content": "오버나잇 리스크, 주시 종목, 전략 제안"},
    {"heading": "📊 수급 분석", "content": "외국인/기관 매매 동향, 프로그램 매매"}
  ],
  "market_sentiment": "BULLISH 또는 NEUTRAL 또는 BEARISH",
  "confidence": 0.0~1.0,
  "key_events": ["내일 주목할 이벤트 3-5개"],
  "sources": ["참고한 뉴스 출처"]
}
```
- sections의 content는 마크다운 형식 사용 가능
- 한국어로 작성
- 데이터에 없는 내용은 Google Search로 보완
""")
        return '\n'.join(lines)

    # ── Gemini call ──

    async def _call_gemini(self, prompt: str) -> dict | None:
        if not self.client:
            logger.error("Gemini client not available")
            return None

        try:
            from google.genai import types

            # Note: response_mime_type="application/json" is incompatible with
            # Google Search tool. We request JSON in the prompt and parse manually.
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.7,
                )
            )

            text = response.text
            if not text:
                logger.error("Gemini returned empty response")
                return None

            # Try direct JSON parse first
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

            # Extract JSON from markdown code block
            md_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
            if md_match:
                try:
                    return json.loads(md_match.group(1))
                except json.JSONDecodeError:
                    pass

            # Last resort: find outermost {...}
            brace_match = re.search(r'\{[\s\S]*\}', text)
            if brace_match:
                try:
                    return json.loads(brace_match.group())
                except json.JSONDecodeError:
                    pass

            logger.error(f"Failed to parse Gemini response: {text[:300]}")
            return None

        except Exception as e:
            logger.error(f"Gemini call failed: {e}")
            return None

    # ── Fallback (data-only briefing when Gemini fails) ──

    def _fallback_morning(self, data: dict) -> dict:
        now = datetime.now()
        idx = data.get('indices', {})
        spy = idx.get('SPY', {})
        qqq = idx.get('QQQ', {})
        vix = data.get('vix', {})

        sections = [
            {"heading": "🇺🇸 미국 시장 마감", "content":
                f"- S&P 500: {self._fmt_price(spy.get('price'))} ({self._fmt_pct(spy.get('change'))})\n"
                f"- NASDAQ 100: {self._fmt_price(qqq.get('price'))} ({self._fmt_pct(qqq.get('change'))})\n"
                f"- VIX: {vix.get('value', 'N/A')} ({vix.get('level', '')})"},
            {"heading": "📊 주요 지표", "content":
                f"- Fear & Greed: {data.get('fear_greed', {}).get('score', 'N/A')}\n"
                f"- USD/KRW: {data.get('currencies', {}).get('USDKRW=X', {}).get('price', 'N/A')}"},
        ]
        if data.get('decision_signal'):
            ds = data['decision_signal']
            sections.append({"heading": "🎯 AI Signal", "content": f"{ds.get('signal', 'N/A')} (confidence: {ds.get('confidence', 0)})"})

        sentiment = 'NEUTRAL'
        spy_chg = spy.get('change', 0) or 0
        if spy_chg > 1:
            sentiment = 'BULLISH'
        elif spy_chg < -1:
            sentiment = 'BEARISH'

        return {
            "title": f"{now.month}/{now.day} 조간브리핑: 데이터 요약",
            "summary": f"S&P 500 {self._fmt_pct(spy.get('change'))}, VIX {vix.get('value', 'N/A')}. AI 분석 불가로 데이터 요약만 제공합니다.",
            "sections": sections,
            "market_sentiment": sentiment,
            "confidence": 0.3,
            "key_events": [],
            "sources": ["자체 데이터"],
        }

    def _fallback_closing(self, data: dict) -> dict:
        now = datetime.now()
        gate = data.get('kr_gate', {})
        jongga = data.get('jongga', {})

        sections = [
            {"heading": "🇰🇷 한국 시장", "content":
                f"시장 레짐: {gate.get('label', 'N/A')} (score: {gate.get('score', 0)})\n"
                + '\n'.join(f"- {r}" for r in gate.get('reasons', []))},
        ]
        if jongga.get('signals'):
            sig_lines = [f"- [{s['grade']}] {s['name']}: {self._fmt_pct(s['change_pct'])}" for s in jongga['signals'][:5]]
            sections.append({"heading": "🔥 종가베팅 Top 5", "content": '\n'.join(sig_lines)})

        return {
            "title": f"{now.month}/{now.day} 마감브리핑: 데이터 요약",
            "summary": f"KR 시장 {gate.get('label', 'N/A')}, 종가베팅 {jongga.get('total', 0)}개 시그널. AI 분석 불가로 데이터 요약만 제공합니다.",
            "sections": sections,
            "market_sentiment": 'BULLISH' if gate.get('score', 0) >= 60 else ('BEARISH' if gate.get('score', 0) <= 40 else 'NEUTRAL'),
            "confidence": 0.3,
            "key_events": [],
            "sources": ["자체 데이터"],
        }

    # ── Generate + Save ──

    async def generate_morning(self) -> dict | None:
        logger.info("조간 브리핑 생성 시작...")
        data = self._collect_morning_data()
        if not data:
            logger.error("조간 데이터 수집 실패")
            return None

        prompt = self._build_morning_prompt(data)
        result = await self._call_gemini(prompt)

        if not result:
            logger.warning("Gemini 실패, fallback 브리핑 생성")
            result = self._fallback_morning(data)

        now = datetime.now()
        result['type'] = 'morning'
        result['date'] = now.strftime('%Y%m%d')
        result['generated_at'] = now.isoformat()

        self._save('morning', result)
        logger.info(f"조간 브리핑 생성 완료: {result.get('title', '')}")
        return result

    async def generate_closing(self) -> dict | None:
        logger.info("마감 브리핑 생성 시작...")
        data = self._collect_closing_data()
        if not data:
            logger.error("마감 데이터 수집 실패")
            return None

        prompt = self._build_closing_prompt(data)
        result = await self._call_gemini(prompt)

        if not result:
            logger.warning("Gemini 실패, fallback 브리핑 생성")
            result = self._fallback_closing(data)

        now = datetime.now()
        result['type'] = 'closing'
        result['date'] = now.strftime('%Y%m%d')
        result['generated_at'] = now.isoformat()

        self._save('closing', result)
        logger.info(f"마감 브리핑 생성 완료: {result.get('title', '')}")
        return result

    def _save(self, briefing_type: str, data: dict):
        date_str = data.get('date', datetime.now().strftime('%Y%m%d'))

        # Save dated file
        dated_path = os.path.join(_BRIEFING_DIR, f'{briefing_type}_{date_str}.json')
        with open(dated_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Save latest
        latest_path = os.path.join(_BRIEFING_DIR, 'latest.json')
        with open(latest_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved: {dated_path}")


# ── Sync wrappers for scheduler ──

def generate_morning_briefing() -> dict | None:
    gen = BriefingGenerator()
    return asyncio.run(gen.generate_morning())


def generate_closing_briefing() -> dict | None:
    gen = BriefingGenerator()
    return asyncio.run(gen.generate_closing())


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    mode = sys.argv[1] if len(sys.argv) > 1 else 'morning'
    if mode == 'closing':
        result = generate_closing_briefing()
    else:
        result = generate_morning_briefing()

    if result:
        print(f"\nTitle: {result['title']}")
        print(f"Sentiment: {result['market_sentiment']}")
        print(f"Sections: {len(result.get('sections', []))}")
        print(f"Saved to: data/briefing/")
    else:
        print("Generation failed")
