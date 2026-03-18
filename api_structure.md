# MarketFlow API 구조 문서

본 문서는 `c:\bitman_service\app\routes\` 내에 정의된 Flask 기반의 MarketFlow 백엔드 API 라우팅 구조입니다.

## 1. 공통 및 시스템 (System)

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | 시스템 헬스 체크 (버전 및 상태 확인) |
| `/api/system/last-update` | GET | 데이터 최신 상태(Freshness) 확인 |
| `/api/scheduler/status` | GET | 스케줄러 상태 확인 |
| `/api/scheduler/trigger/<task>` | POST | 특정 스케줄러 작업 수동 트리거 |

## 2. 암호화폐 (Crypto - `/api/crypto`)

| Endpoint | Method | Description |
|---|---|---|
| `/api/crypto/vcp-signals` | GET | 코인 VCP(변동성 축소 패턴) 시그널 조회 |
| `/api/crypto/overview` | GET | 암호화폐 시장 요약 조회 |
| `/api/crypto/dominance` | GET | 비트코인 등 주요 코인 도미넌스 정보 |
| `/api/crypto/chart/<ticker>` | GET | 특정 코인 차트 데이터 조회 |
| `/api/crypto/gate-scan` | POST | 게이트 스캔 실행 |
| `/api/crypto/lead-lag/charts/list` | GET | 리드/래그 차트 리스트 조회 |
| `/api/crypto/lead-lag/charts/<path:filename>` | GET | 상세 리드/래그 차트 이미지 파일 서빙 |
| `/api/crypto/run-briefing` | POST | 브리핑 데이터 생성 수동 실행 |
| `/api/crypto/run-leadlag` | POST | 리드/래그 분석 수동 실행 |
| `/api/crypto/run-prediction` | POST | 예측 모델 수동 실행 |
| `/api/crypto/run-risk` | POST | 리스크 분석 수동 실행 |
| `/api/crypto/run-scan` | POST | 전체 스캔 수동 실행 |
| `/api/crypto/task-status` | GET | 크립토 백그라운드 작업 상태 확인 |

## 3. 경제 및 거시 지표 (Economy - `/api/econ`)

| Endpoint | Method | Description |
|---|---|---|
| `/api/econ/overview` | GET | 경제 지표 요약 |
| `/api/econ/summary` | POST | 전반적인 경제 상황 서머리 분석 |
| `/api/econ/fear-greed` | GET | 공포/탐욕 지수 조회 |
| `/api/econ/yield-curve` | GET | 수익률 곡선(Yield Curve) 조회 |
| `/api/econ/kr/indicators` | GET | 한국 경제 지표 목록 |
| `/api/econ/kr/sectors` | GET | 한국 섹터별 경제 현황 |
| `/api/econ/kr/sectors/history` | GET | 한국 섹터 과거 히스토리 |
| `/api/econ/kr/chart-data/<indicator>` | GET | 한국 특정 지표 차트 데이터 |
| `/api/econ/kr/sectors/score` | POST | 섹터별 점수 업데이트 |
| `/api/econ/us/indicators` | GET | 미국 경제 지표 목록 |
| `/api/econ/us/chart-data/<indicator>` | GET | 미국 특정 지표 차트 데이터 |
| `/api/econ/forecast/saved` | GET | 저장된 예측 데이터 조회 |

## 4. 한국 주식 (KR Market - `/api/kr`)

| Endpoint | Method | Description |
|---|---|---|
| `/api/kr/market-status` | GET | 한국 주식 시장 상태 |
| `/api/kr/market-gate` | GET | 마켓 게이트 (주요 지표 타깃 진입 여부) 판단 |
| `/api/kr/signals` | GET | 시장 포착 시그널 목록 |
| `/api/kr/stock-chart/<ticker>` | GET | 개별 한국 주식 차트 조회 |
| `/api/kr/performance` | GET | 시장 퍼포먼스 비교 |
| `/api/kr/cumulative-return` | GET | 누적 수익률 |
| `/api/kr/vcp-stats` | GET | VCP 종목 통계 |
| `/api/kr/vcp-history` | GET | 과거 VCP 데이터 히스토리 |
| `/api/kr/vcp-scan` | POST | VCP 패턴 ス캔 수동 실행 |
| `/api/kr/jongga-v2/latest` | GET | 종가 베팅(V2) 최신 데이터 |
| `/api/kr/jongga-v2/history/<date_str>` | GET | 특정 날짜 종가 베팅 데이터 조회 |
| `/api/kr/jongga-v2/dates` | GET | 종가 베팅 제공 날짜 목록 조회 |
| `/api/kr/jongga-v2/analyze` | POST | 단일 종목 종가 베팅 분석 실행 |
| `/api/kr/jongga-v2/run` | POST | 전체 종가 베팅 스캔 실행 |
| `/api/kr/ai-summary/<ticker>` | GET | AI 기반 개별 종목 요약 |
| `/api/kr/ai-analysis` | GET | 전체 시장 AI 분석 결과 |
| `/api/kr/ai-history-dates` | GET | AI 분석 과거 날짜 목록 |
| `/api/kr/ai-history/<date>` | GET | 특정 날짜 AI 분석 기록 |
| `/api/kr/realtime-prices` | POST | 실시간 가격 새로고침 |
| `/api/kr/update` | POST | 한국 시장 데이터 수동 업데이트 |

## 5. 미국 주식 (US Market - `/api/us`)

| Endpoint | Method | Description |
|---|---|---|
| `/api/us/market-gate` | GET | 미국장 마켓 게이트 판단 |
| `/api/us/market-briefing` | GET | 미국 시장 요약/브리핑 |
| `/api/us/data-status` | GET | 데이터 수집 및 업데이트 상태 |
| `/api/us/stock-chart/<ticker>` | GET | 개별 미국 주식 차트 데이터 |
| `/api/us/heatmap-data` | GET | 섹터/종목 히트맵 데이터 |
| `/api/us/calendar` | GET | 실적 및 경제 캘린더 |
| `/api/us/macro-analysis` | GET | 매크로(경제 환경) 분석 |
| `/api/us/market-regime` | GET | 현재 시장 체제(Regime) 판단 데이터 |
| `/api/us/sector-rotation` | GET | 섹터 로테이션 모델 |
| `/api/us/portfolio` | GET | 포트폴리오 메인 정보 |
| `/api/us/portfolio-performance` | GET | 포트폴리오 상세 성과 |
| `/api/us/cumulative-performance` | GET | 시장 누적 수익률 성과 |
| `/api/us/super-performance` | GET | 슈퍼 퍼포먼스(급등) 종목 목록 |
| `/api/us/top-picks-report` | GET | 추천 종목(Top Picks) 리포트 |
| `/api/us/decision-signal` | GET | 매수/매도 의사결정 시그널 |
| `/api/us/index-prediction` | GET | 지수 흐름 예측 모델 |
| `/api/us/risk-alerts` | GET | 주요 리스크 알림 정보 |
| `/api/us/track-record` | GET | 과거 수익률 트랙 레코드 |
| `/api/us/backtest` | GET | 백테스트 결과 |
| `/api/us/technical-indicators/<ticker>` | GET | 기술적 지표 상세 조회 |
| `/api/us/ai-summary/<ticker>` | GET | 미국 종목 AI 요약 정보 |
| `/api/us/smart-money` | GET | 기관 및 내부자(Smart Money) 자금 흐름 |
| `/api/us/smart-money/<ticker>/detail` | GET | 특정 종목 기관 흐름 상세 |
| `/api/us/institutional` | GET | 기관 투자자 현황 |
| `/api/us/insider-trading` | GET | 내부자 거래 목록 |
| `/api/us/etf-flows` | GET | 주요 ETF 자금 유출입 |
| `/api/us/options-flow` | GET | 옵션 시장 흐름 분석 |
| `/api/us/sec-filings` | GET | SEC 공시 정보 요약 |
| `/api/us/earnings-impact` | GET | 실적 발표 전후 주가 임팩트 분석 |
| `/api/us/earnings-transcripts` | GET | 실적 발표 어닝콜 트랜스크립트 분석 |
| `/api/us/news-analysis` | GET | 시장 주요 뉴스 AI 분석 |
| `/api/us/history-summary` | GET | 과거 시황 서머리 |
| `/api/us/history-dates` | GET | 시황 히스토리 제공 날짜 목록 |
| `/api/us/history/<date>` | GET | 특정 과거 날짜의 시황 정보 |
| `/api/us/history/<date>/performance` | GET | 특정 날짜의 시장 퍼포먼스 |

## 6. 주식 분석기 (Stock Analyzer - `/api/stock-analyzer`)

| Endpoint | Method | Description |
|---|---|---|
| `/api/stock-analyzer/search` | GET | 분석 대상 주식 검색 |
| `/api/stock-analyzer/analyze` | POST | 펀더멘탈/기술적 상세 분석 전송 |
| `/api/stock-analyzer/export` | POST | 분석 결과 히스토리 CSV 엑스포트 |

## 7. 결제 (Stripe - `/api/stripe`)

| Endpoint | Method | Description |
|---|---|---|
| `/api/stripe/create-checkout` | POST | Stripe 결제 세션(Checkout) 생성 |
| `/api/stripe/portal` | POST | 구독 관리 포털 이동 |
| `/api/stripe/webhook` | POST | 웹훅 (결제 완료, 취소 등 이벤트 처리) |

*본 문서는 Flask CLI의 `routes` 명령어를 통해 추출된 애플리케이션의 엔드포인트입니다.*
