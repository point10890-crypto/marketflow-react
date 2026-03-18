#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Economic Calendar Collector v2
- Primary source: Finviz economic calendar (reliable HTML table)
- Earnings dates: yfinance (multiple detection methods)
- AI enrichment: Gemini API (optional, for high-impact events)
- Outputs structured JSON with pre-classified impact levels
"""

import os
import json
import logging
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote
from dotenv import load_dotenv

load_dotenv()

# Translation Map for key events
EVENT_TRANSLATION = {
    'Federal Funds Rate': 'FOMC 금리 결정',
    'FOMC Economic Projections': 'FOMC 경제 전망',
    'FOMC Press Conference': 'FOMC 기자회견',
    'FOMC Minutes': 'FOMC 의사록',
    'GDP': 'GDP 성장률',
    'GDP Price Index': 'GDP 물가 지수',
    'CPI': '소비자물가지수(CPI)',
    'Core CPI': '근원 CPI',
    'PPI': '생산자물가지수(PPI)',
    'Core PPI': '근원 PPI',
    'Nonfarm Payrolls': '비농업 고용지수',
    'Unemployment Rate': '실업률',
    'Initial Jobless Claims': '신규 실업수당 청구건수',
    'Continuing Jobless Claims': '연속 실업수당 청구건수',
    'Retail Sales': '소매판매',
    'Michigan Consumer Sentiment': '미시간대 소비자심리지수',
    'ISM Manufacturing PMI': 'ISM 제조업 PMI',
    'ISM Services PMI': 'ISM 서비스업 PMI',
    'ISM Non-Manufacturing PMI': 'ISM 비제조업 PMI',
    'JOLTs Job Openings': 'JOLTs 구인보고서',
    'JOLTS Job Openings': 'JOLTs 구인보고서',
    'Durable Goods Orders': '내구재 수주',
    'Trade Balance': '무역수지',
    'CB Consumer Confidence': 'CB 소비자신뢰지수',
    'Building Permits': '건축허가건수',
    'Housing Starts': '주택착공건수',
    'New Home Sales': '신규 주택판매',
    'Existing Home Sales': '기존 주택판매',
    'Personal Income': '개인소득',
    'Personal Spending': '개인소비',
    'PCE Price Index': 'PCE 물가지수',
    'Core PCE Price Index': '근원 PCE 물가지수',
    'ADP Nonfarm Employment': 'ADP 민간고용',
    'Crude Oil Inventories': '원유재고',
    'Industrial Production': '산업생산',
    'Capacity Utilization': '설비가동률',
    'S&P Global Manufacturing PMI': 'S&P 제조업 PMI',
    'S&P Global Services PMI': 'S&P 서비스업 PMI',
    'Philadelphia Fed Manufacturing Index': '필라델피아 제조업지수',
    'Empire State Manufacturing Index': 'NY 제조업지수',
    'Consumer Credit': '소비자신용',
}

HIGH_IMPACT_KEYWORDS = [
    'Federal Funds Rate', 'FOMC', 'Nonfarm Payrolls',
    'CPI', 'Core CPI', 'GDP', 'PCE Price Index', 'Core PCE',
    'Unemployment Rate',
]

MEDIUM_IMPACT_KEYWORDS = [
    'Retail Sales', 'PPI', 'Core PPI',
    'ISM Manufacturing', 'ISM Services', 'ISM Non-Manufacturing',
    'Consumer Confidence', 'Consumer Sentiment', 'Michigan',
    'JOLT', 'Durable Goods', 'Housing Starts', 'Building Permits',
    'Initial Jobless Claims', 'Continuing Claims',
    'Trade Balance', 'New Home Sales', 'Existing Home Sales',
    'Personal Income', 'Personal Spending',
    'ADP', 'Empire State', 'Philadelphia Fed',
    'Industrial Production', 'Capacity Utilization',
    'S&P Global', 'Crude Oil Inventories',
]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EconomicCalendar:
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/120.0.0.0 Safari/537.36'
    }

    def __init__(self, data_dir: str = '.'):
        self.data_dir = data_dir
        self.output_file = os.path.join(data_dir, 'output', 'weekly_calendar.json')
        self.watchlist = [
            # Mega caps
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META',
            # Large tech
            'AMD', 'AVGO', 'NFLX', 'INTC', 'CRM', 'ORCL', 'ADBE', 'CSCO',
            # Financials
            'JPM', 'BAC', 'GS', 'MS', 'V', 'MA',
            # Consumer
            'WMT', 'COST', 'HD', 'NKE', 'SBUX', 'MCD',
            # Healthcare
            'UNH', 'JNJ', 'LLY', 'PFE', 'ABBV',
            # Industrial / Energy
            'CAT', 'BA', 'XOM', 'CVX', 'GE',
            # Retail favorites
            'PLTR', 'COIN', 'MSTR', 'SMCI', 'ARM', 'SNOW', 'NET',
        ]

    def get_week_range(self) -> tuple:
        """Get start (Mon) and end (Sun) of current week"""
        today = datetime.now()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end

    def _classify_impact(self, event_name: str) -> str:
        """Classify event impact: high / medium / low"""
        name_lower = event_name.lower()
        for kw in HIGH_IMPACT_KEYWORDS:
            if kw.lower() in name_lower:
                return 'high'
        for kw in MEDIUM_IMPACT_KEYWORDS:
            if kw.lower() in name_lower:
                return 'medium'
        return 'low'

    def _translate_event(self, event_name: str) -> str:
        """Translate event name to Korean (English) format"""
        for eng, kor in EVENT_TRANSLATION.items():
            if eng.lower() in event_name.lower():
                return f"{kor} ({event_name})"
        return event_name

    def _parse_finviz_date(self, date_str: str) -> Optional[str]:
        """Parse Finviz date like 'Mon Feb 03' into YYYY-MM-DD"""
        if not date_str or str(date_str) == 'nan':
            return None

        date_str = str(date_str).strip()
        now = datetime.now()
        year = now.year

        formats = [
            '%b %d %A',    # "Feb 03 Monday"
            '%A %b %d',    # "Monday Feb 03"
            '%b %d',       # "Feb 03"
            '%a %b %d',    # "Mon Feb 03"
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt).replace(year=year)
                # Handle year boundary (Dec->Jan)
                if dt.month == 1 and now.month == 12:
                    dt = dt.replace(year=year + 1)
                elif dt.month == 12 and now.month == 1:
                    dt = dt.replace(year=year - 1)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
        return None

    def _clean_value(self, val) -> Optional[str]:
        """Clean a table cell value, return None for empty/NaN"""
        if val is None:
            return None
        s = str(val).strip()
        if s in ('', 'nan', 'NaN', '-'):
            return None
        return s

    def get_economic_events(self) -> List[Dict]:
        """Fetch economic events from Finviz calendar (embedded JSON data)"""
        logger.info("🌍 Fetching economic events from Finviz...")

        try:
            from bs4 import BeautifulSoup

            response = requests.get(
                "https://finviz.com/calendar.ashx",
                headers=self.HEADERS, timeout=15
            )
            if response.status_code != 200:
                logger.warning(f"Finviz HTTP {response.status_code}")
                return []

            # Finviz embeds calendar data as JSON inside a <script> tag
            soup = BeautifulSoup(response.text, 'html.parser')
            entries = []

            for script in soup.find_all('script'):
                text = script.string or ''
                if '"entries"' in text and '"event"' in text:
                    start = text.find('{"data"')
                    if start == -1:
                        continue
                    end = text.rfind('}') + 1
                    data = json.loads(text[start:end])
                    entries = data.get('data', {}).get('entries', [])
                    break

            if not entries:
                logger.warning("No calendar entries found in Finviz response")
                return []

            # Filter to current week range
            start_date, end_date = self.get_week_range()

            events = []
            for entry in entries:
                event_name = entry.get('event', '')
                if not event_name:
                    continue

                # Parse date: "2026-02-02T10:00:00"
                date_raw = entry.get('date', '')
                if not date_raw:
                    continue

                try:
                    dt = datetime.fromisoformat(date_raw)
                except (ValueError, TypeError):
                    continue

                # Filter to week range
                if not (start_date.date() <= dt.date() <= end_date.date()):
                    continue

                date_str = dt.strftime('%Y-%m-%d')
                time_str = dt.strftime('%H:%M') if not entry.get('allDay') else ''

                # Map Finviz importance (1-3) to our impact levels
                importance = entry.get('importance', 1)
                if importance >= 3:
                    impact = 'high'
                elif importance >= 2:
                    impact = 'medium'
                else:
                    impact = 'low'

                # Also check our keyword lists (catches events Finviz may underrate)
                keyword_impact = self._classify_impact(event_name)
                if keyword_impact == 'high':
                    impact = 'high'
                elif keyword_impact == 'medium' and impact == 'low':
                    impact = 'medium'

                translated = self._translate_event(event_name)

                # Append reference period if available (e.g., "Jan")
                reference = entry.get('reference')
                if reference:
                    translated = f"{translated} [{reference}]"

                forecast = self._clean_value(entry.get('forecast'))
                previous = self._clean_value(entry.get('previous'))
                actual = self._clean_value(entry.get('actual'))

                events.append({
                    'date': date_str,
                    'time': time_str,
                    'event': translated,
                    'impact': impact,
                    'type': 'Economic',
                    'forecast': forecast,
                    'previous': previous,
                    'actual': actual,
                    'ticker': None,
                    'ai_outlook': None,
                })

            logger.info(f"✅ Found {len(events)} economic events from Finviz")
            return events

        except Exception as e:
            logger.error(f"Failed to fetch Finviz calendar: {e}")
            return []

    def get_earnings_calendar(self) -> List[Dict]:
        """Check earnings for watchlist stocks via yfinance"""
        logger.info(f"📊 Checking earnings for {len(self.watchlist)} stocks...")

        earnings = []
        start_date, end_date = self.get_week_range()
        end_extended = end_date + timedelta(days=7)  # Look 2 weeks ahead
        seen = set()

        for ticker in self.watchlist:
            if ticker in seen:
                continue

            try:
                stock = yf.Ticker(ticker)
                next_date = None

                # Method 1: get_earnings_dates (more reliable)
                try:
                    ed = stock.get_earnings_dates(limit=4)
                    if ed is not None and not ed.empty:
                        for dt_idx in ed.index:
                            nd = dt_idx.date() if hasattr(dt_idx, 'date') else dt_idx
                            if start_date.date() <= nd <= end_extended.date():
                                next_date = nd
                                break
                except Exception:
                    pass

                # Method 2: calendar attribute (fallback)
                if not next_date:
                    try:
                        cal = stock.calendar
                        if cal:
                            dates = cal.get('Earnings Date', [])
                            if dates:
                                d = dates[0]
                                nd = d.date() if isinstance(d, datetime) else d
                                if start_date.date() <= nd <= end_extended.date():
                                    next_date = nd
                    except Exception:
                        pass

                if next_date:
                    seen.add(ticker)

                    # Fetch stock info for context
                    sector = ''
                    mkt_cap_str = ''
                    try:
                        info = stock.info or {}
                        sector = info.get('sector', '')
                        mkt_cap = info.get('marketCap', 0)
                        if mkt_cap > 1e12:
                            mkt_cap_str = f"${mkt_cap / 1e12:.1f}T"
                        elif mkt_cap > 1e9:
                            mkt_cap_str = f"${mkt_cap / 1e9:.1f}B"
                    except Exception:
                        pass

                    ai_outlook = None
                    parts = [p for p in [sector, f"시가총액 {mkt_cap_str}" if mkt_cap_str else ''] if p]
                    if parts:
                        ai_outlook = ' | '.join(parts)

                    earnings.append({
                        'date': next_date.strftime('%Y-%m-%d'),
                        'time': '',
                        'event': f"{ticker} Earnings",
                        'impact': 'high',
                        'type': 'Earnings',
                        'forecast': None,
                        'previous': None,
                        'actual': None,
                        'ticker': ticker,
                        'ai_outlook': ai_outlook,
                    })

            except Exception:
                continue

        logger.info(f"✅ Found {len(earnings)} upcoming earnings")
        return earnings

    def generate_calendar(self) -> Dict:
        """Generate full calendar combining economic events and earnings"""
        start, end = self.get_week_range()

        economic = self.get_economic_events()
        earnings = self.get_earnings_calendar()

        all_events = economic + earnings
        all_events.sort(key=lambda x: (x['date'], x['time'] or 'ZZ'))

        output = {
            'week_start': start.strftime('%Y-%m-%d'),
            'week_end': end.strftime('%Y-%m-%d'),
            'updated': datetime.now().isoformat(),
            'events': all_events,
        }

        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ Saved weekly calendar to {self.output_file} ({len(all_events)} events)")
        return output


class EventAISummarizer:
    """Generate AI summaries for high-impact economic events"""

    def __init__(self):
        self.api_key = os.getenv('GOOGLE_API_KEY')
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

    def get_event_news(self, event_name: str, limit: int = 3) -> List[Dict]:
        """Fetch recent headlines related to an economic event"""
        news = []
        try:
            search_query = event_name
            # Strip Korean/emoji prefixes for cleaner search
            for ch in ['🇺🇸', '🗣️', '📊']:
                search_query = search_query.replace(ch, '')
            # Use the English name if available (in parentheses)
            if '(' in search_query and ')' in search_query:
                search_query = search_query.split('(')[1].split(')')[0]
            search_query = search_query.strip()

            headers = {'User-Agent': 'Mozilla/5.0'}
            url = (f"https://news.google.com/rss/search?"
                   f"q={quote(search_query + ' market impact')}&hl=en-US&gl=US&ceid=US:en")

            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                for item in root.findall('.//item')[:limit]:
                    title = item.find('title')
                    if title is not None:
                        news.append({'title': title.text})
        except Exception as e:
            logger.debug(f"News fetch error for {event_name}: {e}")
        return news

    def summarize_event(self, event_name: str, context: str) -> Optional[str]:
        """Generate AI summary for an economic event"""
        if not self.api_key:
            return None

        news = self.get_event_news(event_name)
        news_text = '\n'.join([n['title'] for n in news]) if news else 'No recent news available.'

        prompt = f"""You are a financial analyst. Analyze this economic event and provide a brief market outlook.

Event: {event_name}
Data: {context}
Recent Headlines:
{news_text}

Provide a 2-3 sentence summary in Korean covering:
1. What this event means for markets
2. Current market expectations or concerns

Format: Just the summary, no titles or bullet points. Be concise and actionable."""

        try:
            response = requests.post(
                f"{self.base_url}?key={self.api_key}",
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 1500
                    }
                },
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                candidates = result.get('candidates', [])
                if candidates:
                    content = candidates[0].get('content', {})
                    parts = content.get('parts', [])
                    if parts:
                        text = parts[0].get('text', '').strip()
                        if text:
                            return text
            else:
                logger.warning(f"Gemini API error {response.status_code}")
        except Exception as e:
            logger.warning(f"AI summary error for {event_name}: {e}")
        return None

    def enrich_high_impact_events(self, events: List[Dict]) -> List[Dict]:
        """Add AI summaries to high-impact economic events"""
        logger.info("🤖 Generating AI summaries for high-impact events...")

        for event in events:
            if event.get('impact') == 'high' and event.get('type') != 'Earnings':
                context = (f"Forecast: {event.get('forecast') or 'N/A'}, "
                           f"Previous: {event.get('previous') or 'N/A'}")
                summary = self.summarize_event(event['event'], context)
                if summary:
                    existing = event.get('ai_outlook') or ''
                    event['ai_outlook'] = f"{existing}\n{summary}".strip() if existing else summary
                time.sleep(1)  # Rate limit

        return events


def main():
    calendar = EconomicCalendar()
    data = calendar.generate_calendar()

    # Add AI summaries for high-impact events
    if os.getenv('GOOGLE_API_KEY'):
        summarizer = EventAISummarizer()
        data['events'] = summarizer.enrich_high_impact_events(data['events'])

        with open(calendar.output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("✨ AI summaries added for high-impact events")

    print("\n" + "=" * 60)
    print("📅 THIS WEEK'S CALENDAR")
    print(f"   {data['week_start']} ~ {data['week_end']}")
    print("=" * 60)

    econ_count = len([e for e in data['events'] if e['type'] == 'Economic'])
    earn_count = len([e for e in data['events'] if e['type'] == 'Earnings'])
    print(f"   📊 Economic events: {econ_count}")
    print(f"   💰 Earnings: {earn_count}")

    if data['events']:
        current_date = None
        for event in data['events']:
            if event['date'] != current_date:
                current_date = event['date']
                print(f"\n  [{current_date}]")
            impact_icon = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}.get(event['impact'], '⚪')
            time_str = f" {event['time']}" if event['time'] else ''
            print(f"    {impact_icon}{time_str} {event['event']}")
            if event.get('forecast'):
                print(f"       Exp: {event['forecast']}  Prev: {event.get('previous', 'N/A')}")
    else:
        print("\n  No events found for this week.")


if __name__ == "__main__":
    main()
