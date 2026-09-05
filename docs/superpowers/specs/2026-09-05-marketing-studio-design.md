# Marketing Studio 설계 — 브랜드커넥트 수집 → SEO 블로그 → 영상 → 발행 패키지 (2026-09-05)

## 목적
네이버 브랜드커넥트 캠페인/상품을 수집해 상세정보와 스크린샷(3장+)을 확보하고, SEO 최적화 블로그 글과 맞춤 영상 대본, 자동 영상(MP4)을 만들어
채널별 발행 패키지와 수익 관리까지 제공하는 **독립 로컬 앱**. 자동 발행은 범위 밖(네이버 블로그 공식 API 부재, 계정 제재 위험).

## 위치 / 배포
- 저장소 `marketing_studio/` — MarketFlow 코드에 의존하지 않는 self-contained 패키지. 사용자는 폴더를 `C:\marketing_studio` 로 복사해 `setup.bat` → `run_studio.bat`.
- 런타임: Python 3.11, Flask(5080), Playwright Chromium(영구 프로필), Pillow, edge-tts, imageio-ffmpeg(내장 ffmpeg), SQLite.

## 아키텍처
```
web/app.py (Flask API + static SPA) ──▶ jobs.py (단일 워커 큐, 진행률/취소)
        │                                   │
        ▼                                   ▼
   pipeline.py  ──▶ crawler/ (session·brand_connect·product_page·screenshots·probe)
                ──▶ content/ (llm 체인·keywords·seo 채점·blog_writer·script_writer)
                ──▶ video/   (tts·slides·renderer·ffmpeg·fonts)
                ──▶ exporter.py (발행 패키지) · monetize.py (UTM/정산 CSV/EPC)
   db.py (SQLite, JSON 컬럼) · models.py (dataclass, to_dict 플랫)
```

## 핵심 결정
1. **DOM 변경 내성**: 브랜드커넥트는 로그인 필수 + 구조 미공개. 후보 셀렉터 리스트(`selectors.json`, 오버라이드 가능) → 휴리스틱(캠페인 링크 앵커 기준) → 원본 HTML 저장 + `probe` 리포트로 튜닝. 파서는 순수 함수라 픽스처로 테스트.
2. **로그인은 사람이**: `launch_persistent_context` 프로필에 세션 저장, 자동 로그인 없음(캡차/2FA).
3. **항상 완주**: LLM 없으면 템플릿 블로그/대본(SEO 85~100점), TTS 실패 시 무음+자막, 이미지 부족 시 전체 스크린샷 타일링, ffmpeg 는 imageio-ffmpeg 폴백.
4. **SEO 결정론 채점**: 13개 항목 100점(제목/서두/소제목 키워드, 1,500자, 이미지 3장, 해시태그, 표시문구, FAQ). LLM 결과 75점 미만이면 1회 자동 수정.
5. **수익화 내장**: 제휴 링크 → 블로그 CTA/영상 설명란/링크인바이오 자동 삽입, 채널별 UTM, 정산 CSV 파서, EPC/전환율 요약, 수익 계산기.
6. **긴 작업은 큐**: 브라우저/ffmpeg 작업은 JobRunner 스레드에서 직렬 실행, UI 는 2.5초 폴링.

## 검증 (샌드박스, 네이버 접근 불가 → 로컬 픽스처)
- `python -m pytest -q` (marketing_studio): 파서/SEO/작성기/LLM 체인(mock)/슬라이드/렌더러/패키지/API/전체 파이프라인.
- 전체 파이프라인 오프라인 실행: 스마트스토어 픽스처 → 스크린샷 3장 → 블로그 100점 1,777자 → 7장면 대본 → 1080x1920 MP4 + SRT + 썸네일 → 패키지 16파일, 46초.
- UI: 7개 화면 + 상세 모달 Playwright 렌더 확인, JS 오류 0.
- CI: `.github/workflows/marketing-studio-test.yml` (경로 필터, Playwright chromium 설치 후 pytest).

## 미구현 / 후속
- 실제 브랜드커넥트 DOM 은 사용자 PC 에서 `probe` 로 1회 확인 후 셀렉터 오버라이드 필요할 수 있음.
- 자동 발행(유튜브 Data API OAuth 등)은 사용자 요청 시 `publisher/` 확장 지점으로 추가.
