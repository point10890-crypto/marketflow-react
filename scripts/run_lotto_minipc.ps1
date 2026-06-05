# Run lotto_analysis.py on miniPC against local Flask (production)
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& C:\bitman_marketfloww\.venv\Scripts\python.exe C:\bitman_marketfloww\scripts\lotto_analysis.py
