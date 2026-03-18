# CryptoAnalytics

AI 기반 암호화폐 시장 분석 플랫폼

## 기능

- **Market Briefing** — BTC/ETH 시장 현황, Fear & Greed, 펀딩비율
- **VCP Signals** — 암호화폐 VCP 패턴 스캐너
- **AI Prediction** — ML 기반 가격 예측
- **Risk Analysis** — 포트폴리오 리스크 분석
- **Lead-Lag Analysis** — BTC vs 매크로 상관관계

## 실행 방법

### Backend

```bash
# 가상환경 생성
python -m venv .venv
source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일 편집하여 API 키 입력

# 서버 실행
python run.py
# http://localhost:5001
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# http://localhost:3000
```

### 테스트

```bash
# Backend 테스트
python -m pytest tests/ -v

# Frontend 테스트
cd frontend && npm test
```

## 기술 스택

- **Backend**: Flask, SQLAlchemy, SQLite
- **Frontend**: Next.js 15, TypeScript, TailwindCSS
- **ML**: scikit-learn, pandas, numpy
- **Data**: ccxt, yfinance, fredapi
- **Auth**: JWT (Flask) + NextAuth
- **Payment**: Stripe
