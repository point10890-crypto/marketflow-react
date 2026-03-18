#!/usr/bin/env python3
"""
Regenerate Bitcoin Timeline Events using Gemini 2.0 Flash
Creates richer, more detailed monthly summaries
"""
import json
import os
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Use gemini-2.5-flash (fast and robust)
MODEL_NAME = "gemini-2.5-flash"

PROMPT_TEMPLATE = """당신은 암호화폐 시장 전문가입니다. 아래 기간에 대한 비트코인 시장 분석을 작성해주세요.

기간: {year}년 {month}월

분석 요구사항:
1. 해당 월의 주요 이벤트 (규제, ETF, 해킹, 거시경제 등)
2. 가격 움직임의 원인 분석
3. 시장 심리 및 투자자 행동
4. 다른 암호화폐(이더리움, 알트코인)와의 관계

응답 형식 (JSON):
{{
  "en_title": "영어 제목 (5-7 단어, 임팩트 있게)",
  "ko_title": "한글 제목 (임팩트 있는 짧은 문구)",
  "en_summary": "영어 요약 (3-4 문장, 상세하고 구체적인 내용)",
  "ko_summary": "한글 요약 (3-4 문장, 상세하고 구체적인 내용)",
  "type": "positive/negative/neutral/volatility"
}}

주의:
- 실제 역사적 사실에 기반해야 합니다
- 단순한 가격 언급이 아닌, WHY(원인)에 집중해주세요
- 구체적인 수치나 이벤트명을 포함하세요
- JSON 형식만 출력하세요
"""

def generate_event(year: int, month: int) -> dict:
    """Generate event description for a specific month"""
    model = genai.GenerativeModel(MODEL_NAME)
    
    prompt = PROMPT_TEMPLATE.format(year=year, month=month)
    
    # Safety settings to avoid blocking
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
    
    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0.7,
            "max_output_tokens": 1024,
        },
        safety_settings=safety_settings
    )
    
    # Parse JSON from response
    text = response.text.strip()
    
    # Remove markdown code block if present
    import re
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        text = json_match.group(0)
    
    # Fix common issues
    text = text.replace('\n', ' ').replace('\r', '')
    
    return json.loads(text)

def main():
    output_path = Path(__file__).parent / "timeline_events.json"
    
    # Load existing data
    if output_path.exists():
        with open(output_path, 'r', encoding='utf-8') as f:
            existing = json.load(f)
    else:
        existing = {}
    
    # Generate for 2024-01 to 2025-12 (24 months)
    import time
    
    for year in range(2024, 2026):
        for month in range(1, 13):
            key = f"{year}-{month:02d}"
            
            print(f"🔄 Generating {key}...")
            try:
                event = generate_event(year, month)
                existing[key] = event
                print(f"  ✅ {event.get('ko_title', 'OK')}")
                
                # Rate limit
                time.sleep(1)
                
            except Exception as e:
                print(f"  ❌ Error: {e}")
                continue
    
    # Save updated data
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Saved {len(existing)} events to {output_path}")

if __name__ == "__main__":
    main()
