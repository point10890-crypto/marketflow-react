# AdSense 심사 대비 — 공개 콘텐츠 + 정책 페이지 + 광고 인프라 + 공개 영역 디자인

2026-08-17 · 승인됨 (커뮤니티 읽기 공개 / 광고는 공개 페이지만 / 서비스명 MarketFlow + point10890@gmail.com 표기 / PC·모바일 퍼블리싱 디자인 개선 포함)

## 문제

AdSense 스크립트(`ca-pub-4268071335236139`)와 ads.txt 는 준비됐지만 심사 요건이 빠져 있다:
robots.txt 가 일반 크롤러를 전체 차단하고, 공개 콘텐츠가 랜딩+가격 2장뿐이며(나머지는
로그인 게이트), 개인정보처리방침·이용약관·소개 페이지가 없고, YMYL(금융) 면책이 없다.

## 1. 공개 커뮤니티 (심사 콘텐츠 핵심)

### 백엔드 — `app/routes/public_community.py` (신규 blueprint, 인증 없음, `/api/public/community`)
- `GET /boards` — 공개 화이트리스트 보드 목록 + 글 수
- `GET /boards/<slug>/posts?page=&per_page=` — 목록 (id, title, author_name, created_at,
  is_notice, views). per_page 상한 30
- `GET /posts/<id>` — 본문 HTML + 읽기전용 댓글 (작성자 이름만). 화이트리스트 밖 보드는 404
- 화이트리스트: env `PUBLIC_COMMUNITY_BOARDS` 기본 `notice,lotto-ai,analysis,free-talk`
- 개인정보 경계: author 는 표시 이름만. 이메일/user_id/구매정보 비노출. 수식마켓·Pro 라운지 제외
- 이미지: `/api/community/uploads/<filename>` 은 이미 무인증 서빙 — 공개 글 이미지 그대로 동작

### 프론트 — 비로그인 공개 라우트
- `/community` (보드 탭 + 글 목록), `/community/:board`, `/community/post/:id`
- `PublicLayout`: 상단 헤더(로고 + 로그인/무료가입 CTA) + `PublicFooter`. 사이드바 없음
- 글쓰기/댓글 → 가입 유도 CTA. 로그인 회원의 기존 대시보드 커뮤니티는 무변경

## 2. 정책·정보 페이지 (공개 4종)

- `/privacy` — 수집항목(이메일·이름)·이용목적·보관, **AdSense 쿠키/광고 식별자 고지 +
  맞춤광고 거부 방법(구글 광고 설정 링크)**, 문의처
- `/terms` — 구독/결제(계좌이체·승인제)/환불/서비스 범위/책임 제한
- `/about` — 서비스 소개(KR·US·Crypto AI 분석), 연락처, 투자 면책 전문
- `PublicFooter` (공용): 정책 링크 3종 + 투자 면책 한 줄("본 서비스가 제공하는 정보는 투자
  참고 자료이며 투자 권유·자문이 아닙니다. 투자에 대한 책임은 투자자 본인에게 있습니다.")
  + © MarketFlow. 랜딩·공개 커뮤니티·정책 페이지에 일괄 적용

## 3. 광고 인프라 (공개 페이지만)

- `AdSlot` 컴포넌트: `<ins class="adsbygoogle">` + push, 반응형(auto), 미승인/차단 시 영역
  자동 축소(min-height 없음), `data-ad-client` 고정 + `data-ad-slot` prop
- 배치: 공개 커뮤니티 목록 중간 1, 공개 글 본문 하단 1, 랜딩 하단 1. 정책 페이지 제외
- Auto ads 미사용(수동 슬롯만) → 로그인 대시보드는 광고 프리 유지

## 4. 크롤러·SEO 환경

- `robots.txt` 재작성: `Allow: /$ /community /privacy /terms /about /pricing` +
  `Disallow: /dashboard /admin /login /signup /plan-select /payment-request /pending-approval`,
  Mediapartners-Google 전체 허용 유지, Sitemap 명시
- `sitemap.xml`: 정적 공개 경로
- `index.html`: description/OG 메타 보강. 공개 페이지별 `document.title`

## 5. 공개 영역 퍼블리싱 디자인 (PC + 모바일 세로)

frontend-design 에이전트 참여. 앱 다크 아이덴티티(#09090b 바탕) 위에 공개 영역 전용의
정돈된 에디토리얼 톤: 읽기 중심 타이포그래피(본문 최대 폭 ~720px, 줄간격 넉넉히), 카드
헤어라인 보더, 보드별 액센트 컬러, 모바일(≤480px) 세로 1열 최적화(터치 타깃 ≥44px,
헤더 축약, 목록 카드형). 랜딩 푸터를 PublicFooter 로 교체·통일.

## 6. 검증·배포

- 공개 API 회귀 테스트: 화이트리스트 밖 403/404, 이메일 필드 부재, 쓰기 메서드 차단,
  per_page 상한
- 비로그인 브라우저 실렌더(PC 1280 + 모바일 375 세로) 확인 후 배포
- 프로덕션: robots.txt/sitemap/정책 페이지/공개 커뮤니티 200 확인. 심사 신청은 배포 후

## 비범위

- 로그인 대시보드 광고 (Pro 가치 보호)
- SSR/프리렌더 (Googlebot 은 CSR 렌더 가능 — 필요 시 후속)
- 정책 페이지 법률 자문 수준 문안
