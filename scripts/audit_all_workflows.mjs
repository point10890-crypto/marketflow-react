// 전체 워크플로우 audit - 모든 시나리오 + 페이지를 모바일 viewport 에서 검증.
//
// 출력: scripts/audit_screenshots/*.png + scripts/audit_report.json
import { chromium } from 'playwright';
import fs from 'fs';

// 운영 토큰(특히 admin)을 리포에 커밋하면 안 된다 — 실행 시 환경변수로 주입할 것
const _tok = (name) => {
    const v = process.env[name];
    if (!v) { console.error(`${name} env var required (auth_token)`); process.exit(1); }
    return v;
};
const NEWBIE  = { token: _tok('MF_AUDIT_TOKEN_NEWBIE'),  name: 'AuditNewbie', email: 'audit_newbie@example.com' };
const PRO     = { token: _tok('MF_AUDIT_TOKEN_PRO'),     name: 'AuditPro',    email: 'audit_pro@example.com' };
const ULTRA   = { token: _tok('MF_AUDIT_TOKEN_ULTRA'),   name: 'AuditUltra',  email: 'audit_ultra@example.com' };
const EXPIRED = { token: _tok('MF_AUDIT_TOKEN_EXPIRED'), name: 'AuditExpired',email: 'audit_expired@example.com' };
const ADMIN   = { token: _tok('MF_AUDIT_TOKEN_ADMIN'),   name: 'Admin' };

const OUT_DIR = 'C:/bitman_marketfloww/scripts/audit_screenshots';
fs.mkdirSync(OUT_DIR, { recursive: true });

const findings = [];

function log(msg) { console.log(msg); }
function record(scenario, finding) { findings.push({ scenario, ...finding }); }

async function check(page, scenario, expectedTexts) {
    // textContent 사용 — innerText 는 viewport 영역만 반영, textContent 는 전체 DOM
    const body = await page.evaluate(() => document.body.textContent || '');
    const docW = await page.evaluate(() => document.documentElement.scrollWidth);
    const viewW = await page.evaluate(() => document.documentElement.clientWidth);
    const overflow = docW - viewW;
    const path = await page.evaluate(() => location.pathname);

    const checks = {};
    for (const [name, text] of Object.entries(expectedTexts)) {
        checks[name] = body.includes(text);
    }
    const ok = Object.values(checks).every(v => v);
    log(`  ${ok ? '✅' : '❌'} ${scenario} [${path}] overflow=${overflow}px checks=${JSON.stringify(checks)}`);
    record(scenario, { path, overflow, checks, ok });
    return { ok, body, path, overflow };
}

async function audit() {
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 2,
        isMobile: true,
        hasTouch: true,
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1.15',
    });

    async function loginAs(user) {
        const page = await context.newPage();
        await page.goto('https://bit-man.net/login', { waitUntil: 'domcontentloaded' });
        await page.evaluate((tok) => localStorage.setItem('auth_token', tok), user.token);
        return page;
    }

    // ─── PUBLIC PAGES (no auth) ────────────────────────────────────────────
    log('\n=== W0: 공개 페이지 (4종 플랜 노출 검증) ===');
    {
        const page = await context.newPage();
        await page.goto('https://bit-man.net/', { waitUntil: 'networkidle' });
        await page.waitForTimeout(2000);
        await check(page, 'Landing', { '90,000': true, 'Pro + AI Bain': true, 'Ultra Pro': true });
        await page.screenshot({ path: `${OUT_DIR}/W0_landing.png` });

        await page.goto('https://bit-man.net/pricing', { waitUntil: 'networkidle' });
        await page.waitForTimeout(2000);
        await check(page, 'Pricing 상세', { 'AI Bain 이란': true, 'ALPHA SCAN': true, '90,000': true });
        await page.screenshot({ path: `${OUT_DIR}/W0_pricing.png`, fullPage: true });

        await page.goto('https://bit-man.net/login', { waitUntil: 'networkidle' });
        await page.waitForTimeout(2000);
        await check(page, 'Login 결제 패널', { 'PRO + AI BAIN': true, 'ULTRA PRO + AI BAIN': true, '90,000': true, '1,240,000': true });
        await page.screenshot({ path: `${OUT_DIR}/W0_login.png`, fullPage: true });
        await page.close();
    }

    // ─── W1: 신규 가입자 (pending, tier=null) ────────────────────────────
    log('\n=== W1: 신규 가입자 (pending) ===');
    {
        const page = await loginAs(NEWBIE);
        // /plan-select 자동 리다이렉트 확인
        await page.goto('https://bit-man.net/dashboard', { waitUntil: 'networkidle' });
        await page.waitForTimeout(2500);
        await check(page, 'Newbie /dashboard → /plan-select 리다이렉트', { '플랜을 선택해 주세요': true, 'Pro + AI Bain': true });
        await page.screenshot({ path: `${OUT_DIR}/W1_newbie_planselect.png`, fullPage: true });
        await page.close();
    }

    // ─── W2: 활성 Pro 회원 ──────────────────────────────────────────────
    log('\n=== W2: 활성 Pro 회원 ===');
    {
        const page = await loginAs(PRO);
        await page.goto('https://bit-man.net/dashboard', { waitUntil: 'networkidle' });
        await page.waitForTimeout(3000);
        await check(page, 'Pro Summary - 업그레이드 배너 노출', { 'AI Bain 알파 스캐너 추가': true, '+40,000원/30일': true });
        await page.screenshot({ path: `${OUT_DIR}/W2_pro_summary.png` });

        // AI Bain 페이지 - 업그레이드 폼
        await page.goto('https://bit-man.net/dashboard/ai-bain', { waitUntil: 'networkidle' });
        await page.waitForTimeout(2000);
        await check(page, 'Pro /dashboard/ai-bain - 업그레이드 폼', { 'AI Bain 구독 업그레이드 신청': true, '40,000원': true });
        await page.screenshot({ path: `${OUT_DIR}/W2_pro_aibain_upgrade.png`, fullPage: true });
        await page.close();
    }

    // ─── W3: 활성 Ultra Pro 회원 ───────────────────────────────────────
    log('\n=== W3: 활성 Ultra Pro 회원 ===');
    {
        const page = await loginAs(ULTRA);
        await page.goto('https://bit-man.net/dashboard', { waitUntil: 'networkidle' });
        await page.waitForTimeout(3000);
        await check(page, 'Ultra Summary - 업그레이드 배너 (Ultra Pro)', { 'AI Bain 알파 스캐너 추가': true, 'Ultra Pro 구독 유지': true });
        await page.screenshot({ path: `${OUT_DIR}/W3_ultra_summary.png` });

        await page.goto('https://bit-man.net/dashboard/ai-bain', { waitUntil: 'networkidle' });
        await page.waitForTimeout(2000);
        await check(page, 'Ultra /dashboard/ai-bain - 업그레이드 폼 (Ultra Pro 유지)', { 'AI Bain 구독 업그레이드 신청': true, 'Ultra Pro': true, '40,000원': true });
        await page.screenshot({ path: `${OUT_DIR}/W3_ultra_aibain_upgrade.png`, fullPage: true });
        await page.close();
    }

    // ─── W4: Pro 만료 회원 → /plan-select 강제 리다이렉트 ─────────────
    log('\n=== W4: Pro 만료 회원 → 강제 재구독 ===');
    {
        const page = await loginAs(EXPIRED);
        await page.goto('https://bit-man.net/dashboard', { waitUntil: 'networkidle' });
        await page.waitForTimeout(3000);
        await check(page, 'Expired /dashboard → 강제 리다이렉트', { '플랜을 선택': true });
        await page.screenshot({ path: `${OUT_DIR}/W4_expired_redirect.png`, fullPage: true });
        await page.close();
    }

    // ─── W5: 관리자 대시보드 (stat tile + AI Bain 카드) ───────────────
    log('\n=== W5: 관리자 대시보드 ===');
    {
        const page = await loginAs(ADMIN);
        await page.goto('https://bit-man.net/admin', { waitUntil: 'networkidle' });
        await page.waitForTimeout(3000);
        await check(page, 'Admin 대시보드', { 'AI Bain 활성': true, 'AI Bain 관리': true, 'Pending Subs': true });
        await page.screenshot({ path: `${OUT_DIR}/W5_admin_dashboard.png`, fullPage: true });

        // 구독 탭
        const subTab = await page.$('button:has-text("구독")');
        if (subTab) {
            await subTab.click();
            await page.waitForTimeout(2000);
            await check(page, 'Admin 구독 탭', { '대기 중': true });
            await page.screenshot({ path: `${OUT_DIR}/W5_admin_subscriptions.png`, fullPage: true });
        }

        // 사용자 탭
        const usersTab = await page.$('button:has-text("사용자")');
        if (usersTab) {
            await usersTab.click();
            await page.waitForTimeout(2000);
            await check(page, 'Admin 사용자 탭', { 'Pro': true });
            await page.screenshot({ path: `${OUT_DIR}/W5_admin_users.png`, fullPage: true });
        }

        await page.close();
    }

    await browser.close();

    // ─── Report ─────────────────────────────────────────────────────────
    const report = {
        timestamp: new Date().toISOString(),
        totalChecks: findings.length,
        passed: findings.filter(f => f.ok).length,
        failed: findings.filter(f => !f.ok).length,
        overflowIssues: findings.filter(f => f.overflow > 0),
        findings,
    };
    fs.writeFileSync('C:/bitman_marketfloww/scripts/audit_report.json', JSON.stringify(report, null, 2));
    log('\n=== SUMMARY ===');
    log(`Total: ${report.totalChecks}, Passed: ${report.passed}, Failed: ${report.failed}`);
    log(`Overflow issues: ${report.overflowIssues.length}`);
    if (report.failed > 0) {
        log('\nFailed:');
        findings.filter(f => !f.ok).forEach(f => {
            log(`  - ${f.scenario}: ${JSON.stringify(f.checks)}`);
        });
    }
}

audit().catch(err => { console.error('FATAL:', err); process.exit(1); });
