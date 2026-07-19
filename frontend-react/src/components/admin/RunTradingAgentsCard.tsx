/**
 * RunTradingAgentsCard — run-scoped TradingAgents 딥검증 버튼 + 결과 카드.
 *
 * 단일 MiroFish 라이브 run 상세 화면에 삽입. 버튼 클릭 시
 * POST /api/admin/mirofish/runs/<run_id>/tradingagents 호출,
 * verdict(STRONG_BUY/BUY/HOLD/SELL) + 레짐 보정 + 강세/약세 근거를 표시.
 */
import { useState } from 'react';
import { mirofishApi, type RunTradingAgentsResult } from '@/lib/mirofishApi';

const VERDICT_STYLE: Record<string, string> = {
    STRONG_BUY: 'text-emerald-300 border-emerald-400/40 bg-emerald-500/10',
    BUY: 'text-sky-300 border-sky-400/40 bg-sky-500/10',
    HOLD: 'text-gray-300 border-white/15 bg-white/5',
    SELL: 'text-rose-300 border-rose-400/40 bg-rose-500/10',
};

export default function RunTradingAgentsCard({ runId }: { runId: string }) {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [result, setResult] = useState<RunTradingAgentsResult | null>(null);

    const run = async () => {
        setLoading(true); setError('');
        try {
            setResult(await mirofishApi.runTradingAgentsForRun(runId));
        } catch (e: any) {
            setError(e?.message || 'TradingAgents 딥검증 실패');
        } finally {
            setLoading(false);
        }
    };

    const v = result?.verdict;
    const adj = v?.regime_adjustment;
    return (
        <div className="rounded-2xl border border-white/10 bg-[#0e0e11] p-5">
            <div className="flex items-center justify-between gap-3 mb-3">
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <i className="fas fa-shield-halved text-cyan-400" />TradingAgents 딥검증
                </h3>
                <button onClick={run} disabled={loading}
                    className="px-3 py-1.5 rounded-lg text-xs font-bold bg-cyan-500/15 text-cyan-300 hover:bg-cyan-500/25 disabled:opacity-40">
                    {loading ? <><i className="fas fa-spinner fa-spin mr-1" />검증 중…</> : 'Brain 13D로 딥검증'}
                </button>
            </div>
            {error && <div className="text-rose-400 text-xs mb-2">{error}</div>}
            {v && (
                <div className="space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className={`px-2 py-0.5 rounded-md border text-xs font-black ${VERDICT_STYLE[v.verdict] || VERDICT_STYLE.HOLD}`}>{v.verdict}</span>
                        <span className="text-xs text-gray-400">확신 {Math.round(v.confidence)}%</span>
                        {v.strong_buy && <span className="text-xs font-bold text-orange-300">🔥 매수 유력</span>}
                        {result?.method && <span className="text-[10px] text-gray-500 uppercase">{result.method}</span>}
                    </div>
                    {v.regime && (
                        <div className="text-[11px] text-gray-400">
                            레짐 <span className="text-gray-200">{v.regime}</span>
                            {adj && adj.applied ? <> · 보정 <span className={adj.applied > 0 ? 'text-emerald-300' : 'text-rose-300'}>{adj.applied > 0 ? '+' : ''}{adj.applied}</span></> : null}
                        </div>
                    )}
                    {v.bull_case && <p className="text-[11px] text-emerald-200/80"><b>강세</b> {v.bull_case}</p>}
                    {v.bear_case && <p className="text-[11px] text-rose-200/80"><b>약세</b> {v.bear_case}</p>}
                </div>
            )}
        </div>
    );
}
