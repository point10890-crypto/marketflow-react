# 급등 이유 역추적

사용자 요청: 급등한 종목을 출발점으로 상승 재료를 찾는 시스템을 추가한다.
기존 연속 구현·검증·배포 위임 범위로 진행한다. 주문, 새 유료 모델, 권한 확대는 없다.

## 결정한 범위

- 현재 KIS Screener 저장 candidate_pool에서 +5% 이상, 거래대금 20억 원 이상인 실제 KOSPI/KOSDAQ 종목을 최대 20개 감시한다. 이는 설명 대상 선정이며 매수 추천 필터가 아니다. 새 시세 스캔을 호출하지 않는다.
- 세션·종목별 최초 관측 가격/시각/등락률을 봉인한다. 처음 본 시각을 실제 급등 시작이라고 부르지 않는다. 과거 세션은 과거 관측으로 명시한다.
- Omni 다중 언론사 원장, 독립 제갈공명 기사, OpenDART 기업 공시를 역조회한다. 부족한 뉴스는 해당 회사명 Google News RSS 검색 1회로 보완한다. 정확한 회사 연결을 검증하고 발표·수신 시각을 분리한다.
- 7일 조회 창, 조회 건수/시간/응답 크기 제한, 완료 단계 캐시, 실패 단계만 재시도. 공시의 날짜만 알 때 당일 발표 선후는 미확인이다. 검색 결과와 출처 수가 독립 증거 개수라는 뜻은 아니다.
- 기사 제목에 명시된 사건을 유력 재료 후보/사후 보도/원인 미확인으로 구분한다. 위험·부정 재료도 함께 표시한다. 인과관계 입증·수익 확률·매수 승인으로 승격하지 않는다.
- 무료 규칙 분석과 기존 출처를 사용한다. 다중 에이전트 유료 예산과 분리하며 LLM 추가 호출은 없다.
- 별도 5분 예약 작업으로 수집하고 GET는 저장 결과만 읽는다. 기존 시세 producer, AlphaLab 첫 결정/순위/손익 원장에 쓰지 않는다.
- 제갈공명 뉴스·재료 검증 페이지 상단에 모바일 우선 카드. 종목 검색, 실제 상승 관측, 유력 재료 한 문장, 발표/관측/수신 시각, 원문 링크, 추가 확인 및 수집 오류를 보여준다.

## 공개 계약

`GET /api/admin/mirofish/kongming/surge-traces`: 기존 admin 또는 Kongming bundle, private/no-store, 추가 권한 없음.
응답: `schema_version:1,status,generated_at,source_as_of,threshold:{change_pct:5,trading_value:2000000000},items:[],operation:{state,last_run_at,source_status,processed,pending}`.
행: `id,symbol,name,market,session,first_detected_at,price_observed_at,price,change_pct,trading_value,status,summary,evidence:[],checks:[],limitations:[]`.
증거: `id,kind(news|disclosure),title,url,source,publisher,published_at,published_precision(timestamp|date|unknown),first_received_at,timing(before_observation|after_observation|same_day_unknown|unknown),discovered_after_observation,category,direction(positive|negative|neutral|mixed),verification,duplicate_count`.
체크: `source,status,checked_at,count`. Nullable fields explicitly null. 의미 있는 사건 미발견과 출처 실패는 구분한다. UI는 미확인/부분 결과를 숨기지 않는다.

## 검증

시간 역행·미래 기사·이름 충돌·중복·동일 세션 재실행·조회 실패·출처 stale·paper quote·비회원 차단·GET 무부작용·모바일 가로 넘침·실제 운영 결과를 검사한다. 새 후보가 없으면 그 사실을 보고하며 fixture를 실데이터로 가장하지 않는다.
