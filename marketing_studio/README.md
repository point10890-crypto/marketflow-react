# Marketing Studio — 브랜드커넥트 수익화 스튜디오

네이버 **브랜드커넥트** 캠페인/상품을 수집하고, 상세정보와 **스크린샷 3장 이상**을 확보한 뒤,
**SEO 최적화 블로그 글 → 맞춤 영상 대본 → 자동 영상(MP4)** 을 만들고, 채널별로 바로 올릴 수 있는
**발행 패키지**와 **수익 관리**까지 한 화면에서 처리하는 로컬 웹 앱입니다.

> 자동 발행(네이버 블로그/유튜브 업로드)은 **의도적으로 포함하지 않았습니다.** 네이버 블로그는 공식 글쓰기 API 가 없고,
> 자동 업로드는 계정 제재 위험이 큽니다. 대신 "복사 → 붙여넣기 → 업로드" 10분 안에 끝나도록 발행 패키지와 체크리스트를 만들어 줍니다.

```
브랜드커넥트/스마트스토어 URL
   │  ① 수집: 상세정보(가격·브랜드·특징·스펙·수수료) + 스크린샷(hero/전체/모바일) + 상품 이미지
   ▼
키워드 분석 (휴리스틱 + 네이버 검색광고 API 검색량 선택)
   │  ② SEO 블로그: 제목/서두/소제목 키워드 배치, 장단점, FAQ, 표시문구, 해시태그 → 100점 채점표
   │  ③ 영상 대본: 훅 → 문제 → 특징 3개 → 가격 → CTA (쇼츠 45초 / 리뷰 2~3분)
   ▼
   ④ 영상: edge-tts 음성 + 자막 슬라이드 + 켄번즈 줌 + (BGM) → 1080x1920 MP4 + 썸네일 + SRT
   ▼
   ⑤ 발행 패키지: blog/(md·html·txt) + images/ + video/(mp4·srt·설명란) + links.txt + CHECKLIST.md
   ▼
   ⑥ 수익 관리: 채널별 클릭/주문/수수료 입력 또는 정산 CSV 가져오기 → EPC·전환율·상품별 TOP
```

---

## 1. 설치 (Windows, `C:\marketing_studio`)

1. **Python 3.11+** 설치 — https://www.python.org/downloads/ ("Add python.exe to PATH" 체크)
2. 이 폴더(`marketing_studio`)를 통째로 `C:\marketing_studio` 에 복사합니다.
   ```powershell
   git clone https://github.com/point10890-crypto/marketflow-react.git C:\_mf
   robocopy C:\_mf\marketing_studio C:\marketing_studio /E
   ```
3. `C:\marketing_studio\setup.bat` 실행 — 가상환경 생성, 패키지 설치, Playwright Chromium 설치, `.env` 생성, 환경 진단(doctor)
4. `C:\marketing_studio\.env` 를 메모장으로 열어 API 키 입력 (아래 "설정" 참고). **키가 없어도 템플릿 모드로 전체 파이프라인이 동작**합니다.
5. `run_studio.bat` 실행 → 브라우저에 http://127.0.0.1:5080 이 열립니다.

> ffmpeg 는 `imageio-ffmpeg` 패키지에 내장된 바이너리를 자동으로 사용하므로 따로 설치할 필요가 없습니다.
> 한글 폰트는 Windows 의 맑은 고딕을 자동 탐색합니다.

## 2. 5분 빠른 시작

| 단계 | 화면 | 할 일 |
|------|------|------|
| 1 | 브랜드커넥트 | **네이버 로그인 창 열기** → 뜬 브라우저에서 직접 로그인 (최초 1회, 세션 저장) |
| 2 | 브랜드커넥트 | **수집 시작** → 캠페인 목록 저장 → 원하는 캠페인 **가져오기** (상세 + 스크린샷) |
| 3 | 상품 | 상품 카드 **상세** → **제휴 링크**(커넥트링크/파트너스 링크) 입력 후 저장 |
| 4 | 상품 | **전체 실행** → 블로그 + 대본 + 영상 + 패키지가 순서대로 생성 (작업 표시줄에서 진행률 확인) |
| 5 | 콘텐츠 스튜디오 | SEO 점수·체크리스트 확인, 필요한 부분 수정 후 **저장 & 재채점**, **텍스트 복사** |
| 6 | 영상 | 미리보기 → **MP4 다운로드**, **설명란 복사** |
| 7 | `output/packages/…` | `CHECKLIST.md` 순서대로 네이버 블로그 / 클립 / 쇼츠 / 릴스에 업로드 |
| 8 | 수익 관리 | 발행 후 클릭/주문/수수료 입력 (또는 정산 CSV 붙여넣기) → EPC 로 다음 상품 선정 |

캠페인 페이지가 없어도 **상품 → URL 로 가져오기** 에 스마트스토어/브랜드스토어/쿠팡/일반 쇼핑몰 상품 URL 을 넣으면 동일하게 동작합니다.

## 3. 브랜드커넥트 수집

- **로그인**: 자동 로그인은 하지 않습니다(캡차·2단계 인증). `login_naver.bat` 또는 UI 버튼으로 창을 열어 직접 로그인하면 `data/browser_profile/` 에 세션이 저장되어 이후 헤드리스로 재사용됩니다.
- **목록 URL**: 기본 `https://brandconnect.naver.com/`. 설정 → "브랜드커넥트 캠페인 목록 URL" 또는 `.env` 의 `STUDIO_BRANDCONNECT_URL` 로 변경. 목록이 안 잡히면 네비게이션에서 "캠페인" 링크를 자동 탐색합니다.
- **셀렉터 튜닝**: 브랜드커넥트 화면 구조는 예고 없이 바뀝니다. 기본값은 `studio/crawler/selectors.json` 의 **후보 셀렉터 목록**(앞에서부터 시도) + 휴리스틱(캠페인 링크 기준)입니다.
  1. 브랜드커넥트 화면에서 **DOM 프로브** 에 목록 URL 을 넣고 실행 → 반복 컨테이너/캠페인 링크/클래스 목록 확인 (`data/probe/…/page.html`, `screenshot.png`, `probe.json` 저장)
  2. 설정 → **셀렉터 오버라이드** 에 JSON 입력, 예: `{"list": {"item": ["ul.CampaignList_list > li"], "title": [".CampaignCard_title"]}}`
  3. 다시 수집. 수집한 원본 HTML 은 항상 `data/campaigns/` 에 남으므로 오프라인으로도 튜닝할 수 있습니다.
- **상품 보강**: 캠페인 상세에 스마트스토어 링크가 있으면 그 상품 페이지도 열어 가격·이미지·스펙을 보강하고 스크린샷을 추가로 찍습니다 (`data/products/<id>/store/`).
- **스크린샷 보장**: hero(첫 화면) + fullpage(전체) + mobile(세로) + 가격/상세 섹션 + 상품 이미지 다운로드. 3장 미만이면 전체 화면을 잘라 채웁니다.
- **매너**: 개인 계정 세션으로 사람이 보는 속도(페이지당 수 초)로만 접근합니다. 대량 병렬 수집은 지원하지 않으며 하지 마세요.

## 4. 콘텐츠 엔진

**LLM 우선순위** `.env` `STUDIO_LLM_ORDER=gemini,deepseek,openai,anthropic` — 키가 있는 프로바이더만, 실패(429 등) 시 다음으로 넘어가고 전부 실패하면 **템플릿 모드**로 작성합니다. SDK 없이 HTTP 로 호출합니다.

**SEO 채점 (100점)** — 네이버 블로그 상위노출 실무 규칙을 결정론적으로 검사합니다.

| 항목 | 배점 | 항목 | 배점 |
|------|-----|------|-----|
| 제목 15~40자 | 8 | 소제목 3개 이상 | 8 |
| 제목에 핵심 키워드 | 15 | 소제목에 키워드 | 5 |
| 키워드가 제목 앞쪽 | 5 | 이미지 3장 이상 | 10 |
| 서두 150자 안에 키워드 | 10 | 요약문 50~160자 + 키워드 | 5 |
| 본문 1,500자 이상 | 10 | 해시태그 5~20개 | 5 |
| 키워드 본문 3~15회 | 10 | 제휴/광고 표시 문구 | 5 |
| 목록 + FAQ 구조 | 4 | | |

- 점수가 75 미만이면 LLM 에게 제안 목록을 주고 1회 자동 수정합니다. 콘텐츠 스튜디오에서 직접 고친 뒤 **저장 & 재채점** 도 가능합니다.
- **키워드**: 상품명에서 홍보 문구를 제거한 핵심 키워드 + 보조("후기/추천/가격/장단점") + 롱테일 + 해시태그(`#광고` 포함). `NAVER_SEARCHAD_*` 키를 넣으면 **월 검색량**으로 정렬됩니다.
- **출력물**: `output/blog/<slug>_<id>/post.md`, `post.html`, `post.txt`(네이버 에디터 붙여넣기용: `■` 소제목, `[이미지 삽입: 파일명]`), `meta.json`

## 5. 영상 제작

- **TTS**: `edge-tts`(무료, Microsoft 신경망 음성). 기본 `ko-KR-SunHiNeural`, 남성은 `ko-KR-InJoonNeural`. 인터넷이 필요하며 실패 시 **무음 + 자막** 영상으로 완주합니다(영상 카드에 사유 표시).
- **슬라이드**: 1080x1920, 블러 배경 + 상품 이미지 카드 + 큰 자막 + 내레이션 소자막 + POINT 배지 + 진행바.
- **렌더**: 장면별 켄번즈 줌 → 이어붙이기 → BGM 믹스(`assets/bgm/` 에 mp3 를 넣으면 자동 사용, 볼륨 12%) → `output/videos/<slug>_<script>/<slug>.mp4` + `_thumb.png` + `.srt` + `metadata.json`
- 대본 화면에서 자막/내레이션/초를 수정하고 **이 대본으로 영상 제작** 을 누르면 재렌더링됩니다.

## 6. 수익화 플레이북

1. **링크가 먼저**: 상품 상세의 *제휴 링크* 에 브랜드커넥트 커넥트링크(또는 쿠팡 파트너스 링크)를 넣어야 블로그 CTA·영상 설명란·`links.txt` 에 들어갑니다. 링크 없이 발행하면 수익이 0 입니다.
2. **채널 조합**: 블로그 글(검색 유입) + 클립/쇼츠(노출) 를 **같은 날** 올리고 영상 설명란/고정댓글에 블로그 링크와 제휴 링크를 둡니다. 채널별 UTM 링크는 상품 상세에서 복사할 수 있습니다(브랜드커넥트 단축링크는 원본 그대로 사용).
3. **표시 의무**: 표시광고법에 따라 본문 상단/하단에 제휴 표시 문구(설정에서 수정)와 `#광고` 를 남깁니다. 패키지에 자동 포함됩니다.
4. **선정 기준**: 대시보드 **수익 계산기** 로 `판매가 × 수수료율` 이 큰 상품(주문당 수수료 2~3만원↑)을 우선합니다. 체험단(제품 제공)은 콘텐츠 원가 절감용, 커미션형은 매출용으로 나눠 운영하세요.
5. **개선 루프**: 발행 7일 후 수익 관리에 클릭/주문을 기록 → **EPC(클릭당 수익)** 낮은 글은 제목/썸네일 교체, 높은 카테고리는 유사 상품 추가.

## 7. CLI

```powershell
.\.venv\Scripts\activate
python -m studio doctor                 # 환경 진단 (--login 로그인 상태까지)
python -m studio login                  # 네이버 로그인 창
python -m studio crawl --pages 3 --details 5   # 목록 수집 + 상세 5건
python -m studio campaigns              # 캠페인 목록
python -m studio import <URL>           # 상품 가져오기
python -m studio products
python -m studio blog <상품ID>           # SEO 블로그
python -m studio script <상품ID> --format shorts|review
python -m studio video <상품ID> [--bgm 파일] [--voice ko-KR-InJoonNeural]
python -m studio package <상품ID>
python -m studio run <URL|상품ID|캠페인ID>   # 전체 파이프라인 (run_pipeline.bat)
python -m studio probe <URL>            # DOM 프로브
python -m studio earnings --import-csv 정산.csv
python -m studio serve --open           # 웹 UI
```

## 8. 설정 (`.env`)

| 키 | 설명 |
|----|------|
| `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | LLM (하나 이상 권장, 없으면 템플릿) |
| `STUDIO_LLM_ORDER` | 프로바이더 우선순위 |
| `STUDIO_GEMINI_MODEL`, `DEEPSEEK_MODEL`, `STUDIO_OPENAI_MODEL`, `STUDIO_ANTHROPIC_MODEL` | 모델명 |
| `NAVER_SEARCHAD_API_KEY/SECRET/CUSTOMER_ID` | 검색광고 키워드 도구(검색량) — 선택 |
| `NAVER_CLIENT_ID/SECRET` | 데이터랩 — 선택 |
| `STUDIO_BRANDCONNECT_URL`, `STUDIO_HEADLESS`, `STUDIO_CHROMIUM_PATH` | 크롤링 |
| `STUDIO_FFMPEG`, `STUDIO_TTS_VOICE`, `STUDIO_TTS_RATE`, `STUDIO_FONT_PATH` | 영상 |
| `STUDIO_BLOG_TONE`, `STUDIO_BLOG_LENGTH`, `STUDIO_DISCLOSURE`, `STUDIO_CREATOR_NAME` | 콘텐츠 |
| `STUDIO_HOST`, `STUDIO_PORT`, `STUDIO_HOME` | 서버/데이터 위치 |

UI 설정 화면에서 바꾼 값(톤, 글자수, 음성, 표시문구, 목록 URL, 헤드리스)은 DB 에 저장되어 `.env` 보다 우선합니다.

## 9. 디렉토리

```
C:\marketing_studio\
├─ setup.bat / run_studio.bat / login_naver.bat / run_pipeline.bat
├─ .env                      # 키/설정 (git 제외)
├─ studio\                   # 앱 코드
│  ├─ crawler\               # session(로그인/브라우저) · brand_connect · product_page · screenshots · probe · selectors.json
│  ├─ content\               # llm · keywords · seo · blog_writer · script_writer · prompts · markdown
│  ├─ video\                 # ffmpeg · fonts · tts · slides · renderer
│  ├─ pipeline.py · jobs.py · monetize.py · exporter.py · db.py · models.py · cli.py
│  └─ web\                   # Flask API + static SPA
├─ data\                     # studio.db · products\<id>\(스크린샷/이미지/page.html) · campaigns\ · probe\ · browser_profile\
├─ output\                   # blog\ · videos\ · packages\
├─ assets\bgm\ · assets\fonts\
└─ tests\                    # pytest
```

## 10. 문제 해결

| 증상 | 조치 |
|------|------|
| `playwright` 브라우저 오류 | `.\.venv\Scripts\python -m playwright install chromium` 재실행. 회사 PC 라면 `STUDIO_CHROMIUM_PATH` 에 설치된 Chrome 경로(`C:\Program Files\Google\Chrome\Application\chrome.exe`) 지정 |
| 로그인 안 됨 / 캠페인 0건 | `python -m studio doctor --login` 으로 세션 확인 → 브랜드커넥트 화면에서 DOM 프로브 → 셀렉터 오버라이드. 설정에서 헤드리스를 끄면 브라우저 창이 보여 원인 파악이 쉽습니다 |
| 영상이 무음 | edge-tts 가 네트워크(프록시/SSL)로 실패한 경우. 인터넷 확인 후 재제작. 영상 카드에 오류 사유 표시 |
| 한글이 □ 로 보임 | `STUDIO_FONT_PATH=C:\Windows\Fonts\malgunbd.ttf` 지정 또는 `assets\fonts\` 에 나눔고딕 복사 |
| ffmpeg 없음 | `pip install imageio-ffmpeg` 또는 `STUDIO_FFMPEG=C:\ffmpeg\bin\ffmpeg.exe` |
| LLM 429/오류 | 다음 프로바이더로 자동 전환. 전부 실패하면 템플릿 모드(작업 로그에 표시) |
| 포트 충돌 | `.env` `STUDIO_PORT` 변경 |

## 11. 테스트

```powershell
.\.venv\Scripts\python -m pytest -q      # 브라우저/ffmpeg 없는 환경에서는 해당 테스트 자동 skip
```

## 12. 유의사항

- 네이버 서비스 약관과 브랜드커넥트 운영정책을 준수하세요. 이 도구는 **본인 계정으로 본인이 보는 페이지**를 저장·정리하는 용도이며, 대량 수집·재배포 목적이 아닙니다.
- 생성된 글/영상은 발행 전 반드시 사실 확인(가격·스펙·효능 표현)을 하세요. 건강기능식품·의료기기 등은 표시 규제가 별도로 있습니다.
- 제휴 콘텐츠에는 표시광고법에 따른 경제적 이해관계 표시가 필수입니다(기본 문구 자동 삽입).
