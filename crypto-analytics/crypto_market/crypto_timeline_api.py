import os
import re
import json
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

class CryptoTimelineService:
    def __init__(self, reports_dir):
        self.reports_dir = reports_dir

    def get_timeline_data(self):
        """
        Returns a dictionary containing:
        - prices: list of {time, value} objects (monthly)
        - events: list of {time, en_title, ko_title, en_summary, ko_summary, type} objects
        """
        # 1. Fetch Price Data (Last 2 years monthly)
        btc = yf.Ticker("BTC-USD")
        hist = btc.history(period="2y", interval="1mo")
        
        # If monthly data is too sparse, fallback to weekly to ensure a nice curve
        if len(hist) < 12:
            hist = btc.history(period="2y", interval="1wk")
        
        if hist.empty:
            # Absolute fallback
            hist = btc.history(period="5y", interval="1mo")
        
        prices = []
        for idx, row in hist.iterrows():
            prices.append({
                "time": idx.strftime("%Y-%m-%d"),
                "value": round(float(row['Close']), 2)
            })

        # 2. Load Preprocessed Events (LLM Enhanced)
        events = []
        events_file = os.path.join(os.path.dirname(__file__), 'timeline_events.json')
        
        preprocessed_data = {}
        if os.path.exists(events_file):
            try:
                with open(events_file, 'r', encoding='utf-8') as f:
                    preprocessed_data = json.load(f)
            except Exception as e:
                print(f"Error loading timeline_events.json: {e}")

        for filename in sorted(os.listdir(self.reports_dir)):
            if not filename.endswith(".md"):
                continue
            
            try:
                # Extract year-month from filename (e.g., 2025-12.md)
                match = re.match(r"(\d{4}-\d{2})\.md", filename)
                if not match: continue
                date_key = match.group(1) # "2025-12"
                date_str = date_key + "-01"
                
                # Find price at that month for chart placement
                matching_price = next((p['value'] for p in prices if p['time'].startswith(date_key)), None)
                
                # Use Preprocessed LLM Data if available
                if date_key in preprocessed_data:
                    ev = preprocessed_data[date_key]
                    events.append({
                        "time": date_str,
                        "en_title": ev.get('en_title', 'Monthly Update'),
                        "ko_title": ev.get('ko_title', '월간 업데이트'),
                        "en_summary": ev.get('en_summary', ''),
                        "ko_summary": ev.get('ko_summary', ''),
                        "type": ev.get('type', 'neutral'),
                        "price": float(matching_price) if matching_price is not None else None
                    })
                else: 
                    # Fallback to simple extraction (removed complex regex for speed)
                    events.append({
                        "time": date_str,
                        "en_title": "Monthly Update",
                        "ko_title": "월간 업데이트",
                        "en_summary": "Click to view full analysis.",
                        "ko_summary": "상세 분석을 보려면 클릭하세요.",
                        "type": "neutral",
                        "price": float(matching_price) if matching_price is not None else None
                    })
                    
            except Exception as e:
                print(f"Error processing {filename}: {e}")

        return {
            "prices": prices,
            "events": events
        }
