# Goodrich TradingOS × AI Brain 통합 설계

## 목표

AI Brain 메뉴 안에 Goodrich의 KIS 기반 AI 펀드매니저를 독립 페이지로 제공한다.
MarketFlow는 Goodrich가 확정한 종목, 가격, 순위, 목표가, 손절가를 변경하지 않는다.

## 서비스 경계

```text
AI Brain 구독자
  -> MarketFlow React (/dashboard/ai-bain/goodrich)
  -> MarketFlow Flask 인증 경계 (/api/admin/mirofish/goodrich/*)
  -> Goodrich FastAPI (/v1/fund-manager*)
  -> KIS + 결정론적 점수/가격 규칙
  -> OpenAI 검증 설명
```

- Goodrich는 시장 사실, TOP 3, 목표가·손절가의 단일 소유자다.
- MarketFlow는 구독 권한, 타임아웃, 최소 응답 계약, 안전한 오류 메시지를 담당한다.
- OpenAI는 확정 후보의 설명만 담당하며 종목이나 숫자를 생성하지 않는다.
- 자동 주문 및 브로커 주문 API는 연결하지 않는다.

## MarketFlow 엔드포인트

| 메서드 | 경로 | 역할 |
|---|---|---|
| GET | `/api/admin/mirofish/goodrich/fund-manager` | 활성 TOP 3 조회 및 Goodrich 감시 결과 중계 |
| POST | `/api/admin/mirofish/goodrich/fund-manager/research` | 신규 KIS 정량 분석 및 OpenAI 설명 실행 |

두 엔드포인트 모두 관리자 또는 활성 AI Brain 구독자 인증이 필요하다.
Goodrich 주소는 `GOODRICH_API_BASE_URL`로 설정하며 기본값은 로컬
`http://127.0.0.1:8000`이다.

## 응답 계약

원본 Goodrich 응답을 보존하고 `integration` 메타데이터를 추가한다.

- `service`: `goodrich-tradingos`
- `source`: `goodrich-api`
- `fetched_at`: MarketFlow 수신 시각
- `universe`: `fixed-6`
- `ranking_owner`: `goodrich-deterministic-rules`
- `ai_role`: `verified-explanation-only`
- `ordering_enabled`: `false`

MarketFlow는 `picks`가 배열인지, 각 후보에 `symbol`과 `name`이 있는지 확인한다.
원본 오류 본문이나 자격증명은 사용자 응답에 포함하지 않는다.

## 화면 설계

- 헤더: 서비스명, KIS/규칙/OpenAI 역할, 수동 재분석
- 운영 메타: 고정 6종목, 결정론적 순위, 주문 비활성
- 시장 브리프: Goodrich OpenAI 시장 요약
- TOP 3 카드: 종목 식별자, 정량 점수, 현재가, 진입 기준, 목표가, 손절가
- 설명: 검증된 강점과 핵심 위험
- 하단 고지: 전체 시장 스캔이 아니라 고정 6종목 유니버스임을 명시

## 장애와 안전

- 연결 실패: HTTP 503
- 업스트림 시간 초과: HTTP 504
- 잘못된 JSON/계약 위반: HTTP 502
- POST 리서치 제한시간: 90초
- 프런트 POST 제한시간: 100초
- 실 KIS/OpenAI 검증과 배포는 별도 운영 작업에서 수행한다.

## 다음 확장

1. Goodrich 서비스 상태/최근 성공 시각 엔드포인트
2. 사용자별 리서치 실행 쿨다운과 일일 비용 제한
3. 실행 ID, 소요시간, KIS/OpenAI 상태를 포함한 추적 메타데이터
4. 전체 시장 유니버스 확대 전 성과 추적과 look-ahead-free 평가
