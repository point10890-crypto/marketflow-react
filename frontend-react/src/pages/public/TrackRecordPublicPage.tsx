import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { PublicShell } from '@/components/public/PublicShell';
import GradeBadge from '@/components/stock/GradeBadge';
import { publicTrackRecordAPI, PublicTrackRecord, PublicTrackSignal } from '@/lib/api';
import { useSeo, SITE_ORIGIN } from '@/lib/seo';

/**
 * 공개 Track Record — /track-record (비로그인 열람, FunnelGate 밖).
 *
 * 로드맵 §3.3-4 / §6 "Prove": 종가베팅 V2 의 사후 기록을 지연·마스킹해 공개한다.
 * 숫자는 전부 /api/public/track-record 가 저장된 파일에서 읽은 값이며 이 화면은
 * 아무것도 계산하지 않는다. 표본 수와 검증 대기 수를 항상 함께 보여준다.
 */

const DISCLAIMER = '성과 지표는 사후 검증 결과이며 미래 수익을 보장하지 않습니다.';

function pct(v: number | null | undefined, digits = 1): string {
    if (v == null || Number.isNaN(v)) return '–';
    return `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`;
}

function pctClass(v: number | null | undefined): string {
    if (v == null) return 'text-gray-500';
    return v > 0 ? 'text-red-300' : v < 0 ? 'text-blue-300' : 'text-gray-400';
}

const OUTCOME: Record<string, { label: string; cls: string }> = {
    TARGET_HIT: { label: '목표 도달', cls: 'border-red-400/30 bg-red-500/10 text-red-300' },
    STOP_HIT: { label: '손절', cls: 'border-blue-400/30 bg-blue-500/10 text-blue-300' },
    OPEN: { label: '보유 중', cls: 'border-white/10 bg-white/[0.04] text-gray-300' },
};

function VerificationChip({ s }: { s: PublicTrackSignal }) {
    if (s.verification === 'pending' || !s.forward) {
        return <span className="rounded-full border border-amber-400/25 bg-amber-500/10 px-2 py-0.5 text-[10px] font-bold text-amber-200">검증 대기</span>;
    }
    const o = OUTCOME[s.forward.outcome] ?? OUTCOME.OPEN;
    return <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${o.cls}`}>{o.label}</span>;
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
    return (
        <div className="flex min-h-[86px] flex-col justify-between rounded-2xl border border-white/[0.07] bg-[#0e0e11] p-4">
            <span className="text-[10px] font-bold uppercase tracking-widest text-gray-500">{label}</span>
            <span className="text-2xl font-black tabular-nums text-white">{value}</span>
            {sub && <span className="text-[11px] text-gray-500">{sub}</span>}
        </div>
    );
}

function Row({ s }: { s: PublicTrackSignal }) {
    return (
        <tr className="border-b border-white/[0.05] last:border-0">
            <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[12px] text-gray-400">{s.date}</td>
            <td className="px-3 py-2.5"><GradeBadge grade={s.grade} /></td>
            <td className="px-3 py-2.5">
                <span className={`text-[13px] font-bold ${s.masked ? 'text-gray-300' : 'text-white'}`}>{s.stock_name}</span>
                {s.stock_code
                    ? <span className="ml-2 font-mono text-[11px] text-gray-500">{s.stock_code}</span>
                    : <span className="ml-2 text-[10px] text-gray-600">공개 전</span>}
            </td>
            <td className={`whitespace-nowrap px-3 py-2.5 text-right font-mono text-[12px] tabular-nums ${pctClass(s.change_pct)}`}>{pct(s.change_pct)}</td>
            <td className="whitespace-nowrap px-3 py-2.5 text-right font-mono text-[12px] tabular-nums text-gray-400">
                {s.score_total ?? '–'}
            </td>
            <td className="px-3 py-2.5 text-center"><VerificationChip s={s} /></td>
            <td className={`whitespace-nowrap px-3 py-2.5 text-right font-mono text-[12px] tabular-nums ${pctClass(s.forward_return)}`}>
                {s.forward_return == null ? '–' : pct(s.forward_return, 2)}
            </td>
        </tr>
    );
}

function Card({ s }: { s: PublicTrackSignal }) {
    return (
        <li className="rounded-2xl border border-white/[0.07] bg-[#0e0e11] p-3.5">
            <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                    <GradeBadge grade={s.grade} />
                    <span className={`truncate text-[14px] font-bold ${s.masked ? 'text-gray-300' : 'text-white'}`}>{s.stock_name}</span>
                    {s.stock_code && <span className="font-mono text-[11px] text-gray-500">{s.stock_code}</span>}
                </div>
                <VerificationChip s={s} />
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-gray-500">
                <span className="font-mono">{s.date}</span>
                <span className={`text-right font-mono tabular-nums ${pctClass(s.change_pct)}`}>당일 {pct(s.change_pct)}</span>
                <span className={`text-right font-mono tabular-nums ${pctClass(s.forward_return)}`}>
                    사후 {s.forward_return == null ? '–' : pct(s.forward_return, 2)}
                </span>
            </div>
        </li>
    );
}

export default function TrackRecordPublicPage() {
    useSeo({
        title: '트랙 레코드 — 종가베팅 사후 검증 기록 | MarketFlow',
        description: '종가베팅 V2 가 매 거래일 남긴 신호를 지연·마스킹해 공개합니다. 등급·당일 등락률과 사후 검증 결과를 표본 수와 함께 그대로 보여줍니다.',
        path: '/track-record',
        jsonLd: {
            '@context': 'https://schema.org',
            '@type': 'Dataset',
            name: 'MarketFlow 종가베팅 트랙 레코드 (지연 공개)',
            url: `${SITE_ORIGIN}/track-record`,
            inLanguage: 'ko',
            description: '종가베팅 V2 신호의 지연 공개 기록과 사후 검증 결과',
        },
    });

    const [data, setData] = useState<PublicTrackRecord | null>(null);
    const [error, setError] = useState('');

    useEffect(() => {
        let alive = true;
        publicTrackRecordAPI.get()
            .then((d) => { if (alive) setData(d); })
            .catch(() => { if (alive) setError('기록을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'); });
        return () => { alive = false; };
    }, []);

    const v = data?.verification;
    const grades = data ? ['S', 'A', 'B', 'C'].filter((g) => (data.by_grade[g] ?? 0) > 0) : [];

    return (
        <PublicShell section="track-record">
            <div className="mx-auto max-w-5xl px-4 pb-6 pt-8 sm:px-6 sm:pt-12">
                <header className="pub-rise">
                    <div className="pub-label">// TRACK RECORD · DELAYED</div>
                    <h1 className="mt-2 text-3xl font-black tracking-tight text-white sm:text-4xl">종가베팅 사후 기록</h1>
                    <p className="mt-3 max-w-[60ch] break-keep text-[13px] leading-relaxed text-gray-400 sm:text-sm">
                        매 거래일 14:50 에 저장된 종가베팅 V2 신호를 <b className="text-gray-200">거래일 1일 지연</b>으로 공개합니다.
                        발생 후 거래일 5일 미만인 신호는 종목명 앞 두 글자만 보여주고 종목코드를 숨깁니다(<span className="font-mono text-gray-300">삼성**</span>).
                        당일 신호와 전체 종목명은 구독자 대시보드에서만 볼 수 있습니다. 선별 없이 창 안의 모든 신호를 싣습니다.
                    </p>
                </header>

                {error && (
                    <div className="mt-6 rounded-2xl border border-rose-500/25 bg-rose-500/[0.06] p-4 text-[13px] text-rose-200" role="alert">{error}</div>
                )}

                {!data && !error && (
                    <div className="mt-6 grid gap-3 sm:grid-cols-4" aria-busy="true">
                        {[0, 1, 2, 3].map((i) => <div key={i} className="h-[86px] animate-pulse rounded-2xl border border-white/[0.05] bg-white/[0.02]" />)}
                    </div>
                )}

                {data && (
                    <>
                        <section className="pub-rise mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4" style={{ animationDelay: '60ms' }} aria-label="집계">
                            <Stat label="표본" value={`${data.sample_size}건`} sub={`${data.days_count} 거래일 · ${data.date_range.from ?? '–'} ~ ${data.date_range.to ?? '–'}`} />
                            <Stat label="등급 분포" value={grades.map((g) => `${g}${data.by_grade[g]}`).join(' · ') || '–'} sub={`마스킹 ${data.masked_count}건`} />
                            <Stat label="검증 완료" value={`${v?.evaluated ?? 0}건`} sub={`검증 대기 ${v?.pending ?? 0}건`} />
                            <Stat
                                label="목표 도달률"
                                value={v?.win_rate == null ? '검증 대기' : `${v.win_rate.toFixed(1)}%`}
                                sub={v?.closed ? `종결 ${v.closed}건 · 평균 ${pct(v.avg_roi_pct, 2)}` : '종결된 표본이 아직 없습니다'}
                            />
                        </section>

                        <section className="mt-6" aria-label="신호 목록">
                            <div className="flex items-center justify-between px-1">
                                <h2 className="text-[13px] font-bold text-gray-300">신호 {data.signals.length}건 · 최신순</h2>
                                <span className="text-[11px] text-gray-600">기준일 {data.as_of ?? '–'}</span>
                            </div>
                            {data.signals.length === 0 ? (
                                <div className="mt-3 rounded-2xl border border-white/[0.07] bg-[#0e0e11] p-8 text-center text-[13px] text-gray-500">
                                    아직 공개 가능한 기록이 없습니다. 신호는 거래일 1일 지연 후 공개됩니다.
                                </div>
                            ) : (
                                <>
                                    <div className="mt-3 hidden overflow-x-auto rounded-2xl border border-white/[0.07] bg-[#0e0e11] md:block">
                                        <table className="w-full min-w-[640px] text-left">
                                            <thead>
                                                <tr className="border-b border-white/[0.06] text-[10px] font-bold uppercase tracking-wider text-gray-500">
                                                    <th className="px-3 py-2.5">신호일</th>
                                                    <th className="px-3 py-2.5">등급</th>
                                                    <th className="px-3 py-2.5">종목</th>
                                                    <th className="px-3 py-2.5 text-right">당일 등락</th>
                                                    <th className="px-3 py-2.5 text-right">점수/17</th>
                                                    <th className="px-3 py-2.5 text-center">검증</th>
                                                    <th className="px-3 py-2.5 text-right">사후 수익</th>
                                                </tr>
                                            </thead>
                                            <tbody>{data.signals.map((s, i) => <Row key={`${s.date}-${s.grade}-${i}`} s={s} />)}</tbody>
                                        </table>
                                    </div>
                                    <ul className="mt-3 space-y-2 md:hidden">
                                        {data.signals.map((s, i) => <Card key={`${s.date}-${s.grade}-${i}`} s={s} />)}
                                    </ul>
                                </>
                            )}
                        </section>

                        <section className="mt-8 rounded-2xl border border-white/[0.07] bg-white/[0.02] p-5" aria-label="산출 방식">
                            <h2 className="text-[13px] font-bold text-gray-200">산출 방식</h2>
                            <ul className="mt-3 space-y-1.5 text-[12px] leading-relaxed text-gray-500">
                                {Object.entries(data.methodology).map(([k, text]) => <li key={k}>· {text}</li>)}
                            </ul>
                        </section>
                    </>
                )}

                <p className="mt-6 text-[11px] leading-relaxed text-gray-600">
                    {DISCLAIMER} 투자 판단과 책임은 이용자 본인에게 있으며, 이 페이지는 투자 권유가 아닙니다.
                </p>

                <div className="mt-8 flex flex-col items-start gap-3 rounded-[24px] border border-[#ff8f6d]/20 bg-[#ff8f6d]/[0.05] p-5 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                        <div className="text-[15px] font-black text-white">당일 신호와 근거 11소스는 구독자 화면에서</div>
                        <p className="mt-1 text-[12px] text-gray-400">등급·진입/손절 근거·수급·공시·뉴스를 마스킹 없이, 14:50 저장 직후 확인합니다.</p>
                    </div>
                    <Link to="/pricing" className="inline-flex min-h-[44px] shrink-0 items-center rounded-full bg-[#ff6b57] px-6 text-[13px] font-black text-[#190704] transition-colors hover:bg-[#ff8a76]">
                        요금제 보기<i className="fas fa-arrow-right ml-2 text-[10px]" aria-hidden />
                    </Link>
                </div>
            </div>
        </PublicShell>
    );
}
