# Detection Alpha Lab — 실측 수익률 기반 검출 정밀화

2026-08-17 · 승인됨. 목적: "좋은 종목을 검출받아 실제 매매에서 좋은 결과" — 검출→수익
전 구간을 실측으로 조인다. 새 기능이 아니라 검출 품질 R&D.

## 배경

포지션 엔진(2026-08-17)으로 완결 매매 루프는 생겼지만, 수익률을 좌우하는 세 지점이
임의값이다: ①진입 게이트 없음(국면 무관 진입) ②고정 청산(+8/-7/8일 — 변동성 무시)
③손실 패턴 필터 없음. 프로덕션에 과거 워크플로우 ~1,172개(수개월 검출 이력)가 있어
"우리 검출이 실제로 얼마나 버는가"를 실측할 수 있다.

## 1. 히스토리컬 리플레이 하네스 — `app/services/mirofish/detection_lab.py`

- `collect_historical_detections()` — workflows 디렉토리 전수 스캔 → CIO BUY 검출
  목록 [(detected_date, symbol, name, score)]. 같은 날 중복 심볼은 1건.
- `replay(detections, price_series, rules)` — 시간순 리플레이:
  - 진입: 검출 다음 거래일 시가 (라이브 엔진과 동일, lookahead-safe)
  - 동시 보유 중 심볼 재검출 무시 (라이브와 동일)
  - 청산: rules 에 따라 (아래 2절) — 같은 봉 손절·익절 동시 관통 시 손절 우선
- 산출 지표: trades / win_rate / expectancy(평균 수익률) / median / profit_factor /
  누적(복리) / equity MDD / 청산사유 분포 / **국면(phase)별 분해** / 보유일 분포
- 픽 목록 출력 — 통계만 보지 않고 뽑힌 종목·날짜·수익률을 육안 검증
  (2026-08-01 Goodrich 교훈: 결함은 목록에서만 보인다)

## 2. 규칙 변형 (RuleSet) — A/B 후보

baseline: 현행 (게이트 없음, 고정 +8/-7/8거래일)

- **V1 레짐 게이트**: 검출일의 4국면이 '하락 국면'이면 진입 스킵
  (regime timeline by_date — lookahead-safe)
- **V2 주봉 Stage-2 필터**: 검출일 기준 종가 > 150일 MA(≈30주선) AND 150MA(당일) >
  150MA(20거래일 전) 일 때만 진입 — 미너비니 Stage 2. 검출일까지 데이터만 사용
- **V3 ATR 동적 청산**: 고정 ±% 대신 목표 = 진입가 + 2.0×ATR14, 손절 = 진입가 −
  1.5×ATR14 (ATR 은 진입 전일까지 14일 TR 평균). 보유 만료 8거래일 유지
- 조합(V1+V2, V1+V2+V3 등)도 같은 하네스로 평가

## 3. 판정 원칙

- 기준선 대비 expectancy 개선 + 표본 충분 + 픽 목록 육안 검증 통과한 변형만 반영
- 개선 없으면 정직하게 "반영 없음" 결론 (지난 백테스트와 동일 원칙)
- 반영 수단: 라이브 엔진은 env 기반이므로 파라미터형(V3)은 env, 게이트형(V1/V2)은
  paper_positions.ingest/settle 에 필터 훅 추가 후 env 로 on/off

## 4. 실행 환경

- 개발·테스트: 본PC (합성 데이터 TDD — 본PC daily_prices 는 구본이라 실측 불가)
- 실측: miniPC (`scripts/detection_lab_run.py` — 워크플로우+daily_prices 실데이터)
- 리포트: JSON + 요약 markdown (기준선 vs 변형 표 + 샘플 픽 목록)

## 5. 2단계 (표본 축적 후, 비범위)

손실 트레이드 공통 패턴 학습 → 하드 필터화. L3 수익 예측 모델 게이트 해제.
