# 검출 신호와 뉴스 사건 연결 계약

## 목적과 확인된 문제

사용자는 SK하이닉스의 검출 이후 나온 호재성 보도가 검출 신호와 어떤 관계인지 재점검하고 파이프라인을 개선하도록 요청했다. 하락 추세만으로 후보를 제외하거나 나중의 호재를 원래 선정 이유로 소급하지 않는다.

2026-10-07 18:46 KST 최초 결정 기록 전에 공개 RSS 원장은 오전의 SK하이닉스 저평가 보도를 실제 수집했다. 현재 AlphaLab은 가격과 과거 순손익으로 후보를 선정하며 이 뉴스 원장과 연결되지 않는다. 뉴스 확인과 가격 검출의 시간 관계를 재현할 수 있는 별도 저장 계층을 추가한다.

## 변경 범위와 불변 조건

- 뉴스는 공개 RSS/옴니 원장을 사용하고 공식 연합뉴스 산업 피드 하나를 보완한다. 유료 API·새 키·LLM·실주문을 추가하지 않는다.
- AlphaLab의 최초 결정, 종목·순위·Kelly·참고 가격·유효기간·과거 전향 기록은 그대로 보존한다.
- `catalyst_context`는 status 응답의 선택 필드다. 본문은 고정 결정의 세 식별자에 귀속한다.
- GET은 저장된 sidecar만 읽는다. DB 초기화·RSS 호출·연구 실행·쓰기·알림은 하지 않는다.
- 뉴스 수집 성공 후 별도 갱신하며 실패 시 이전 결과를 보존한다. 뉴스 갱신 실패는 기존 연구 성공을 취소하지 않는다.
- 일반 뉴스는 보조 맥락이다. source grade·매체 수·단어 점수를 검증된 승률이나 CIO 승인으로 승격하지 않는다.
- 종목별 비교 패널에는 제목에 정확한 기업명 또는 종목 코드가 명시된 기사만 표시한다. 다른 회사 기사 본문의 단순 언급을 해당 종목 자체의 호재로 표시하지 않는다. 원장의 본문 연관 기록은 삭제하지 않는다.

## 공개 인터페이스

`catalyst_context` 필드의 공통 스키마는 다음과 같다.

- `schema_version=1`, `policy_version='alpha-catalyst-context-v1'`.
- `decision_id`, `input_fingerprint`, `source_audit_hash`, `decision_at`, `captured_at`, `snapshot_id`.
- `status='ready'|'unavailable'`, `used_in_selection=false`, `association_status='unproven'`.
- `rows`는 기존 후보와 같은 순서로 최대 세 개다.
- 각 행은 `symbol`, `name`, `first_detected_at`, `first_decision_id`, `events`를 포함한다.
- 사건은 최대 8개이며 `event_id`, `event_group`, `title`, `url`, `source`, `grade`, `published_at`, `collected_at`, `stage`, `polarity`, `timing`을 포함한다.
- `polarity='supportive'|'adverse'|'mixed'|'unknown'`.
- `timing='captured_before_first'|'published_before_captured_after'|'reported_after_first'`.
- `stage='valuation_opinion'|'site_inspection'|'infrastructure'|'investment'|'contract'|'earnings'|'other'`.
- `validation`는 `status='collecting'`, `hypothesis='price_setup_leads_catalyst_72h_v1'`, `horizon_hours=72`, `started_at`, `enrolled_decisions`, `matured_decisions=0`, `coincidence_rejected=false`를 제공한다. 관측 성과가 없으면 수익·확률·사건 발생률을 계산하지 않는다.

역사적 최초 결정 시각은 무결성 검사를 통과한 issued journal로부터 얻는다. 원장의 발행 시각과 실제 최초 수집 시각을 분리한다. URL의 숫자나 파일 수정 시각으로 기사 발행 시각을 만들어내지 않는다. 이후 수집한 과거 기사를 당시 모델이 사용한 것처럼 표시하지 않는다.

원문 URL·해시로 동일 기사 중복을 제거한다. 표시가 8개를 넘으면 사전 수집·사후 수집 각각 최근 4개를 우선 보존하고, 한쪽 자료가 적으면 남은 자리를 다른 최근 기사로 채워 시간순으로 표시한다. 원장은 종목별 최근 256개와 최초 결정 이전 256개의 제한된 구간을 함께 읽어 후속 보도 누적으로 사전 기록이 밀려나지 않게 한다. 각 기사 자체의 최초 수집 시각은 바꾸지 않는다. 사건 그룹은 종목·주제·날짜·일부 장소를 사용한 설명용 묶음이며, 동일 사건이나 전재 관계를 확정하지 않는다. 기사 수와 그룹 수를 독립 호재 수로 집계하지 않는다. 이후 성과 평가에는 사건 동일성의 별도 검증이 필요하다. 부지 점검과 투자 확정, 수주 성공과 실패, 실적 발표와 이익 감소, 위험의 발생과 해소를 구분한다.

## 전향 검증

첫 명시적 갱신 시점에 가설·72시간 구간·현재 정책을 고정한다. 그 시점 이전 결정은 역사 조사이며 전향 성공 사례에 넣지 않는다. 이후 새 결정에는 선택 종목과 같은 품질 유니버스의 비선정 대조 종목을 함께 고정한다. 원본 입력 지문과 코호트를 보존해 나중에 유리한 종목이나 기간만 골라 바꾸지 못하게 한다.

현재 릴리스는 전향 관측의 등록과 자료 보존까지 연결한다. 단일 SK하이닉스 사례로 통계적 비우연성이나 수익 예측 능력을 확정하지 않는다. 대조 관측·뉴스 수집 공백·비용 반영 순손익이 성숙하기 전에는 성과 지표를 미산출로 남긴다.

## 완료 검증

중복 뉴스, 사건 충돌, 미래·시간대 누락, 재수집, 다른 결정의 sidecar, 실패 후 보존, GET 무쓰기, 기존 결정·가격·Kelly·승인 불변을 검사한다. 실제 MiniPC의 저장 가격·뉴스 원장을 연결해 SK하이닉스의 사전·사후 뉴스 시각을 확인한다. 관련 백엔드·프론트 테스트, 빌드와 CI를 통과한 버전만 배포하고 건강 상태와 실제 표시를 확인한다.
