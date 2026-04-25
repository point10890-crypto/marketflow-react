# Run post_notice.py on miniPC against local Flask (production)
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$topic = '2026-04-25 업데이트 — Multi-AI v2 (Gemini+GPT-4o+Grok-4 합의) + Devil''s Advocate (Claude Haiku 4.5 리스크 검토) + W패턴 차트 모달 화면 95% 확대'
& C:\bitman_marketfloww\.venv\Scripts\python.exe C:\bitman_marketfloww\scripts\post_notice.py --topic $topic
