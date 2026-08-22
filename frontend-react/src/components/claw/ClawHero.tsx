/**
 * Claw LIVE 히어로 — 랜딩급 이미지 메이킹.
 *
 * 중앙 마스코트(상태가 곧 표정) + 절차 생성 ASCII 집게 텍스처 + 한 줄 헤드라인
 * "진짜 주식 분석하는 인공지능 에이전트." + 검증 가능한 약속(신뢰 칩).
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

export function ClawHero({ data, heartbeatAge }: { data: ClawOverview | null; heartbeatAge: number | null }) {
    const state = data?.loop.state ?? null;
    const mood = MOOD[state ?? 'idle'];
    const tone = state === 'halt' ? 'amber' : state === 'dead' ? 'gray' : 'teal';
    const badge = state === 'running' ? 'LIVE' : state === 'halt' ? 'HOLD' : state === 'dead' ? 'OFFLINE' : 'REST';
    return (
        <section className="relative overflow-hidden rounded-3xl border border-white/[0.06] bg-[#0a0c11]">
            <ClawAsciiBackdrop live={state === 'running'} tone={tone} />
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_70%_at_50%_45%,rgba(45,212,191,.10),rgba(0,0,0,0)_70%)]" />

            <div className="relative flex flex-col items-center px-5 pb-6 pt-9 text-center sm:px-8 sm:pt-11">
                <ClawMascot state={state} size={112} className="drop-shadow-[0_14px_36px_rgba(45,212,191,.22)]" />

                <p className="mt-4 font-mono text-[11px] tracking-[0.28em] text-gray-400 sm:text-[12px]">
                    관찰 전용 · 사용자 PC에서 실행 · 매매 없음
                </p>

                <h1 className="mt-3 text-[30px] font-black leading-[1.12] tracking-tight text-white sm:text-[44px]">
                    <span className="claw-brush mr-2 text-[1.18em] font-normal text-[#ff6b57]">진짜</span>
                    주식 분석하는 인공지능 에이전트<span className="text-[#ff6b57]">.</span>
                </h1>

                <div className="mt-4 flex flex-wrap items-center justify-center gap-x-3 gap-y-1.5">
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-teal-400/25 bg-teal-500/10 px-3 py-1 text-[11px] font-bold text-teal-300">
                        <span className="relative grid h-2 w-2 place-items-center">
                            <span className={`absolute inline-flex h-2 w-2 rounded-full ${state === 'running' ? 'bg-teal-400/60 animate-ping' : ''}`} />
                            <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${state === 'running' ? 'bg-teal-400' : state === 'halt' ? 'bg-amber-400' : state === 'dead' ? 'bg-red-500' : 'bg-gray-500'}`} />
                        </span>
                        Claw LIVE · {badge}
                    </span>
                    <span className="text-[14px] font-semibold text-gray-100">{data ? mood.line : '불러오는 중이에요…'}</span>
                    {data && <span className="text-[12px] text-gray-400">{mood.sub}</span>}
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
                <li key={c.text} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${c.tone === 'ok' ? 'border-teal-400/25 bg-teal-500/[0.08] text-teal-200' : 'border-white/[0.08] bg-white/[0.03] text-gray-300'}`}>
                    <i className={`fas ${c.icon} text-[10px] ${c.tone === 'ok' ? 'text-teal-300' : 'text-gray-500'}`} />{c.text}
                </li>
            ))}
        </ul>
    );
}
