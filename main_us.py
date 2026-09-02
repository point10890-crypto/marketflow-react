"""
Gemini Vision S&P 500 Chart Analyzer
Top 100 S&P 500 stocks — auto-generate candlestick charts → Gemini/OpenAI Vision technical analysis
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
import mplfinance as mpf
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ── Logging ──
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ── Environment ──
load_dotenv()
API_KEY = os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')

if not API_KEY and not OPENAI_API_KEY:
    logger.error("GEMINI_API_KEY and OPENAI_API_KEY both missing in .env")
    sys.exit(1)

plt.rcParams['axes.unicode_minus'] = False

# ── Output directory ──
CHARTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'charts_us')
os.makedirs(CHARTS_DIR, exist_ok=True)

# ── S&P 500 Top 100 stocks ──
STOCKS = {
    "AAPL": ("Apple", "Technology"), "MSFT": ("Microsoft", "Technology"),
    "GOOGL": ("Alphabet", "Technology"), "AMZN": ("Amazon", "Consumer Cyclical"),
    "NVDA": ("NVIDIA", "Technology"), "META": ("Meta Platforms", "Technology"),
    "TSLA": ("Tesla", "Consumer Cyclical"), "BRK-B": ("Berkshire Hathaway", "Financial"),
    "UNH": ("UnitedHealth", "Healthcare"), "JNJ": ("Johnson & Johnson", "Healthcare"),
    "V": ("Visa", "Financial"), "XOM": ("Exxon Mobil", "Energy"),
    "JPM": ("JPMorgan Chase", "Financial"), "WMT": ("Walmart", "Consumer Defensive"),
    "PG": ("Procter & Gamble", "Consumer Defensive"), "MA": ("Mastercard", "Financial"),
    "HD": ("Home Depot", "Consumer Cyclical"), "CVX": ("Chevron", "Energy"),
    "MRK": ("Merck", "Healthcare"), "ABBV": ("AbbVie", "Healthcare"),
    "LLY": ("Eli Lilly", "Healthcare"), "PEP": ("PepsiCo", "Consumer Defensive"),
    "KO": ("Coca-Cola", "Consumer Defensive"), "COST": ("Costco", "Consumer Defensive"),
    "AVGO": ("Broadcom", "Technology"), "TMO": ("Thermo Fisher", "Healthcare"),
    "MCD": ("McDonald's", "Consumer Cyclical"), "CSCO": ("Cisco", "Technology"),
    "ACN": ("Accenture", "Technology"), "ABT": ("Abbott Labs", "Healthcare"),
    "DHR": ("Danaher", "Healthcare"), "CRM": ("Salesforce", "Technology"),
    "CMCSA": ("Comcast", "Communication"), "NKE": ("Nike", "Consumer Cyclical"),
    "TXN": ("Texas Instruments", "Technology"), "NEE": ("NextEra Energy", "Utilities"),
    "PM": ("Philip Morris", "Consumer Defensive"), "BMY": ("Bristol-Myers", "Healthcare"),
    "UPS": ("UPS", "Industrials"), "RTX": ("RTX Corp", "Industrials"),
    "AMGN": ("Amgen", "Healthcare"), "HON": ("Honeywell", "Industrials"),
    "UNP": ("Union Pacific", "Industrials"), "LOW": ("Lowe's", "Consumer Cyclical"),
    "INTC": ("Intel", "Technology"), "IBM": ("IBM", "Technology"),
    "QCOM": ("Qualcomm", "Technology"), "BA": ("Boeing", "Industrials"),
    "CAT": ("Caterpillar", "Industrials"), "GE": ("GE Aerospace", "Industrials"),
    "SPGI": ("S&P Global", "Financial"), "INTU": ("Intuit", "Technology"),
    "AMAT": ("Applied Materials", "Technology"), "ADP": ("ADP", "Industrials"),
    "DE": ("Deere & Co", "Industrials"), "MDLZ": ("Mondelez", "Consumer Defensive"),
    "GILD": ("Gilead Sciences", "Healthcare"), "SYK": ("Stryker", "Healthcare"),
    "ADI": ("Analog Devices", "Technology"), "BKNG": ("Booking Holdings", "Consumer Cyclical"),
    "ISRG": ("Intuitive Surgical", "Healthcare"), "REGN": ("Regeneron", "Healthcare"),
    "VRTX": ("Vertex Pharma", "Healthcare"), "MMC": ("Marsh McLennan", "Financial"),
    "CB": ("Chubb", "Financial"), "LRCX": ("Lam Research", "Technology"),
    "ZTS": ("Zoetis", "Healthcare"), "PGR": ("Progressive", "Financial"),
    "CI": ("Cigna", "Healthcare"), "BDX": ("Becton Dickinson", "Healthcare"),
    "SO": ("Southern Co", "Utilities"), "DUK": ("Duke Energy", "Utilities"),
    "CME": ("CME Group", "Financial"), "CL": ("Colgate-Palmolive", "Consumer Defensive"),
    "MO": ("Altria", "Consumer Defensive"), "SCHW": ("Charles Schwab", "Financial"),
    "NOW": ("ServiceNow", "Technology"), "EQIX": ("Equinix", "Real Estate"),
    "APD": ("Air Products", "Materials"), "SHW": ("Sherwin-Williams", "Materials"),
    "TGT": ("Target", "Consumer Cyclical"), "ETN": ("Eaton Corp", "Industrials"),
    "NOC": ("Northrop Grumman", "Industrials"), "ITW": ("Illinois Tool Works", "Industrials"),
    "PNC": ("PNC Financial", "Financial"), "ORLY": ("O'Reilly Auto", "Consumer Cyclical"),
    "MCO": ("Moody's", "Financial"), "GD": ("General Dynamics", "Industrials"),
    "KLAC": ("KLA Corp", "Technology"), "SNPS": ("Synopsys", "Technology"),
    "AZO": ("AutoZone", "Consumer Cyclical"), "CDNS": ("Cadence Design", "Technology"),
    "SLB": ("Schlumberger", "Energy"), "FIS": ("Fidelity National", "Technology"),
    "EOG": ("EOG Resources", "Energy"), "MSI": ("Motorola Solutions", "Technology"),
    "ADSK": ("Autodesk", "Technology"), "TFC": ("Truist Financial", "Financial"),
    "APH": ("Amphenol", "Technology"), "HUM": ("Humana", "Healthcare"),
}

# ── Gemini Analysis Prompt ──
ANALYSIS_PROMPT = """You are a technical analysis expert with 25 years of experience.

Analyze this {name} ({ticker}) stock chart.

Check the following:
1. Moving average (20/50/200) alignment status
2. Whether RSI is below 30 (oversold) or above 70 (overbought)
3. Volume change compared to the 20-day average
4. Bollinger Band upper/lower touch

Respond ONLY in the following JSON format:
{{
  "signal": "BUY or HOLD or SELL",
  "confidence": integer between 0 and 100,
  "reasons": ["reason1", "reason2", "reason3"],
  "ma_status": "bullish_aligned or bearish_aligned or mixed",
  "rsi_zone": "oversold or neutral or overbought",
  "volume_trend": "increasing or decreasing or flat"
}}"""


# ════════════════════════════════════════════════
# Step 1: Chart Generation
# ════════════════════════════════════════════════

def generate_chart(ticker: str, name: str) -> str | None:
    """Generate 1-year candlestick chart PNG → return filepath"""
    try:
        df = yf.download(ticker, period='1y', progress=False)

        if df.empty or len(df) < 20:
            logger.warning(f"[SKIP] {name}({ticker}): insufficient data ({len(df)} rows)")
            return None

        # MultiIndex column handling
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel('Ticker', axis=1)

        # Timezone cleanup
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # Moving average addplots
        ap = []
        for period, color in [(20, 'cyan'), (50, 'orange'), (200, 'red')]:
            ma = df['Close'].rolling(period).mean()
            if ma.notna().sum() > 0:
                ap.append(mpf.make_addplot(ma, color=color, width=0.8))

        # Filename
        filepath = os.path.join(CHARTS_DIR, f"{ticker}.png")

        # mplfinance chart
        mc = mpf.make_marketcolors(up='#26a69a', down='#ef5350', edge='inherit',
                                   wick='inherit', volume='in', ohlc='i')
        s = mpf.make_mpf_style(marketcolors=mc, base_mpf_style='charles',
                               gridcolor='#333333', facecolor='#1a1a2e',
                               figcolor='#1a1a2e',
                               rc={'axes.unicode_minus': False,
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
# Step 2: Gemini Vision Analysis
# ════════════════════════════════════════════════

_executor = ThreadPoolExecutor(max_workers=10)


def _extract_json(text: str) -> dict | None:
    """Extract JSON from Gemini response (handles markdown fences, truncation)"""
    text = text.strip()

    # Strip markdown code fences
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    # 1st: direct parse
    try:
        data = json.loads(text)
        return data[0] if isinstance(data, list) and data else data
    except json.JSONDecodeError:
        pass

    # 2nd: truncated JSON recovery
    if '{' in text:
        candidate = text[text.index('{'):]

        # Close unclosed strings
        in_string = False
        last_char = ''
        for ch in candidate:
            if ch == '"' and last_char != '\\':
                in_string = not in_string
            last_char = ch
        if in_string:
            candidate += '"'

        # Remove trailing comma
        candidate = re.sub(r',\s*$', '', candidate)

        # Close unclosed brackets/braces
        open_brackets = candidate.count('[') - candidate.count(']')
        if open_brackets > 0:
            candidate += ']' * open_brackets

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
    """Synchronous Gemini API call"""
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
            logger.error(f"[PARSE FAIL] {name}({ticker}): parse failed — {text[:200]}")

        return data
    except Exception as e:
        logger.error(f"[GEMINI ERROR] {name}({ticker}): {e}")
        return None


OPENAI_VISION_MODEL = os.getenv('US_CHART_OPENAI_MODEL') or os.getenv('OPENAI_MODEL') or 'gpt-5.5'


def _openai_chat_with_token_limit(client, *, model: str, messages: list,
                                  max_output_tokens: int, **kwargs):
    """토큰 한도 파라미터명을 모델에 맞춰 협상하는 chat 호출 (main_kr.py 동일 패턴)."""
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
    """OpenAI Vision fallback for chart analysis.

    2026-09-02: gpt-4o-mini 하드코딩이 매 호출 404 (계정 보유 모델은 gpt-5.5 뿐) —
    Gemini 크레딧 소진과 겹치자 US AI 차트가 8/24 부터 통째로 정지했던 원인.
    """
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
            logger.error(f"[OPENAI PARSE FAIL] {name}({ticker}): parse failed — {text[:200]}")

        return data
    except Exception as e:
        logger.error(f"[OPENAI ERROR] {name}({ticker}): {e}")
        return None


# Track consecutive Gemini failures to detect sustained outage
_gemini_fail_count = 0
_GEMINI_FAIL_THRESHOLD = 5  # disable Gemini after N consecutive failures


async def analyze_chart(client: genai.Client, ticker: str, name: str,
                        image_path: str, semaphore: asyncio.Semaphore) -> dict | None:
    """Async wrapper: Gemini Vision → OpenAI Vision fallback"""
    global _gemini_fail_count
    async with semaphore:
        loop = asyncio.get_event_loop()
        result = None

        # Try Gemini first (skip if too many consecutive failures)
        if _gemini_fail_count < _GEMINI_FAIL_THRESHOLD and API_KEY:
            result = await loop.run_in_executor(_executor, _call_gemini, client, ticker, name, image_path)
            if result is None:
                _gemini_fail_count += 1
                if _gemini_fail_count >= _GEMINI_FAIL_THRESHOLD:
                    logger.warning(f"[FALLBACK] Gemini failed {_GEMINI_FAIL_THRESHOLD} times consecutively, switching to OpenAI Vision")
            else:
                _gemini_fail_count = 0  # reset on success

        # OpenAI Vision fallback
        if result is None and OPENAI_API_KEY:
            result = await loop.run_in_executor(_executor, _call_openai_vision, ticker, name, image_path)

        if result:
            sector = STOCKS.get(ticker, ("", "Unknown"))[1]
            result['ticker'] = ticker
            result['name'] = name
            result['sector'] = sector
            logger.info(f"  ✓ {name} ({ticker}) → {result.get('signal', '?')} (confidence: {result.get('confidence', '?')})")
        return result


# ════════════════════════════════════════════════
# Step 3: Summarize Results
# ════════════════════════════════════════════════

def summarize_results(results: list[dict]) -> pd.DataFrame:
    """Organize analysis results into DataFrame + save CSV"""
    records = []
    for r in results:
        if not r:
            continue
        records.append({
            'ticker': r.get('ticker', ''),
            'name': r.get('name', ''),
            'sector': r.get('sector', ''),
            'signal': r.get('signal', ''),
            'confidence': r.get('confidence', 0),
            'ma_status': r.get('ma_status', ''),
            'rsi_zone': r.get('rsi_zone', ''),
            'volume_trend': r.get('volume_trend', ''),
            'reasons': ' | '.join(r.get('reasons', [])) if isinstance(r.get('reasons'), list) else str(r.get('reasons', '')),
        })

    df = pd.DataFrame(records)
    if df.empty:
        logger.warning("No analysis results.")
        return df

    df = df.sort_values('confidence', ascending=False).reset_index(drop=True)

    # Summary
    print("\n" + "=" * 60)
    print("📊 Analysis Summary")
    print("=" * 60)

    counts = df['signal'].value_counts()
    for signal in ['BUY', 'HOLD', 'SELL']:
        cnt = counts.get(signal, 0)
        emoji = '🟢' if signal == 'BUY' else '🟡' if signal == 'HOLD' else '🔴'
        print(f"  {emoji} {signal}: {cnt}")

    buy_df = df[df['signal'] == 'BUY']
    if not buy_df.empty:
        print(f"\n{'─' * 60}")
        print("🟢 BUY Signals:")
        print(f"{'─' * 60}")
        for _, row in buy_df.iterrows():
            print(f"  {row['name']:20s} ({row['ticker']:5s}) {row['sector']:18s} | "
                  f"conf={row['confidence']:3d} | MA:{row['ma_status']} | "
                  f"RSI:{row['rsi_zone']} | Vol:{row['volume_trend']}")

    # Save CSV
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gemini_chart_analysis_us.csv')
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n💾 Results saved: {csv_path}")
    print(f"   Total {len(df)} stocks analyzed\n")

    return df


# ════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════

async def main():
    print("=" * 60)
    print("🔍 Gemini Vision S&P 500 Chart Analyzer")
    print(f"   Model: {MODEL}")
    print(f"   Stocks: {len(STOCKS)} (S&P 500 Top 100)")
    print("=" * 60)

    # ── Step 1: Chart Generation ──
    print(f"\n📈 Step 1: Generating candlestick charts... ({len(STOCKS)})")
    chart_map: dict[str, str] = {}  # ticker → filepath
    for i, (ticker, (name, sector)) in enumerate(STOCKS.items(), 1):
        print(f"  [{i:3d}/{len(STOCKS)}] {name} ({ticker})...", end=' ')
        filepath = generate_chart(ticker, name)
        if filepath:
            chart_map[ticker] = filepath
            print("✓")
        else:
            print("✗ (skip)")

    print(f"\n  → Charts generated: {len(chart_map)}/{len(STOCKS)}")

    if not chart_map:
        logger.error("No charts generated. Exiting.")
        return

    # ── Step 2: Gemini Vision Analysis ──
    print(f"\n🤖 Step 2: Gemini Vision analysis... ({len(chart_map)})")
    client = genai.Client(api_key=API_KEY)
    semaphore = asyncio.Semaphore(10)

    tasks = []
    for ticker, filepath in chart_map.items():
        name = STOCKS[ticker][0]
        tasks.append(analyze_chart(client, ticker, name, filepath, semaphore))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter exceptions
    valid_results = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"  Analysis failed: {r}")
        elif r is not None:
            valid_results.append(r)

    print(f"\n  → Analysis complete: {len(valid_results)}/{len(chart_map)}")

    # ── Step 3: Summarize ──
    print("\n📋 Step 3: Summarizing results...")
    summarize_results(valid_results)


if __name__ == '__main__':
    asyncio.run(main())
