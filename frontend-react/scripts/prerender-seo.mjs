import { AD_PRIVACY_HTML, DATA_SHARING_HTML, PUBLISHING_PAGES } from '../src/data/publishing.mjs';
import { publicUrl, normalizePublicLinks } from '../src/lib/publicUrls.mjs';
// 공개 경로 정적 스냅샷 생성기 — `vite build` 뒤에 실행된다 (package.json build 스크립트).
//
// 왜 필요한가: SPA 는 모든 경로가 같은 빈 index.html 을 반환한다. AdSense 심사·검색
// 크롤러가 JS 렌더링에 실패하면 "콘텐츠 없음/저품질" 로 판정된다. 이 스크립트는
// 공개 경로마다 dist/<경로>/index.html 을 만들어:
//   1. 경로별 <title>·description·canonical·og:* 를 심고
//   2. #root 앞에 실제 본문 스냅샷(<div id="seo-content">)을 넣는다.
//      JS 가 실행되면 main.tsx 가 이 블록을 즉시 제거하고 React 앱이 대체한다.
//
// 주의: public/_redirects 에서 여기서 생성하는 경로의 `<path> / 200` 프록시 라인을
// 제거해야 정적 파일이 서빙된다 (Cloudflare Pages 는 리다이렉트를 먼저 평가).
// 본문 텍스트는 src/pages 의 해당 페이지와 내용을 맞춰 유지할 것.

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { GUIDES, renderGuideNotes } from '../src/data/guides.mjs';
import { CREATOR_ABOUT_JSON_LD, CREATOR_PROFILE } from '../src/data/creator.mjs';

const ORIGIN = 'https://bit-man.net';
const DIST = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist');

const NAV = `
<nav><a href="/">홈</a> · <a href="/guide">인사이트 가이드</a> · <a href="/community">커뮤니티</a> · <a href="/pricing">요금제</a> · <a href="/about">서비스 소개</a> · <a href="/privacy">개인정보처리방침</a> · <a href="/terms">이용약관</a> · <a href="/editorial">편집 · 정정 원칙</a> · <a href="/contact">문의 · 오류 신고</a></nav>`;

const FOOTER = `
<footer><p>MarketFlow 는 관찰·분석 정보를 제공하며 자동 주문이나 투자 자문을 수행하지 않습니다.
모든 정보는 투자 판단을 위한 참고 자료이며, 최종 결정과 책임은 투자자 본인에게 있습니다.
과거의 결과는 미래 수익을 보장하지 않습니다.</p>
<p>문의: point10890@gmail.com · © MarketFlow</p></footer>`;

/** @type {Array<{path: string, title: string, description: string, body: string, jsonLd?: object | object[]}>} */
const ROUTES = [
    {
        path: '/',
        title: 'BitMan AI 주식분석 에이전트 | AI 브레인',
        description:
            '여러 AI 에이전트가 국내주식·미국주식·가상자산 시장을 자동 분석합니다. AI 브레인과 제갈공명에서 종목 후보, 차트 유사 사례, 뉴스·공시 근거를 확인하세요.',
        body: `
<h1>세 시장을 살피고, 종목의 근거를 찾다.</h1>
<p><strong>BitMan AI 주식분석 에이전트</strong>는 국내주식, 미국주식, 가상자산의 시장 흐름을 한 곳에서 보여줍니다. 여러 AI 에이전트가 시장 데이터를 분석하고 종목의 근거를 검토합니다.</p>
<p><a href="/signup">무료 계정 만들기</a> · <a href="/login">로그인</a> · <a href="/pricing">요금제 보기</a></p>
<section id="automation">
<h2>세 시장의 흐름을 한 대시보드에서</h2>
<ul>
<li><strong>국내주식</strong> — 주도주 변화, 수급과 차트를 살펴봅니다.</li>
<li><strong>미국주식</strong> — 시장 브리핑, 섹터와 ETF 자금 흐름을 확인합니다.</li>
<li><strong>가상자산</strong> — 시장 브리핑, BTC 점유율과 코인 시그널을 확인합니다.</li>
</ul>
</section>
<section id="ai-brain">
<h2>AI 브레인 · 종목 후보와 근거를 함께</h2>
<p>알파 스캐너와 Goodrich TOP 3에서 관찰 후보를 찾고, 종목 판단에서 에이전트가 합의한 근거와 엇갈린 의견을 확인합니다. 차트 유사 사례는 현재 흐름과 비슷한 과거 구간을 보여줍니다. 제갈공명에서 관련 뉴스와 공시를 대조해 종목이 움직인 배경을 살펴볼 수 있습니다.</p>
<p><a href="/signup?plan=pro&amp;aibain=1">AI 브레인 포함 플랜으로 시작하기</a></p>
</section>
<h2>가입부터 이용까지</h2>
<ol>
<li><strong>계정 만들기</strong> — 이메일로 무료 가입합니다.</li>
<li><strong>요금제 선택</strong> — 기본 시장 분석은 Pro, 종목 후보와 뉴스·공시 검증까지 보려면 AI 브레인 포함 플랜을 선택합니다.</li>
<li><strong>입금 후 구독 신청</strong> — 안내된 금액을 이체하고 신청을 제출합니다.</li>
<li><strong>관리자 승인</strong> — 승인 후 대시보드에서 선택한 서비스를 이용합니다.</li>
</ol>
<p>기존 Pro·Ultra Pro 회원은 AI 브레인과 제갈공명을 추가할 수 있습니다. 이용 기간, 추가 요금과 플랜 구성은 <a href="/pricing">요금제</a>에서 확인하세요.</p>
<h2>가입 없이 살펴보기</h2>
<p><a href="/guide/signal-verification-worked-example">AI 후보 6건 검증 예제</a> · <a href="/guide">전체 가이드</a> · <a href="/track-record">트랙 레코드</a> · <a href="/community">공개 커뮤니티</a></p>`,
    },
    {
        path: '/about',
        title: '서비스 소개 | MarketFlow',
        description:
            'MarketFlow 는 시장 데이터를 반복 관찰하고 데이터 품질을 확인한 뒤 의미 있는 변화만 기록하는 AI 시장 관찰 서비스입니다. 핵심 에이전트 Claw 의 작동 방식과 운영 원칙을 소개합니다.',
        jsonLd: CREATOR_ABOUT_JSON_LD,
        body: `
<h1>서비스 소개</h1>
<p><strong>MarketFlow</strong> 는 시장 데이터를 반복 관찰하고, 원천 시각과 데이터 품질을 확인한 뒤
의미 있는 변화만 기록하는 시장 관찰 서비스입니다. 핵심 에이전트 <strong>Claw</strong> 와 함께
한국·미국·암호화폐 분석 도구를 한 대시보드에서 제공합니다.</p>
<section id="creator">
<h2>운영자 소개</h2>
<p>${esc(CREATOR_PROFILE.introduction)}</p>
<p><a href="${esc(CREATOR_PROFILE.channelUrl)}" target="_blank" rel="noopener noreferrer">${esc(CREATOR_PROFILE.channelName)}</a> 유튜브 채널에서 공개 영상과 채널 활동을 확인할 수 있습니다.</p>
<p>구독자 수 기준: ${esc(CREATOR_PROFILE.subscriberAsOf)}</p>
</section>
<h2>Claw는 어떻게 작동하나요</h2>
<ul>
<li><strong>관찰</strong> — 정해진 주기로 시장 원천과 후보군을 수집합니다.</li>
<li><strong>품질 확인</strong> — 결측·지연·중복 여부와 원천 시각을 먼저 확인합니다.</li>
<li><strong>변화 검출</strong> — 조건을 통과한 변화만 관찰 이벤트로 기록합니다.</li>
<li><strong>위험 우선</strong> — 품질이 부족하거나 위험 신호가 있으면 긍정 알림을 HOLD 합니다.</li>
<li><strong>사후 검증</strong> — 검출 이후 결과를 D+1·D+5 기준으로 기록해 다음 판단의 근거로 남깁니다.</li>
</ul>
<h2>대시보드에서 확인할 수 있는 것</h2>
<p>Claw 운영 상태, 데이터 신선도와 품질, 검출 이벤트와 근거, 위험·무효화 조건, 시장별 분석 및
브리핑을 확인할 수 있습니다. AI Brain은 여러 분석 결과를 교차 검토하는 선택형 확장 기능입니다.
등급과 점수는 매수·매도 지시가 아니라 관찰 우선순위를 정리하기 위한 지표입니다.</p>
<h2>운영 원칙</h2>
<ul>
<li>실제 주문을 실행하지 않는 관찰 전용 서비스입니다.</li>
<li>데이터가 불충분하면 추정값으로 채우지 않고 HOLD 또는 확인 불가로 표시합니다.</li>
<li>모든 신호를 가설로 다루며, 원천과 시각을 함께 남기는 것을 우선합니다.</li>
<li>특정 수익률이나 손실 회피를 보장하지 않습니다.</li>
</ul>
<h2>투자 유의사항</h2>
<p>본 서비스가 제공하는 모든 정보는 투자 참고 자료이며 투자 권유·자문이 아닙니다. 특정 종목의 매수·매도를
권유하지 않으며, 과거 성과는 미래 수익을 보장하지 않습니다. 투자의 최종 판단과 책임은 투자자 본인에게 있습니다.</p>
<h2>문의</h2>
<p>제휴·오류 제보·기타 문의: point10890@gmail.com</p>`,
    },
    {
        path: '/privacy',
        title: '개인정보처리방침 | MarketFlow',
        description:
            'MarketFlow 개인정보처리방침 — 수집 항목, 이용 목적, 보유·파기 원칙, Google AdSense 광고 쿠키, 이용자의 권리와 문의처를 안내합니다.',
        body: `
<h1>개인정보처리방침</h1>
<p>시행일 2026-09-15</p>
<p>MarketFlow(이하 "서비스")는 이용자의 개인정보를 소중히 여기며, 「개인정보 보호법」 등 관련 법령을
준수합니다. 본 방침은 서비스가 어떤 정보를 수집하고 어떻게 이용·보관·파기하는지를 설명합니다.</p>
<h2>1. 수집하는 개인정보 항목</h2>
<ul>
<li><strong>회원가입 시</strong>: 이메일 주소, 이름(닉네임), 비밀번호(단방향 암호화 저장)</li>
<li><strong>구독 신청 시</strong>: 입금자명, 선택 플랜</li>
<li><strong>자동 수집</strong>: 서비스 이용 기록, 접속 일시, 브라우저 정보(쿠키 및 유사 기술)</li>
</ul>
<h2>2. 개인정보의 이용 목적</h2>
<ul>
<li>회원 식별, 로그인 및 구독 상태 관리</li>
<li>구독 결제(계좌이체) 확인 및 승인 처리</li>
<li>서비스 공지, 구독 만료 안내 등 필수 알림</li>
<li>서비스 품질 개선 및 부정 이용 방지</li>
</ul>
<h2>3. 보유 및 파기</h2>
<p>개인정보는 회원 탈퇴 시 지체 없이 파기합니다. 단, 관련 법령에 따라 보존이 필요한 정보(결제·정산
기록 등)는 해당 법령이 정한 기간 동안 분리 보관 후 파기합니다.</p>
<h2>4. 광고 및 쿠키 (Google AdSense)</h2>
${AD_PRIVACY_HTML}
<h2>5. 제3자 제공</h2>
${DATA_SHARING_HTML}
<h2>6. 이용자의 권리</h2>
<p>이용자는 언제든지 자신의 개인정보를 조회·수정하거나 삭제(회원 탈퇴)를 요청할 수 있습니다.</p>
<h2>7. 문의처</h2>
<p>개인정보 관련 문의: point10890@gmail.com</p>`,
    },
    {
        path: '/terms',
        title: '이용약관 | MarketFlow',
        description:
            'MarketFlow 이용약관 — 서비스 범위, 구독·결제·환불 규정, 투자 정보 면책, 이용자의 의무를 규정합니다.',
        body: `
<h1>이용약관</h1>
<p>시행일 2026-08-17</p>
<h2>1. 목적</h2>
<p>본 약관은 MarketFlow(이하 "서비스")가 제공하는 시장 분석 정보 서비스의 이용 조건과 이용자·서비스
간의 권리·의무를 규정합니다.</p>
<h2>2. 서비스의 내용</h2>
<ul>
<li>KR·US·Crypto 시장에 대한 AI 기반 분석 정보 및 시그널 제공</li>
<li>커뮤니티(공개 열람 + 회원 참여) 운영</li>
<li>유료 구독(Pro / Ultra Pro)을 통한 전체 기능 이용</li>
</ul>
<h2>3. 구독 및 결제</h2>
<ul>
<li>구독은 계좌이체 후 관리자 승인 방식으로 활성화되며, 승인 시점부터 이용 기간(30일)이 시작됩니다.</li>
<li>Ultra Pro 는 1회 결제로 무기한 이용하는 플랜입니다.</li>
<li>구독 만료 후에는 재구독 신청을 통해 동일한 방식으로 이용을 재개할 수 있습니다.</li>
</ul>
<h2>4. 환불</h2>
<p>결제 후 7일 이내에 서비스를 실질적으로 이용하지 않은 경우 전액 환불을 요청할 수 있습니다. 이용
개시 이후에는 잔여 기간에 대해 일할 계산 환불을 원칙으로 합니다.</p>
<h2>5. 투자 정보에 대한 면책</h2>
<p>서비스가 제공하는 모든 정보(AI 분석, 시그널, 커뮤니티 게시물 포함)는 투자 판단을 위한
<strong>참고 자료</strong>이며, 「자본시장과 금융투자업에 관한 법률」상의 투자 자문 또는 투자 권유가
아닙니다. 투자의 최종 결정과 그 결과에 대한 책임은 전적으로 이용자 본인에게 있습니다.</p>
<h2>6. 이용자의 의무</h2>
<ul>
<li>타인의 계정을 도용하거나 서비스 콘텐츠를 무단으로 복제·재배포하지 않습니다.</li>
<li>커뮤니티에 법령 위반, 허위 사실, 스팸성 게시물을 작성하지 않습니다.</li>
</ul>
<h2>7. 서비스의 변경 및 중단</h2>
<p>서비스는 운영상·기술상 필요에 따라 제공 내용을 변경할 수 있으며, 중대한 변경은 사전에 공지합니다.</p>
<h2>8. 문의처</h2>
<p>약관 관련 문의: point10890@gmail.com</p>`,
    },
    {
        path: '/pricing',
        title: '요금제 — AI 브레인 + 제갈공명 · Pro · Ultra Pro | MarketFlow',
        description:
            'PRO 50,000원, PRO+AI 브레인·제갈공명 100,000원. 기존 PRO·Ultra Pro 회원은 AI·제갈공명 추가 50,000원입니다.',
        body: `
<h1>요금제</h1>
<p>계정 생성은 무료이며, 대시보드 전체 이용은 플랜 선택 → 계좌이체 → 관리자 승인 후 시작됩니다.</p>
<h2>기존 Pro·Ultra Pro 회원: AI 브레인 + 제갈공명 추가 50,000원 / 30일</h2>
<p>기존 등급을 유지하고 AI 분석과 뉴스·공시·시세 검증을 함께 추가합니다. AI 이용 중 Pro 잔여기간은 일시정지되고, AI 만료 후 다시 차감됩니다. Ultra Pro는 무기한 유지됩니다.</p>
<h2>무등급·만료 회원: Pro + AI 브레인 + 제갈공명 100,000원</h2>
<p>Pro 50,000원과 AI·제갈공명 50,000원을 함께 신청합니다. AI·제갈공명을 30일 이용하는 동안 Pro 30일은 보존됩니다.</p>
<h2>Pro — 50,000원 / 30일</h2>
<ul>
<li>Claw LIVE와 국내 주도주 관찰</li>
<li>KR · US · Crypto 대시보드</li>
<li>VCP · 차트 분석 · 시장 브리핑</li>
</ul>
<h2>Ultra Pro — 1회 결제 무기한 이용</h2>
<p>Pro 의 모든 기능을 기간 제한 없이 이용합니다.</p>
<h2>AI Brain 애드온 — 근거 분석과 후보 검증 확장</h2>
<ul>
<li>AI Brain 알파 스캐너</li>
<li>GraphRAG 분석과 TOP 3</li>
<li>스캔 성과·품질 확인 화면</li>
</ul>
<p>AI Brain 추가 구독에는 제갈공명이 포함되며 30일마다 갱신합니다. 기존 단독 이용권은 승인된 만료일까지 유지됩니다.</p>
<p>환불: 결제 후 7일 이내 미이용 시 전액 환불, 이용 개시 후에는 잔여 기간 일할 계산 환불이 원칙입니다.
자세한 내용은 <a href="/terms">이용약관</a>을 확인하세요.</p>`,
    },
    {
        path: '/community',
        title: '커뮤니티 — AI 시장 분석과 이야기 | MarketFlow',
        description:
            'AI 가 매일 생성하는 한국·미국·암호화폐 시장 분석 글과 공지, 회원들의 투자 이야기를 모은 MarketFlow 공개 커뮤니티입니다.',
        body: `
<h1>커뮤니티 — AI 시장 분석과 이야기</h1>
<p>AI 가 매일 생성하는 시장 분석과 공지, 회원들의 이야기를 모았습니다.
글 열람은 누구나 가능하며, 글쓰기와 댓글은 회원에게 열려 있습니다.</p>
<h2>게시판</h2>
<ul>
<li><a href="/community/analysis">시장 분석</a> — AI 가 매일 생성하는 KR·US·Crypto 시장 분석 글</li>
<li><a href="/community/lotto-ai">로또 AI</a> — AI 번호 분석 실험 코너</li>
<li><a href="/community/free-talk">자유 이야기</a> — 회원들의 투자 이야기</li>
</ul>
<p>이 페이지의 최신 글 목록은 JavaScript 실행 후 표시됩니다.</p>`,
    },
];

for (const page of PUBLISHING_PAGES) {
    ROUTES.push({ path: page.path, title: `${page.title} | MarketFlow`, description: page.description,
        body: `<h1>${page.title}</h1><p>최종 갱신: ${page.updated}</p>${page.html}` });
}

// ── 인사이트 가이드 — src/data/guides.mjs 단일 소스에서 목록/본문 페이지 생성 ──
const GUIDE_DISCLAIMER = `
<p><em>이 글은 투자 교육을 위한 일반 정보이며 특정 종목의 매수·매도 권유나 투자 자문이 아닙니다.
언급된 지표와 체크리스트는 분석 도구일 뿐 수익을 보장하지 않으며, 투자의 최종 판단과 책임은
투자자 본인에게 있습니다.</em></p>`;

// 공개 Track Record — 본문 숫자는 API 가 채우므로 스냅샷에는 규칙 설명만 넣는다 (수치 조작 금지).
ROUTES.push({
    path: '/track-record',
    title: '트랙 레코드 — 종가베팅 사후 검증 기록 | MarketFlow',
    description: '종가베팅 V2 가 매 거래일 남긴 신호를 지연·마스킹해 공개합니다. 등급·당일 등락률과 사후 검증 결과를 표본 수와 함께 그대로 보여줍니다.',
    body: `
<h1>종가베팅 사후 기록 (지연 공개)</h1>
<p>매 거래일 14:50 에 저장된 종가베팅 V2 신호를 거래일 1일 지연으로 공개합니다. 발생 후 거래일 5일 미만인
신호는 종목명 앞 두 글자만 표시하고 종목코드를 숨깁니다. 당일 신호와 전체 종목명은 구독자 대시보드에서만
볼 수 있습니다.</p>
<h2>산출 방식</h2>
<ul>
<li>최근 60 거래일(공개 가능한 분석일 기준)의 신호를 선별 없이 전부 싣습니다.</li>
<li>등급·점수·등락률은 신호 당일 저장 값입니다.</li>
<li>사후 수익은 별도 추적 파일(목표가/손절가 도달 판정, 일봉 기준)에 기록된 경우에만 표시하며, 없으면 "검증 대기"로 둡니다.</li>
<li>사후 수익률에는 거래 비용·슬리피지가 반영되어 있지 않습니다.</li>
</ul>
<p>표본 수·등급 분포·검증 완료 건수와 신호 목록은 페이지가 열릴 때 최신 기록에서 불러옵니다.</p>
<p><em>성과 지표는 사후 검증 결과이며 미래 수익을 보장하지 않습니다. 투자 판단과 책임은 이용자 본인에게 있습니다.</em></p>
<p><a href="/pricing">요금제 보기</a></p>`,
});

ROUTES.push({
    path: '/guide',
    title: '인사이트 가이드 — 시장 분석 교육 콘텐츠 | MarketFlow',
    description: 'VCP 패턴, 수급 분석, 시장 레짐, 종가베팅 체크리스트, 포지션 사이징, 공시 읽기, AI 신호 활용까지 — MarketFlow 팀이 쓴 시장 분석 교육 가이드 모음입니다.',
    jsonLd: {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        name: 'MarketFlow 인사이트 가이드',
        url: `${ORIGIN}/guide`,
        inLanguage: 'ko',
        hasPart: GUIDES.map((g) => ({
            '@type': 'Article',
            headline: g.title,
            url: `${ORIGIN}/guide/${g.slug}`,
        })),
    },
    body: `
<h1>인사이트 가이드</h1>
<p>차트·수급·공시·리스크 관리까지, MarketFlow 팀이 서비스에 녹인 분석 원리를 누구나 읽을 수 있게
정리했습니다. 모든 글은 교육 목적이며 투자 권유가 아닙니다.</p>
<p>${esc(CREATOR_PROFILE.introduction)} <a href="/about#creator">운영자 소개와 채널 보기</a></p>
<ul>
${GUIDES.map((g) => `<li><a href="/guide/${g.slug}">${g.title}</a> — ${g.description} · 보강 ${g.updatedDate}</li>`).join('\n')}
</ul>`,
});

for (const g of GUIDES) {
    ROUTES.push({
        path: `/guide/${g.slug}`,
        title: `${g.title} | MarketFlow 가이드`,
        description: g.description,
        jsonLd: [
            {
                '@context': 'https://schema.org',
                '@type': 'Article',
                headline: g.title,
                description: g.description,
                datePublished: g.date,
                dateModified: g.updatedDate,
                citation: g.sources.map((source) => source.url),
                author: { '@type': 'Organization', name: 'MarketFlow 리서치', url: `${ORIGIN}/about#creator` },
                publisher: { '@type': 'Organization', name: 'MarketFlow', url: ORIGIN },
                mainEntityOfPage: `${ORIGIN}/guide/${g.slug}`,
                inLanguage: 'ko',
            },
            {
                '@context': 'https://schema.org',
                '@type': 'BreadcrumbList',
                itemListElement: [
                    { '@type': 'ListItem', position: 1, name: '홈', item: ORIGIN },
                    { '@type': 'ListItem', position: 2, name: '인사이트 가이드', item: `${ORIGIN}/guide` },
                    { '@type': 'ListItem', position: 3, name: g.title, item: `${ORIGIN}/guide/${g.slug}` },
                ],
            },
        ],
        body: `
<p><a href="/guide">← 인사이트 가이드</a></p>
<h1>${g.title}</h1>
<p><a href="/about#creator">MarketFlow 리서치</a> · 최초 게시: ${g.date} · 내용 보강: ${g.updatedDate} · ${g.readMinutes}분 읽기 · ${g.category}</p>
<p><a href="/about#creator">운영자: ${esc(CREATOR_PROFILE.name)} · ${esc(CREATOR_PROFILE.channelName)}</a></p>
${g.html}
${renderGuideNotes(g)}
${GUIDE_DISCLAIMER}`,
    });
}

function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderRoute(template, route) {
    const url = publicUrl(route.path);
    let html = template
        .replace(/<noscript>[\s\S]*?<\/noscript>/, '')
        .replace(/(<meta property="og:type" content=")[^"]*(")/, `$1${route.path.startsWith('/guide/') ? 'article' : 'website'}$2`)
        .replace(/<title>[^<]*<\/title>/, `<title>${route.title.replace(/</g, '&lt;')}</title>`)
        .replace(/(<meta name="description" content=")[^"]*(")/, `$1${esc(route.description)}$2`)
        .replace(/(<link rel="canonical" href=")[^"]*(")/, `$1${url}$2`)
        .replace(/(<meta property="og:title" content=")[^"]*(")/, `$1${esc(route.title)}$2`)
        .replace(/(<meta property="og:description" content=")[^"]*(")/, `$1${esc(route.description)}$2`)
        .replace(/(<meta property="og:url" content=")[^"]*(")/, `$1${url}$2`)
        .replace(/(<meta name="twitter:title" content=")[^"]*(")/, `$1${esc(route.title)}$2`)
        .replace(/(<meta name="twitter:description" content=")[^"]*(")/, `$1${esc(route.description)}$2`);

    if (route.jsonLd) {
        const json = JSON.stringify(normalizePublicLinks(route.jsonLd)).replace(/</g, '\\u003c');
        html = html.replace('</head>', `    <script type="application/ld+json" data-seo="jsonld">${json}</script>\n</head>`);
    }

    // Pages also serves the root HTML for app routes. Hide the public snapshot before
    // first paint there and while a returning member's stored session is checked.
    if (route.path === '/') {
        html = html.replace('</head>', `<script>
(function () {
    function readToken(name) {
        try { return window[name].getItem('auth_token'); } catch (_) { return null; }
    }
    if (location.pathname !== '/' || readToken('localStorage') || readToken('sessionStorage')) {
        document.documentElement.classList.add('skip-home-snapshot');
    }
})();
</script>
<style>.skip-home-snapshot #seo-content{display:none}</style>
</head>`);
    }

    // Keep the public text readable even when external CSS/JS is unavailable.
    html = html.replace('</head>', `<style>
body{background:#09090b}
#seo-content{font-family:system-ui,sans-serif;background:#09090b;overflow-wrap:anywhere}
#seo-content a{color:#ffad9c;text-decoration:underline;text-underline-offset:3px}
#seo-content h1,#seo-content h2,#seo-content th{color:#fafafa}
#seo-content table{width:100%;border-collapse:collapse}
#seo-content th,#seo-content td{padding:8px;border:1px solid #52525b;text-align:left}
#seo-content footer{margin-top:40px;border-top:1px solid #52525b;padding-top:16px}
</style></head>`);

    const snapshot = `<div id="seo-content" style="max-width:760px;margin:0 auto;padding:32px 20px;color:#d4d4d8;line-height:1.7">${NAV}${route.body}${FOOTER}</div>\n    `;
    html = html.replace('<div id="root">', `${snapshot}<div id="root">`);

    if (!html.includes('id="seo-content"')) {
        throw new Error(`[prerender] #root injection failed for ${route.path}`);
    }
    return html;
}

const template = readFileSync(join(DIST, 'index.html'), 'utf8');

for (const route of ROUTES) {
    const out = renderRoute(template, route);
    const target = route.path === '/'
        ? join(DIST, 'index.html')
        : join(DIST, ...route.path.split('/').filter(Boolean), 'index.html');
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, out);
    console.log(`[prerender] ${route.path} -> ${target.replace(DIST, 'dist')}`);
}

console.log(`[prerender] ${ROUTES.length} routes done`);
