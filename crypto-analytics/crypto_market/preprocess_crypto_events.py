import os
import re
import json
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Gemini API
GENAI_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GENAI_API_KEY:
    print("Error: GOOGLE_API_KEY not found in environment variables.")
    exit(1)

genai.configure(api_key=GENAI_API_KEY)

REPORTS_DIR = os.path.join("crypto_market", "crypto_monthly_reports")
OUTPUT_FILE = os.path.join("crypto_market", "timeline_events.json")

import time

def process_report_with_llm(filename, content):
    """
    Uses Gemini to extract the single most impactful event for Bitcoin from the report.
    """
    model = genai.GenerativeModel("gemini-2.0-flash-exp")  # Use a fast, capable model

    prompt = f"""
    You are a professional crypto market analyst.
    Below is a monthly report for the crypto market.
    
    Your task is to identify the SINGLE most impactful event that affected Bitcoin's price during this month.
    Extract a short, punchy title (max 5-6 words) and a 1-sentence summary.
    Provide the output in both English and Korean.
    Determine the sentiment (positive, negative, or neutral) specifically for Bitcoin.

    REPORT CONTENT:
    {content}

    OUTPUT FORMAT (JSON only):
    {{
        "en_title": "Title in English",
        "ko_title": "한국어 제목",
        "en_summary": "One sentence summary in English.",
        "ko_summary": "한국어 요약 한 문장.",
        "type": "positive/negative/neutral"
    }}
    """
    
    # Simple retry mechanism with backoff
    max_retries = 3
    base_delay = 10  # Start with 10 seconds delay between requests to be safe (RPM limit is usually 10-15)
    
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            # specialized cleaning for json
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:-3]
            elif text.startswith("```"):
                text = text[3:-3]
            
            # Successful call, sleep to respect rate limit before returning
            print(f"    (Success, sleeping {base_delay}s...)")
            time.sleep(base_delay)
            return json.loads(text)
            
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                wait_time = (attempt + 1) * 20
                print(f"    [429 Quota Exceeded] Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"Error processing {filename}: {e}")
                return None
    return None

def main():
    if not os.path.exists(REPORTS_DIR):
        print(f"Directory {REPORTS_DIR} not found.")
        return

    all_events = {}
    
    # Load existing if available to avoid re-processing everything each time (optional, can be fully overwritten)
    # For now, let's overwrite to ensure fresh LLM insights
    
    files = sorted([f for f in os.listdir(REPORTS_DIR) if f.endswith(".md")])
    print(f"Found {len(files)} reports. Starting LLM processing...")

    for filename in files:
        # Extract YYYY-MM
        match = re.match(r"(\d{4}-\d{2})\.md", filename)
        if not match: continue
        date_key = match.group(1) # e.g., "2024-05"

        print(f"Processing {filename}...")
        
        with open(os.path.join(REPORTS_DIR, filename), "r", encoding="utf-8") as f:
            content = f.read()
            
        event_data = process_report_with_llm(filename, content)
        
        if event_data:
            all_events[date_key] = event_data
            print(f"  -> Extracted: {event_data['en_title']}")
        else:
            print(f"  -> Failed to extract for {filename}")

    # Save to JSON
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_events, f, ensure_ascii=False, indent=2)
    
    print(f"\nSuccessfully saved {len(all_events)} events to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
