import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { fetchChartAnalogueCandidates, type ChartAnalogueCandidate } from '@/lib/chartAnalogueApi';

const normalizedName = (value: string) => value.replace(/\s+/g, '').toLocaleLowerCase();

export default function ChartAnalogueSymbolSearch({ symbol, token, onSelect, fetchCandidates = fetchChartAnalogueCandidates,
    submitLabel = '유사 사례 조회', hint = '국내 종목명 · 6자리 코드 · 초성 검색 · 일별 종가 기준', idPrefix = 'analogue' }: {
    symbol: string; token?: string; onSelect: (symbol: string) => void;
    fetchCandidates?: (query: string, token?: string) => Promise<ChartAnalogueCandidate[]>;
    submitLabel?: string; hint?: string; idPrefix?: string;
}) {
    const [input, setInput] = useState(symbol);
    const [candidates, setCandidates] = useState<ChartAnalogueCandidate[]>([]);
    const [activeIndex, setActiveIndex] = useState(-1);
    const [searching, setSearching] = useState(false);
    const [error, setError] = useState('');
    const [composing, setComposing] = useState(false);
    const composingRef = useRef(false);
    const sequence = useRef(0);
    const mounted = useRef(true);

    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; sequence.current += 1; };
    }, []);

    useEffect(() => {
        sequence.current += 1;
        setInput(symbol);
        setCandidates([]);
        setActiveIndex(-1);
        setSearching(false);
        setError('');
    }, [symbol, token]);

    const choose = useCallback((candidate: ChartAnalogueCandidate) => {
        sequence.current += 1;
        setInput(candidate.symbol);
        setCandidates([]);
        setActiveIndex(-1);
        setSearching(false);
        setError('');
        onSelect(candidate.symbol);
    }, [onSelect]);

    const search = useCallback(async (query: string, resolve: boolean) => {
        const request = ++sequence.current;
        setSearching(true);
        setError('');
        try {
            const found = await fetchCandidates(query, token);
            if (!mounted.current || sequence.current !== request || composingRef.current) return;
            if (resolve) {
                const exact = found.filter(candidate => normalizedName(candidate.name) === normalizedName(query));
                const match = exact.length === 1 ? exact[0] : exact.length === 0 && found.length === 1 ? found[0] : null;
                if (match) { choose(match); return; }
                setError(found.length ? '여러 종목이 검색되었습니다. 아래에서 종목을 선택해 주세요.'
                    : '검색 결과가 없습니다. 종목명이나 코드를 확인해 주세요.');
            }
            setCandidates(found);
            setActiveIndex(-1);
        } catch {
            if (mounted.current && sequence.current === request) {
                setCandidates([]);
                setError('종목 검색을 완료하지 못했습니다. 다시 조회하거나 6자리 코드를 입력해 주세요.');
            }
        } finally {
            if (mounted.current && sequence.current === request) setSearching(false);
        }
    }, [token, choose, fetchCandidates]);

    useEffect(() => {
        const query = input.trim();
        if (composing || query.length < 2 || /^\d+$/.test(query)) return;
        const expected = sequence.current;
        const timer = setTimeout(() => {
            if (sequence.current === expected) void search(query, false);
        }, 180);
        return () => clearTimeout(timer);
    }, [input, composing, search]);

    function submit(event: FormEvent) {
        event.preventDefault();
        if (composingRef.current) return;
        const query = input.trim();
        if (/^\d{6}$/.test(query)) { choose({ symbol: query, name: query }); return; }
        if (!query || /^\d+$/.test(query)) {
            setError('종목명 또는 국내 종목 코드 6자리를 입력해 주세요.');
            return;
        }
        void search(query, true);
    }

    function keyDown(event: KeyboardEvent<HTMLInputElement>) {
        if (composingRef.current || event.nativeEvent.isComposing || event.keyCode === 229) {
            if (event.key === 'Enter') event.preventDefault();
            return;
        }
        if (event.key === 'Escape') {
            event.preventDefault();
            sequence.current += 1;
            setCandidates([]);
            setActiveIndex(-1);
            setSearching(false);
            setError('');
        } else if (candidates.length && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
            event.preventDefault();
            setActiveIndex(index => event.key === 'ArrowDown' ? (index + 1) % candidates.length
                : index <= 0 ? candidates.length - 1 : index - 1);
        } else if (event.key === 'Enter' && activeIndex >= 0 && candidates[activeIndex]) {
            event.preventDefault();
            choose(candidates[activeIndex]);
        }
    }

    return <div>
        <form onSubmit={submit} className="ai-search-toolbar flex flex-wrap items-end gap-3">
            <div className="relative min-w-0 flex-1 sm:max-w-sm">
                <label htmlFor={`${idPrefix}-code`} className="mb-1.5 block text-xs font-medium text-gray-300">종목명 또는 코드</label>
                <input id={`${idPrefix}-code`} role="combobox" value={input} maxLength={80} autoComplete="off"
                    placeholder="예: 한미반도체, 삼성전자, 005930"
                    aria-autocomplete="list" aria-expanded={candidates.length > 0}
                    aria-controls={`${idPrefix}-symbol-options`}
                    aria-activedescendant={activeIndex >= 0 ? `${idPrefix}-symbol-${candidates[activeIndex]?.symbol}` : undefined}
                    aria-invalid={!!error} aria-describedby={error ? `${idPrefix}-search-error` : `${idPrefix}-code-hint`}
                    onChange={event => {
                        sequence.current += 1;
                        setInput(event.target.value);
                        setCandidates([]);
                        setActiveIndex(-1);
                        setSearching(false);
                        setError('');
                    }} onKeyDown={keyDown}
                    onCompositionStart={() => { composingRef.current = true; sequence.current += 1; setComposing(true); setCandidates([]); setActiveIndex(-1); setSearching(false); }}
                    onCompositionEnd={() => { composingRef.current = false; setComposing(false); }}
                    className="h-11 w-full rounded-lg border border-[#3a424d] bg-[#15191e] px-3 text-sm text-white placeholder:text-gray-500 focus:border-[#72b4fb] focus:outline-none" />
                {candidates.length > 0 && <ul id={`${idPrefix}-symbol-options`} role="listbox" aria-label="종목 검색 결과"
                    className="absolute left-0 right-0 top-full z-30 mt-1 max-h-64 overflow-y-auto rounded-lg border border-[#3a424d] bg-[#15191e] py-1 shadow-xl">
                    {candidates.map((candidate, index) => <li key={candidate.symbol} id={`${idPrefix}-symbol-${candidate.symbol}`} role="option"
                        aria-selected={index === activeIndex} onMouseDown={event => event.preventDefault()}
                        onClick={() => choose(candidate)}
                        className={`flex cursor-pointer items-center justify-between gap-3 px-3 py-3 text-sm hover:bg-[#243c56] ${index === activeIndex ? 'bg-[#243c56]' : ''}`}>
                        <span className="min-w-0 truncate font-medium text-gray-100">{candidate.name}</span>
                        <span className="shrink-0 font-mono text-xs text-gray-400">{candidate.symbol}</span>
                    </li>)}
                </ul>}
            </div>
            <button type="submit" className="h-11 shrink-0 rounded-lg border border-[#365372] bg-[#1b2c40] px-4 text-sm font-semibold text-[#acd3ff] hover:bg-[#243c56]">{submitLabel}</button>
            <p id={`${idPrefix}-code-hint`} className="w-full text-xs text-gray-400">{hint}</p>
        </form>
        {searching && <p role="status" className="mt-2 text-xs text-gray-400">종목 검색 중…</p>}
        {error && <p id={`${idPrefix}-search-error`} role="alert" className="mt-2 text-sm text-amber-300">{error}</p>}
    </div>;
}
