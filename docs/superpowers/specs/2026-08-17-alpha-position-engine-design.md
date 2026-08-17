# Alpha Position Engine — 알파캐치형 완결 시그널 + AI Brain 대시보드 심플화

2026-08-17 · 승인됨 (알파캐치 최근접 구성 / 알파캐치식+CIO 청산 / 텔레그램 개인봇+구독자 대시보드 / 장중 레이어 1단계 포함 / 대시보드 심플 리디자인)

## 배경

키움 알파캐치(kiwoom.com/inv/roboMarket/AX/introduce) 분석 결과, 본질은 "따라할 수 있는
완결 신호": 아침 스코어 상위 → 장중 체크 → 마감 매수/매도 신호 → 저녁 성과 브리핑, 그리고
목표가/최대 8거래일 보유 규칙과 30일 완결 매매 성과 공개. MarketFlow AI Brain 은 검출
(STEP1~4)은 더 깊게 갖췄으나 STEP5(매매 완결 루프)가 없다.

## 1. 가상 포지션 수명주기 — `app/services/mirofish/paper_positions.py` (신규)

- 진입: TOP3(CIO BUY)/매수유력 검출 → 가상 진입 대기 → **다음 거래일 시가** 체결
  (lookahead-safe). 가격 소스: `data/daily_prices.csv`. 종목당 동시 1포지션.
- 청산 규칙 (env 조정, 기본값):
  - 목표가 `MIROFISH_PAPER_TARGET_PCT` (기본 +8%)
  - 손절 `MIROFISH_PAPER_STOP_PCT` (기본 -7%)
  - 보유 만료 `MIROFISH_PAPER_MAX_DAYS` (기본 8거래일) → 종가 청산
  - CIO 판정 SELL 전환 → 조기 청산
- 원장: `data/admin_mirofish/paper_positions.json` — open[] / closed[] (진입일/진입가/
  청산일/청산가/수익률/보유일/청산사유/검출 run_id). atomic write(재시도 패턴 재사용).
- 킬스위치 `MIROFISH_PAPER_DISABLED`. 기존 스코어링·검출 로직 무변경(읽기 전용 소비).

## 2. 장중 포지션 감시 (1단계 포함 — 키움/KIS 키 보유 확인됨)

- 장중(평일 09:00~15:30) 5~10분 주기로 보유 포지션 현재가 조회
- 시세: KIS 우선(주도주LIVE 검증 인프라) → 키움 REST(`KIWOOM_APP_KEY/SECRET`) 폴백
- 고가 기준 목표가 도달 → 즉시 익절 신호 / 저가 기준 손절 터치 → 즉시 손절 신호
- 같은 포지션 중복 신호 방지(1회 발행 후 원장 마감)

## 3. 일일 타임라인 (스케줄러, 평일)

| 시각 | 작업 | 내용 |
|------|------|------|
| 08:30 | alpha_morning_top | 최신 스캐너 run 상위 종목 + 시장 4국면 라벨 → 텔레그램 |
| 장중 | alpha_intraday_watch | §2 감시 (스케줄 슬롯 다수 또는 폴링 잡) |
| 15:00 | alpha_close_signals | 신규 검출 진입 확정 + 만료/CIO 청산 평가 → 매매신호 텔레그램 |
| 18:00 | alpha_performance_brief | 보유 현황 + 30일 완결 성과(승률/누적/평균수익) → 텔레그램 |

- 발송: 개인봇(@bitman75_bot)만. 정규 스케줄 + 놓친-복구 목록 양쪽 등록.
- 조간 시장정리는 기존 09:05 브리핑 재사용(무변경).

## 4. 시장국면 4단계 (regime.py 경량 확장)

breadth + RS 상위 집중도로: 상승 추세 확산 / 주도주 장세 / 하락 국면 / 반등 초입.
기존 RISK_ON/NEUTRAL/RISK_OFF 소비자는 무변경 — 4국면은 부가 라벨(`phase`)로 병기.

## 5. AI Brain 구독자 대시보드 — 심플 리디자인 (`/dashboard/ai-bain`)

원칙: **사용자에게 필요한 정보만, 콘솔형 복잡성은 백그라운드로.**

- 상단 히어로: 오늘의 시장 4국면 + 한줄 요약
- ① **오늘의 신호** — 신규 진입/청산 신호 (없으면 "오늘 신호 없음")
- ② **보유 중 포지션** — 종목/진입가/현재수익률/보유 D-day/목표·손절선
- ③ **성과 원장** — 30일 승률·누적·평균수익 + 최근 청산 목록(사유 표기)
- ④ 검출 Top3 (기존 카드 유지, 간소화)
- 기존 성과검증/학습 피드백 카드는 접힘(collapsed) 섹션으로 강등 — 원하면 펼쳐보기
- 가상 매매 면책 문구 상시 표기
- API: `GET /api/admin/mirofish/paper/overview` (`@admin_or_aibain_required`) —
  positions/signals/performance/phase 한 번에

## 6. 검증·배포

- pytest: 진입(다음날 시가) / 청산 4규칙 / 중복 방지 / 원장 무결성 / lookahead 금지
  (진입일 데이터만으로 판단) / 스케줄 등록 양쪽 / API 게이팅
- 실데이터 dry-run: 최근 TOP3 검출로 원장 시뮬레이션 → 결과 육안 확인
  (feedback_inspect_the_output_not_just_stats)
- 배포: 커밋 → CF Pages(프론트) → miniPC pull + 재부팅 → 타임라인 실발송 확인

## 비범위

실주문 자동 집행(신호까지만), 스코어 4뷰(트렌드/섹터/팩터 차트), 공개 페이지 노출.
