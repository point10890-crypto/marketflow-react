/**
 * Claw 브랜드 히어로 — 레퍼런스 톤(빨간 크랩 + 붉은 아우라 + ASCII 집게)으로 통일.
 *
 * variant
 *  - full    : Claw LIVE 페이지 상단. 큰 마스코트 + 헤드라인 + 상태 문장 + 신뢰 칩
 *  - compact : 대시보드 전 페이지 공통 브랜드 바(DashboardLayout). 한 줄 높이, 같은 마스코트·헤드라인
 * 외부 브랜드 자산·이미지 파일 없음 — 전부 코드로 그린다.
 */
import { Link } from 'react-router-dom';
import ClawMascot from '@/components/claw/ClawMascot';
import ClawAsciiBackdrop from '@/components/claw/ClawAsciiBackdrop';
import { ClawOverview, fmtAge } from '@/lib/claw';

const MOOD: Record<string, { line: string; sub: string }> = {
    running: { line: '지금 장을 5초마다 보고 있어요.', sub: '주도주 등급이 바뀌는 순간만 알립니다.' },
    idle: { line: '지금은 장외예요. 09:00에 다시 깨어납니다.', sub: '아래는 마지막 세션 기준입니다.' },
    halt: { line: '데이터가 불안해서 판단을 멈췄어요.', sub: '확실하지 않으면 말하지 않는 것이 Claw의 규칙입니다.' },
    dead: { line: '루프 응답이 없어요. 워치독이 재기동을 기다립니다.', sub: '복구되면 이 자리에서 바로 다시 시작합니다.' },
};

function badgeOf(state: string | null): string {
    return state === 'running' ? 'LIVE' : state === 'halt' ? 'HOLD' : state === 'dead' ? 'OFFLINE' : 'REST';
}
function toneOf(state: string | null): 'red' | 'amber' | 'gray' {
    return state === 'halt' ? 'amber' : state === 'dead' ? 'gray' : 'red';
}
function dotOf(state: string | null): string {
    return state === 'running' ? 'bg-[#ff5a3c]' : state === 'halt' ? 'bg-amber-400' : state === 'dead' ? 'bg-gray-500' : 'bg-[#c2410c]';
}

export function Headline({ size = 'lg' }: { size?: 'lg' | 'sm' }) {
    const cls = size === 'lg'
        ? 'text-[26px] font-black leading-[1.12] tracking-tight text-white sm:text-[44px]'
        : 'text-[17px] font-black leading-none tracking-tight text-white sm:text-[20px]';
    return (
        <span className={cls}>
            <span className={`claw-brush text-[#ff6b57] ${size === 'lg' ? 'mr-2 text-[1.18em]' : 'mr-1.5 text-[1.2em]'} font-normal`}>진짜</span>
            주식 분석하는 인공지능 에이전트<span className="text-[#ff6b57]">.</span>
        </span>
    );
}

function LiveBadge({ state }: { state: string | null }) {
    return (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[#ff5a3c]/30 bg-[#ff5a3c]/10 px-3 py-1 text-[11px] font-bold text-[#ffb4a3]">
            <span className="relative grid h-2 w-2 place-items-center">
                <span className={`absolute inline-flex h-2 w-2 rounded-full ${state === 'running' ? 'bg-[#ff5a3c]/60 animate-ping' : ''}`} />
                <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${dotOf(state)}`} />
            </span>
            Claw LIVE · {badgeOf(state)}
        </span>
    );
}

export function ClawHero({ data, heartbeatAge }: { data: ClawOverview | null; heartbeatAge: number | null }) {
    const state = data?.loop.state ?? null;
    const mood = MOOD[state ?? 'idle'];
    return (
        <section className="relative overflow-hidden rounded-3xl border border-[#ff5a3c]/15 bg-[#0a0709]">
            <ClawAsciiBackdrop live={state === 'running'} tone={toneOf(state)} />
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(55%_65%_at_50%_42%,rgba(255,90,60,.22),rgba(255,90,60,0)_70%)]" />

            <div className="relative flex flex-col items-center px-4 pb-5 pt-6 text-center sm:px-8 sm:pb-6 sm:pt-11">
                <ClawMascot state={state} size={116} className="drop-shadow-[0_16px_40px_rgba(255,90,60,.35)] max-sm:h-[84px] max-sm:w-[84px]" />
                <p className="mt-3 font-mono text-[10px] tracking-[0.22em] text-gray-400 sm:mt-4 sm:text-[12px] sm:tracking-[0.28em]">관찰 전용 · 사용자 PC에서 실행 · 매매 없음</p>
                <h1 className="mt-3"><Headline size="lg" /></h1>

                <div className="mt-4 flex flex-wrap items-center justify-center gap-x-3 gap-y-1.5">
                    <LiveBadge state={state} />
                    <span className="text-[14px] font-semibold text-gray-100">{data ? mood.line : '불러오는 중이에요…'}</span>
                    {data && <span className="hidden text-[12px] text-gray-400 sm:inline">{mood.sub}</span>}
                </div>
                {data && (
                    <p className="mt-2 text-[11px] text-gray-500">
                        {data.loop.last_tick_ts ? `마지막 틱 ${data.loop.last_tick_ts.slice(5, 16).replace('T', ' ')}` : '아직 틱 없음'}
                        {data.loop.source && ` · ${data.loop.source} ${fmtAge(data.loop.source_age_s)} 전`}
                        {heartbeatAge != null && ` · 하트비트 ${fmtAge(heartbeatAge)} 전`}
                    </p>
                )}
                {data && <TrustChips data={data} />}
                <Link to="/dashboard/kr/leading-stocks" className="mt-4 inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2 text-[12px] font-bold text-gray-300 transition-colors hover:bg-white/[0.08] hover:text-white">
                    <i className="fas fa-chart-line text-[11px]" />주도주LIVE 열기
                </Link>
            </div>
        </section>
    );
}

/** 대시보드 전 페이지 공통 브랜드 바 — 메인 타이틀 고정. 링크는 Claw LIVE 전체 화면. */
export function ClawBrandBar({ data }: { data: ClawOverview | null }) {
    const state = data?.loop.state ?? null;
    const mood = MOOD[state ?? 'idle'];
    return (
        <Link
            to="/dashboard/kr/claw"
            className="claw-brand-bar group relative mb-3 block overflow-hidden rounded-2xl border bg-[#0a0709] transition-colors hover:border-[#ff5a3c]/35 md:mb-4"
            aria-label="Claw LIVE 열기"
        >
            <ClawAsciiBackdrop live={state === 'running'} tone={toneOf(state)} />
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(40%_120%_at_12%_50%,rgba(255,90,60,.22),rgba(255,90,60,0)_70%)]" />
            <div className="relative flex items-center gap-3 px-3.5 py-2.5 sm:gap-4 sm:px-5">
                <ClawMascot state={state} size={46} className="shrink-0 drop-shadow-[0_6px_18px_rgba(255,90,60,.35)]" />
                <div className="min-w-0 flex-1">
                    <div className="truncate"><Headline size="sm" /></div>
                    <div className="claw-brand-mood mt-0.5 hidden truncate text-[11px] text-gray-400 sm:block">{data ? mood.line : '관찰 전용 · 사용자 PC에서 실행 · 매매 없음'}</div>
                </div>
                <LiveBadge state={state} />
                <i className="fas fa-chevron-right hidden text-[11px] text-gray-600 transition-colors group-hover:text-gray-300 sm:block" />
            </div>
        </Link>
    );
}

/** 검증 가능한 약속 — 전부 코드·테스트로 고정된 규칙. 숫자는 오늘 실제 값. */
export function TrustChips({ data }: { data: ClawOverview }) {
    const s = data.system;
    const chips: { icon: string; text: string; tone?: 'ok' | 'muted' }[] = [
        { icon: 'fa-eye', text: '관찰 전용 · 매매 없음' },
        { icon: 'fa-layer-group', text: `이탈은 ${s.drop_confirm_ticks}틱 연속일 때만 확정` },
        { icon: 'fa-shield-halved', text: '같은 알림 두 번 안 보냄' },
        { icon: 'fa-clock-rotate-left', text: '룩어헤드 없는 성과 기록' },
        { icon: 'fa-receipt', text: `발송 원장 공개 · 오늘 ${s.briefs_delivered_today}/${s.briefs_today}`, tone: s.briefs_today ? 'ok' : 'muted' },
    ];
    return (
        <ul className="mt-4 flex flex-wrap justify-center gap-1.5">
            {chips.map(c => (
                <li key={c.text} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${c.tone === 'ok' ? 'border-[#ff5a3c]/30 bg-[#ff5a3c]/[0.10] text-[#ffc6ba]' : 'border-white/[0.08] bg-white/[0.03] text-gray-300'}`}>
                    <i className={`fas ${c.icon} text-[10px] ${c.tone === 'ok' ? 'text-[#ff8a6b]' : 'text-gray-500'}`} />{c.text}
                </li>
            ))}
        </ul>
    );
}
