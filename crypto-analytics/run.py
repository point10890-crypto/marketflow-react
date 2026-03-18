#!/usr/bin/env python3
"""
CryptoAnalytics Flask 애플리케이션 진입점
Usage: python run.py
"""

from app import create_app

app = create_app()

if __name__ == '__main__':
    print("\n" + "="*50)
    print("CryptoAnalytics Server Starting")
    print("="*50 + "\n")

    app.run(
        host='0.0.0.0',
        port=5001,
        debug=True,
        use_reloader=False
    )
