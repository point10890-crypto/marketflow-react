# 운영 관제 센터 — 적용 계약 (2026-11-08)

관리자 메뉴의 **운영 관제 센터** (`/admin/control-center`)에서 서비스·데이터·예약 작업과 관제 실행기 상태를 조회한다. Flask와 독립된 Windows 예약 작업이 결과를 기록하며, 화면은 30초마다 저장 결과를 읽는다. 이 기능은 관측 도구이며 자동 복구나 매매 실행기가 아니다.

## 구현 범위와 한계

- 전체 Flask 경로는 DB 초기화·마이그레이션·백그라운드 워커가 없는 `create_route_inventory_app()`으로 나열한다. 실제 앱의 경로/인증 분류와 같은지는 회귀 테스트로 확인한다.
- **경로 등록 정보와 실제 HTTP 관측은 다르다.** GET에도 수집·DB 스키마·캐시 갱신 부작용이 있으므로, 전수 HTTP 호출은 하지 않는다.
- 무인증 게이트 실측은 검토된 `/api/admin/control-center/{summary,incidents,routes}`만 수행한다. 401/403은 인증 거부를 확인할 뿐 등록 경로의 존재나 화면 정상 동작을 증명하지 않는다. 나머지는 미관측으로 표시한다.
- 공개 실측은 로컬 `/healthz`, `/api/health`와 지정된 API 터널·웹 호스트만 사용한다. `public_safe/public_reviewed`는 공개 의도 검토 목록이며 자동 호출 허가 목록이 아니다.
- 인증을 동반하는 심층 HTTP 점검은 기본 비활성이다. 별도 운영 검토 후 `CONTROL_CENTER_AUTH_PROBES_ENABLED=1`과 기존 관리자 식별자가 모두 설정된 경우에만 관리자 사전 확인 후 위 3개 읽기 API를 호출한다. 이번 배포는 새 계정·권한·서비스 키를 만들지 않는다.
- 데이터 내용 시각/JSON 유효성, 프로세스 포트, 하트비트, 기존 워치독, 스케줄러 성공 기록, Windows 작업 결과, 디스크·메모리·이벤트 로그를 읽는다. 파일 수정 시각만 있는 자료는 원천 데이터 최신성을 입증하지 못하므로 그 한계를 표시한다.
- 공급자 점검은 기존 MarketFlow 설정과 저장 상태를 확인한다. Telegram getMe·DART의 실제 네트워크 조회도 기본 비활성(`CONTROL_CENTER_PROVIDER_NETWORK_ENABLED=1`일 때만 시간당 제한)이며, 모델 호출·주문·결제·토큰 재발급은 하지 않는다. 키 존재는 API 성공과 구분한다.
- KR/US 휴장·주말 보정은 데이터 생성 지연의 허용치이며 수정주가·상장시장·실제 자료일 검증을 대신하지 않는다. 주문형 누적 성과 캐시가 없으면 판정을 생략한다.

## 저장·상태·사건

`data/control_center/`에 SQLite 관측·사건 이력, `latest.json`, `heartbeat.json`, `inventory.json`을 보관한다. 생성물은 커밋하지 않는다. 관리자 API와 비활성 MCP 조회 도구는 읽기 모드로만 연결한다.

같은 주기 실행은 OS 잠금으로 겹치지 않게 하고, 서로 다른 주기는 SQLite 반영과 스냅샷 발행을 직렬화한다. 각 주기 완료 시각과 오류를 별도로 판정하므로 빠른 점검만 실행돼도 심층 점검이 정상처럼 보이지 않는다. unknown/skipped는 정상 확인으로 계산하지 않는다.

사건은 반복 실패 후 열고 연속 정상 확인 뒤 해소한다. 미관측은 사건 해소 근거가 아니다. CLI 종료코드 0은 관측 완료를 뜻하며 서비스 정상 보장은 아니다. 실행기 자체 실패는 2다. 장애 원인은 화면의 저장 결과와 사건 이력에서 확인한다.

## MiniPC 등록

운영 경로 `C:\bitman_marketfloww`, 호스트 `MINIPC-NQYLP`, Flask 5003. KIS 보조 5001, MCP 8765, Goodrich 8000을 관측한다. 다른 프로젝트의 8080은 제외한다.

```powershell
# 변경 없는 등록 계획 출력 (어느 PC에서나 가능)
powershell -NoProfile -File deploy/register_control_center_tasks.ps1 -Plan
# 승인된 배포 및 테스트 후 MiniPC 관리자 셸에서
.\.venv\Scripts\python.exe -X utf8 -m app.services.control_center run --tier all --no-alerts
powershell -NoProfile -File deploy/register_control_center_tasks.ps1
.\.venv\Scripts\python.exe -X utf8 -m app.services.control_center status
```

| 작업 | 주기 | 시작 지연 | 실행 상한 |
|---|---|---|---|
| MarketFlow-ControlCenter-Fast | 1분 | 1분 | 4분 |
| MarketFlow-ControlCenter-Standard | 10분 | 2분 | 9분 |
| MarketFlow-ControlCenter-Deep | 60분 | 3분 | 15분 |

세 작업 모두 SYSTEM·숨김·중복 실행 무시·`--no-alerts`로 등록한다. 원래 작업을 먼저 삭제하지 않으며 기존 명령 소유권을 확인한 뒤 교체한다. 미니PC 이외 호스트나 다른 체크아웃에는 실제 등록을 거부한다. 의도적으로 폐기된 `MarketFlow-Watchdog`만 제외하고 현행 Flask/스케줄러/터널 워치독은 유지한다. 실제 작업 실패는 숨기지 않는다.

중지·롤백은 이 3개 관제 작업만 비활성화한 뒤 이전 검증 커밋으로 앱 배포를 되돌리는 순서다. 기존 운영 작업·회원·구독 DB는 관제 복구 대상으로 삼지 않는다. 관측 이력은 유지한다.

## 화면·접근

관리자 사이드바 → 운영 관제 센터. PC와 모바일에서 실행기/장애/사건/화면별 근거/경로 검색을 본다. 마지막 결과 생성 시각과 실제 관측 범위가 항상 구분된다. 조회 실패는 이전 결과를 유지하며 오류를 표시한다. 관리자만 API를 읽을 수 있고 일반 회원은 403, 비로그인은 401이다. 응답은 no-store다.

## OpenClaw와 알림

OpenClaw 운영 감독관의 MCP 4개 조회 도구와 설정 미리보기만 포함한다. 기존 연구 에이전트 설정·권한·바인딩을 변경하지 않는다. 자동 조치·에이전트 호출·메시지 발송은 활성화하지 않았다. 예약 작업은 환경 변수와 관계없이 `--no-alerts`를 사용한다. 재시작은 기존 워치독 계약이 담당한다.

## 검증 근거

계약·권한·경로 동등성·입력 오류·동시 쓰기·인증 실패 복구·주기별 정지·HTTP 제한·달력/시각/토큰 캐시 회귀 테스트, 프런트엔드 전체 테스트/린트/빌드, CI 및 배포 기록을 함께 확인한다. Windows의 알려진 네이티브 Python 오류가 발생하면 실패 배치를 새 프로세스로 재실행하고 전체 Linux CI 결과와 구분해 기록한다. 원본 인계 문서의 “258개 전수 호출 안전”과 “모든 화면 정상” 주장은 적용하지 않았다.
