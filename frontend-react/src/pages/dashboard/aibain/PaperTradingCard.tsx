/**
 * Alpha Position Engine — 가상 매매 카드 (알파캐치형 완결 신호).
 *
 * 구독자에게 필요한 것만: 시장 국면 / 보유 중 포지션(수익률·D-day) /
 * 30일 완결 성과 / 최근 청산. 규칙·면책은 하단 고정 한 줄.
 */

export interface PaperOverview {
    generated_at: string;
    phase: {
        phase: string;
        phase_label: string;
        regime: string;
        breadth: number | null;
        as_of?: string;
    };
    open_positions: {
        id: string; symbol: string; name: string;
        entry_date: string; entry_price: number;
        target_price: number; stop_price: number;
        last_close: number | null; unrealized_pct: number | null;
        held_trading_days: number; max_hold_days: number;
    }[];
    pending: { symbol: string; name: string; detected_at: string }[];
    performance: {
        window_days: number; trades: number; win_rate_pct: number;
        avg_return_pct: number; cumulative_return_pct: number;
        recent: {
            symbol: string; name?: string; return_pct: number;
            exit_date: string; exit_reason: string;
        }[];
        open_count: number;
    };
    rules: { target_pct: number; stop_pct: number; max_hold_trading_days: number };
    disabled: boolean;
}

const PHASE_TONE: Record<string, string> = {
    uptrend_broadening: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300',
    leader_market: 'border-amber-400/30 bg-amber-500/10 text-amber-300',
    downtrend: 'border-rose-400/30 bg-rose-500/10 text-rose-300',
    rebound_early: 'border-sky-400/30 bg-sky-500/10 text-sky-300',
};

const EXIT_LABEL: Record<string, string> = {
    target: '목표가', stop: '손절', expiry: '기간만료', cio_sell: 'CIO 전환',
};

function pct(v: number | null | undefined): string {
    if (v == null || !Number.isFinite(v)) return '—';
    return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
}

function pctTone(v: number | null | undefined): string {
    if (v == null) return 'text-gray-500';
    return v > 0 ? 'text-red-400' : v < 0 ? 'text-blue-400' : 'text-gray-400';
}

export default function PaperTradingCard({ data }: { data: PaperOverview }) {
    const phaseTone = PHASE_TONE[data.phase?.phase] ?? PHASE_TONE.leader_market;
    const perf = data.performance;

    return (
        <div className="rounded-2xl border border-cyan-400/15 bg-[#13151f] overflow-hidden">
            {/* 헤더 — 국면 + 성과 요약 스트립 */}
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 sm:px-5 py-3.5 border-b border-white/[0.05]">
                <div className="flex items-center gap-2">
                    <i className="fas fa-arrows-rotate text-cyan-400 text-xs" />
                    <span className="text-sm font-black">가상 매매 시그널</span>
                    <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-black ${phaseTone}`}>
                        {data.phase?.phase_label ?? '—'}
                    </span>
                </div>
                <div className="flex items-center gap-3 font-mono text-[11px] tabular-nums text-gray-500">
                    <span>30일 승률 <b className="text-white">{perf?.win_rate_pct ?? 0}%</b></span>
                    <span>누적 <b className={pctTone(perf?.cumulative_return_pct)}>{pct(perf?.cumulative_return_pct)}</b></span>
                </div>
            </div>

            {/* 보유 중 */}
            <div className="px-4 sm:px-5 py-4">
                <div className="text-[10px] font-black uppercase tracking-[0.18em] text-gray-600 mb-2.5">
                    보유 중 ({data.open_positions?.length ?? 0})
                </div>
                {(!data.open_positions || data.open_positions.length === 0) ? (
                    <p className="text-[12.5px] text-gray-600 py-2">
                        보유 중인 포지션이 없습니다. 다음 검출을 기다리는 중입니다.
                    </p>
                ) : (
                    <div className="space-y-2">
                        {data.open_positions.map(p => (
                            <div key={p.id}
                                 className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.05] bg-white/[0.02] px-3.5 py-2.5">
                                <div className="min-w-0">
                                    <div className="flex items-center gap-2">
                                        <span className="text-[13.5px] font-bold text-white truncate">{p.name}</span>
                                        <span className="font-mono text-[10px] text-gray-600">{p.symbol}</span>
                                        <span className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[9px] text-gray-500">
                                            D{p.held_trading_days}/{p.max_hold_days}
                                        </span>
                                    </div>
                                    <div className="mt-1 font-mono text-[10.5px] tabular-nums text-gray-600">
                                        진입 {p.entry_price.toLocaleString()} · 목표 {p.target_price.toLocaleString()} · 손절 {p.stop_price.toLocaleString()}
                                    </div>
                                </div>
                                <div className={`shrink-0 text-right font-mono text-[15px] font-black tabular-nums ${pctTone(p.unrealized_pct)}`}>
                                    {pct(p.unrealized_pct)}
                                </div>
                            </div>
                        ))}
                    </div>
                )}
                {data.pending?.length > 0 && (
                    <p className="mt-2 text-[11px] text-gray-600">
                        <i className="far fa-clock mr-1" />
                        진입 대기 {data.pending.length}건 — 다음 거래일 시가 체결
                    </p>
                )}
            </div>

            {/* 최근 청산 */}
            {perf?.recent?.length > 0 && (
                <div className="px-4 sm:px-5 pb-4">
                    <div className="text-[10px] font-black uppercase tracking-[0.18em] text-gray-600 mb-2">
                        최근 청산
                    </div>
                    <div className="space-y-1">
                        {perf.recent.slice(0, 5).map((t, i) => (
                            <div key={`${t.symbol}-${t.exit_date}-${i}`}
                                 className="flex items-center justify-between gap-2 py-1 font-mono text-[11.5px] tabular-nums">
                                <span className="text-gray-400 truncate">{t.name || t.symbol}</span>
                                <span className="flex items-center gap-2 shrink-0">
                                    <span className="text-gray-600 text-[10px]">{EXIT_LABEL[t.exit_reason] ?? t.exit_reason}</span>
                                    <span className="text-gray-600 text-[10px]">{t.exit_date?.slice(5)}</span>
                                    <span className={`font-bold ${pctTone(t.return_pct)}`}>{pct(t.return_pct)}</span>
                                </span>
                            </div>
                        ))}
                    </div>
                    <div className="mt-2 flex items-center gap-3 border-t border-white/[0.04] pt-2 font-mono text-[10.5px] tabular-nums text-gray-500">
                        <span>거래 {perf.trades}건</span>
                        <span>평균 {pct(perf.avg_return_pct)}</span>
                    </div>
                </div>
            )}

            {/* 규칙 + 면책 */}
            <div className="border-t border-white/[0.04] bg-black/20 px-4 sm:px-5 py-2.5">
                <p className="text-[10px] leading-relaxed text-gray-600">
                    규칙: 다음 거래일 시가 진입 · 목표 +{data.rules?.target_pct}% · 손절 −{data.rules?.stop_pct}% ·
                    최대 {data.rules?.max_hold_trading_days}거래일 · CIO SELL 전환 시 조기 청산 —
                    <span className="text-gray-500"> 가상 매매이며 투자 권유가 아닙니다. 투자 책임은 본인에게 있습니다.</span>
                </p>
            </div>
        </div>
    );
}
