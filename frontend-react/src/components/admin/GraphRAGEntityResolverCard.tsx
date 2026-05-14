import { useCallback, useEffect, useRef, useState, type CompositionEvent as ReactCompositionEvent, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { MiroFishGraphRAGEntityMatch, MiroFishGraphRAGMatchReason, MiroFishGraphRAGResolveResponse, mirofishApi } from '@/lib/mirofishApi';

type ResolverState = 'idle' | 'loading' | 'ready' | 'error' | 'empty';

const MATCH_REASON_LABEL: Record<MiroFishGraphRAGMatchReason, string> = {
    ticker_direct: 'TICKER',
    yahoo_ticker: 'YAHOO',
    corp_code_reverse: 'CORP',
    exact_alias: 'ALIAS',
    exact_name: 'EXACT',
    chosung_exact: '초성',
    chosung_prefix: '초성+',
    prefix_name: 'PREFIX',
    fuzzy: 'FUZZY',
};

const MATCH_REASON_TONE: Record<string, string> = {
    ticker_direct: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-200',
    yahoo_ticker: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-200',
    corp_code_reverse: 'border-cyan-300/25 bg-cyan-300/10 text-cyan-200',
    exact_alias: 'border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-100',
    exact_name: 'border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-100',
    chosung_exact: 'border-amber-400/30 bg-amber-400/10 text-amber-200',
    chosung_prefix: 'border-amber-400/20 bg-amber-400/[0.08] text-amber-100',
    prefix_name: 'border-amber-400/20 bg-amber-400/[0.08] text-amber-100',
    fuzzy: 'border-neutral-400/20 bg-neutral-400/10 text-neutral-300',
};

function matchTone(reason: string): string {
    return MATCH_REASON_TONE[reason] || MATCH_REASON_TONE.fuzzy;
}

function matchLabel(reason: string): string {
    return MATCH_REASON_LABEL[reason as MiroFishGraphRAGMatchReason] || reason.toUpperCase().slice(0, 8);
}

function confidenceTone(value: number): string {
    if (value >= 0.95) return 'text-emerald-300';
    if (value >= 0.8) return 'text-amber-300';
    if (value >= 0.6) return 'text-amber-200';
    return 'text-neutral-400';
}

function MatchRow({ match }: { match: MiroFishGraphRAGEntityMatch }) {
    const pct = Math.max(0, Math.min(1, Number(match.confidence) || 0));
    const ids = match.ids || {};
    const tickerKr = ids.ticker_kr;
    const yahoo = ids.yahoo_ticker;
    const corp = ids.corp_code;
    return (
        <li className="rounded-lg border border-white/10 bg-black/30 p-2.5">
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-baseline gap-1.5">
                        <span className="truncate text-sm font-black text-white">
                            {match.name_ko || match.name || match.symbol || match.entity_id}
                        </span>
                        {match.name_en && match.name_en !== match.name_ko && (
                            <span className="truncate text-[10px] font-bold text-neutral-500">
                                {match.name_en}
                            </span>
                        )}
                    </div>
                    <div className="mt-0.5 truncate font-mono text-[10px] text-neutral-500">
                        {match.entity_id}
                        {match.market && <span className="ml-1.5 text-neutral-400">· {match.market}</span>}
                        {match.exchange && <span className="ml-1 text-neutral-500">{match.exchange}</span>}
                    </div>
                </div>
                <span className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-black tracking-wider ${matchTone(match.match_reason)}`}>
                    {matchLabel(match.match_reason)}
                </span>
            </div>

            <div className="mt-2 flex items-center gap-2">
                <div className="flex-1 overflow-hidden rounded-sm bg-white/[0.05]">
                    <div
                        className="h-1 bg-gradient-to-r from-amber-500/50 via-amber-400/60 to-emerald-400/70 transition-all"
                        style={{ width: `${Math.max(3, pct * 100)}%` }}
                    />
                </div>
                <span className={`shrink-0 font-mono text-[10px] font-black tabular-nums ${confidenceTone(pct)}`}>
                    {(pct * 100).toFixed(1)}%
                </span>
            </div>

            {(tickerKr || yahoo || corp) && (
                <div className="mt-2 flex flex-wrap gap-1 text-[9px] font-bold text-neutral-400">
                    {tickerKr && <span className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5">KR:{tickerKr}</span>}
                    {yahoo && <span className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5">Y:{yahoo}</span>}
                    {corp && <span className="rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5">DART:{corp}</span>}
                </div>
            )}
        </li>
    );
}

export default function GraphRAGEntityResolverCard() {
    const [query, setQuery] = useState('');
    const [state, setState] = useState<ResolverState>('idle');
    const [response, setResponse] = useState<MiroFishGraphRAGResolveResponse | null>(null);
    const [errorText, setErrorText] = useState<string | null>(null);
    const composingRef = useRef(false);
    const lastResolvedRef = useRef('');

    const runResolve = useCallback(async (raw: string) => {
        const q = raw.trim();
        if (!q) {
            setState('idle');
            setResponse(null);
            setErrorText(null);
            return;
        }
        if (q === lastResolvedRef.current) return;
        lastResolvedRef.current = q;
        setState('loading');
        setErrorText(null);
        try {
            const result = await mirofishApi.graphrag.resolveEntity(q, { limit: 5 });
            setResponse(result);
            if (result.error) {
                setErrorText(result.error);
                setState('error');
            } else if (!result.matches?.length) {
                setState('empty');
            } else {
                setState('ready');
            }
        } catch (err) {
            setErrorText(err instanceof Error ? err.message : 'resolve failed');
            setState('error');
        }
    }, []);

    useEffect(() => {
        if (!query.trim()) {
            setState('idle');
            setResponse(null);
            setErrorText(null);
            lastResolvedRef.current = '';
            return;
        }
        const handle = setTimeout(() => {
            if (composingRef.current) return;
            void runResolve(query);
        }, 350);
        return () => clearTimeout(handle);
    }, [query, runResolve]);

    function isComposing(event: ReactKeyboardEvent<HTMLInputElement> | ReactCompositionEvent<HTMLInputElement>) {
        const native = event.nativeEvent as KeyboardEvent & { isComposing?: boolean; keyCode?: number };
        return Boolean(native.isComposing || native.keyCode === 229);
    }

    function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (composingRef.current) return;
        lastResolvedRef.current = '';
        void runResolve(query);
    }

    const matches = response?.matches || [];
    const isBusy = state === 'loading';

    return (
        <section className="rounded-xl border border-amber-500/15 bg-black/60 p-3 sm:p-4">
            <header className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-amber-300/70 sm:text-[11px] sm:tracking-[0.22em]">
                        <i className="fas fa-crosshairs text-amber-400" />
                        <span className="truncate">Entity Resolver</span>
                    </div>
                    <h3 className="mt-1 text-sm font-black text-white sm:text-base">한글 / 티커 / 초성</h3>
                </div>
                {isBusy && (
                    <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-amber-300/70">
                        resolving...
                    </span>
                )}
            </header>

            <form onSubmit={handleSubmit} className="mt-3">
                <label className="flex items-center gap-2 rounded-lg border border-white/10 bg-black/40 px-2.5 py-2 focus-within:border-amber-400/40">
                    <i className="fas fa-magnifying-glass text-xs text-neutral-500" />
                    <input
                        type="text"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        onCompositionStart={() => { composingRef.current = true; }}
                        onCompositionEnd={(event) => {
                            composingRef.current = false;
                            if (isComposing(event)) return;
                        }}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter' && composingRef.current) {
                                event.preventDefault();
                            }
                        }}
                        placeholder="삼성전자, 005930, AAPL, ㅅㅅㅈㅈ"
                        className="w-full bg-transparent text-sm font-medium text-white outline-none placeholder:text-neutral-600"
                        spellCheck={false}
                        autoComplete="off"
                    />
                    {query && (
                        <button
                            type="button"
                            onClick={() => { setQuery(''); }}
                            className="shrink-0 text-[10px] font-bold text-neutral-500 hover:text-neutral-300"
                        >
                            clear
                        </button>
                    )}
                </label>
            </form>

            {errorText && (
                <div className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/10 px-3 py-2 text-xs font-bold text-rose-100 break-words">
                    {errorText}
                </div>
            )}

            {state === 'idle' && (
                <div className="mt-3 rounded-lg border border-dashed border-white/10 bg-white/[0.02] px-3 py-4 text-center text-[11px] font-bold text-neutral-500">
                    Enter a query to resolve to a canonical entity.
                </div>
            )}

            {state === 'empty' && response && (
                <div className="mt-3 rounded-lg border border-white/10 bg-black/30 px-3 py-3 text-[11px] font-bold text-neutral-400">
                    No match for <span className="font-mono text-amber-200">{response.normalized || response.query}</span>.
                </div>
            )}

            {matches.length > 0 && (
                <ul className="mt-3 space-y-2">
                    {matches.map((match) => (
                        <MatchRow key={match.entity_id} match={match} />
                    ))}
                </ul>
            )}

            {response && state === 'ready' && (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-1 text-[10px] font-bold text-neutral-500">
                    <span className="truncate">
                        {matches.length} match{matches.length !== 1 ? 'es' : ''} · {response.source || 'sqlite'}
                    </span>
                    <span className="whitespace-nowrap tabular-nums">{response.asof?.slice(11, 16) || ''}</span>
                </div>
            )}
        </section>
    );
}
