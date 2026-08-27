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

const ORIGIN = 'https://bit-man.net';
const DIST = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist');

const NAV = `
<nav><a href="/">홈</a> · <a href="/community">커뮤니티</a> · <a href="/pricing">요금제</a> · <a href="/about">서비스 소개</a> · <a href="/privacy">개인정보처리방침</a> · <a href="/terms">이용약관</a></nav>`;

const FOOTER = `
<footer><p>MarketFlow 는 관찰·분석 정보를 제공하며 자동 주문이나 투자 자문을 수행하지 않습니다.
모든 정보는 투자 판단을 위한 참고 자료이며, 최종 결정과 책임은 투자자 본인에게 있습니다.
과거의 결과는 미래 수익을 보장하지 않습니다.</p>
<p>문의: point10890@gmail.com · © MarketFlow</p></footer>`;

/** @type {Array<{path: string, title: string, description: string, body: string}>} */
const ROUTES = [
    {
        path: '/',
        title: 'MarketFlow Claw — 근거 중심 AI 시장 관찰 대시보드',
        description:
            'MarketFlow는 한국·미국·암호화폐 시장을 반복 관찰하고 데이터 품질을 확인한 뒤 의미 있는 변화만 기록하는 AI 시장 관찰 서비스입니다. 장중 주도주 관찰, VCP 분석, AI 브리핑을 한 대시보드에서 제공합니다.',
        body: `
<h1>시장을 계속 관찰하고, 의미 있는 변화만 검출합니다</h1>
<p>MarketFlow Claw 는 국내 장중 흐름을 반복 관찰하고 데이터 품질이 충분할 때만 변화를 기록하는
AI 시장 관찰 에이전트입니다. KR·US·Crypto 분석 도구와 함께 근거·위험·사후 결과를 한 대시보드에서 확인합니다.</p>
<h2>작동 방식 — 점수보다 먼저, 관찰의 품질을 확인합니다</h2>
<ol>
<li><strong>시장 관찰</strong> — 시장별 일정과 원천 주기에 맞춰 가격·거래량·수급·분석 데이터를 수집합니다.</li>
<li><strong>품질 확인</strong> — 기준 시각과 누락 입력을 먼저 검사하고, 신뢰할 수 없으면 새 판단을 보류합니다.</li>
<li><strong>변화 검출</strong> — 주도주 신규 진입·등급 변화·이탈처럼 이전 관찰과 달라진 부분을 구분합니다.</li>
<li><strong>근거와 함께 기록</strong> — 종목·시각·상태·발송 결과를 남겨 같은 변화를 반복해서 알리지 않습니다.</li>
<li><strong>사후 검증</strong> — 발견 당시 알 수 있었던 정보와 이후 결과를 분리해 전략을 계속 점검합니다.</li>
</ol>
<h2>제공 기능</h2>
<ul>
<li><strong>Claw LIVE</strong> — 국내 장중 주도주 흐름과 등급 변화 관찰, 시스템 상태·원천 시각·전달 기록 표시</li>
<li><strong>KR · US · Crypto</strong> — 시장 개요, VCP, 차트 분석과 브리핑을 시장별 갱신 주기에 맞춰 제공</li>
<li><strong>근거와 위험 확인</strong> — 등급만이 아니라 데이터 품질, 기준 시각, 무효화 조건을 함께 표시</li>
<li><strong>AI Brain (선택 애드온)</strong> — 알파 스캐너, GraphRAG 분석, TOP 3와 스캔 성과 화면</li>
</ul>
<h2>운영 원칙</h2>
<ul>
<li>실제 주문을 실행하지 않는 관찰 전용 서비스입니다.</li>
<li>데이터가 불충분하면 추정값으로 채우지 않고 HOLD 또는 확인 불가로 표시합니다.</li>
<li>모든 신호를 가설로 다루며, 원천과 시각을 함께 남기는 것을 우선합니다.</li>
<li>특정 수익률이나 손실 회피를 보장하지 않습니다.</li>
</ul>
<h2>자주 묻는 질문</h2>
<p><strong>자동으로 주식을 주문하나요?</strong> 아니요. MarketFlow는 시장 관찰과 분석 정보를 제공하며 실제 계좌 주문을 실행하지 않습니다.</p>
<p><strong>가입하면 바로 무료로 대시보드를 쓸 수 있나요?</strong> 계정 생성은 무료입니다. 전체 대시보드 이용은 플랜을 선택하고 입금 확인과 관리자 승인이 끝난 뒤 시작됩니다.</p>
<p><strong>표시된 등급이나 과거 결과가 수익을 보장하나요?</strong> 아니요. 등급은 관찰 우선순위를 돕는 분석 결과이며 투자 권유가 아닙니다.</p>`,
    },
    {
        path: '/about',
        title: '서비스 소개 | MarketFlow',
        description:
            'MarketFlow 는 시장 데이터를 반복 관찰하고 데이터 품질을 확인한 뒤 의미 있는 변화만 기록하는 AI 시장 관찰 서비스입니다. 핵심 에이전트 Claw 의 작동 방식과 운영 원칙을 소개합니다.',
        body: `
<h1>서비스 소개</h1>
<p><strong>MarketFlow</strong> 는 시장 데이터를 반복 관찰하고, 원천 시각과 데이터 품질을 확인한 뒤
의미 있는 변화만 기록하는 시장 관찰 서비스입니다. 핵심 에이전트 <strong>Claw</strong> 와 함께
한국·미국·암호화폐 분석 도구를 한 대시보드에서 제공합니다.</p>
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
<p>시행일 2026-08-17</p>
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
<p>서비스의 공개 페이지에는 Google AdSense 광고가 게재될 수 있습니다. Google 을 포함한 제3자 광고
사업자는 쿠키 및 광고 식별자를 사용하여 이용자의 이전 방문 기록에 기반한 맞춤 광고를 표시할 수 있습니다.
Google 의 광고 쿠키 사용에 대한 자세한 내용은 <a href="https://policies.google.com/technologies/ads">Google 광고 정책</a>에서
확인할 수 있으며, <a href="https://adssettings.google.com">Google 광고 설정</a>에서 맞춤 광고를 비활성화할 수 있습니다.</p>
<h2>5. 제3자 제공</h2>
<p>서비스는 이용자의 개인정보를 외부에 판매하거나 제공하지 않습니다. 다만 법령에 근거한 요청이 있는
경우는 예외로 합니다.</p>
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
        title: '요금제 — Pro · Ultra Pro · AI Brain | MarketFlow',
        description:
            'MarketFlow 구독 요금제 안내 — Pro(30일), Ultra Pro(무기한), AI Brain 애드온의 기능과 가격, 계좌이체 결제·승인 절차를 확인하세요.',
        body: `
<h1>요금제</h1>
<p>계정 생성은 무료이며, 대시보드 전체 이용은 플랜 선택 → 계좌이체 → 관리자 승인 후 시작됩니다.</p>
<h2>Pro — 시장 관찰과 분석의 기본 (30일)</h2>
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
<p>베이스 플랜과 별도로 30일마다 갱신하는 선택형 애드온입니다.</p>
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

function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderRoute(template, route) {
    const url = `${ORIGIN}${route.path === '/' ? '/' : route.path}`;
    let html = template
        .replace(/<title>[^<]*<\/title>/, `<title>${route.title.replace(/</g, '&lt;')}</title>`)
        .replace(/(<meta name="description" content=")[^"]*(")/, `$1${esc(route.description)}$2`)
        .replace(/(<link rel="canonical" href=")[^"]*(")/, `$1${url}$2`)
        .replace(/(<meta property="og:title" content=")[^"]*(")/, `$1${esc(route.title)}$2`)
        .replace(/(<meta property="og:description" content=")[^"]*(")/, `$1${esc(route.description)}$2`)
        .replace(/(<meta property="og:url" content=")[^"]*(")/, `$1${url}$2`)
        .replace(/(<meta name="twitter:title" content=")[^"]*(")/, `$1${esc(route.title)}$2`)
        .replace(/(<meta name="twitter:description" content=")[^"]*(")/, `$1${esc(route.description)}$2`);

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
