import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE, API_HEADERS } from '@/lib/api';

interface Stock {
    name: string;
    name_kr?: string;
    ticker: string;
    code: string;
    market: string;
    type: string;
}

interface CommandPaletteProps {
    open: boolean;
    onClose: () => void;
}

export default function CommandPalette({ open, onClose }: CommandPaletteProps) {
    const navigate = useNavigate();
    const [query, setQuery] = useState('');
    const [results, setResults] = useState<Stock[]>([]);
    const [selected, setSelected] = useState(0);
    const inputRef = useRef<HTMLInputElement>(null);
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        if (open) {
            setQuery('');
            setResults([]);
            setSelected(0);
            setTimeout(() => inputRef.current?.focus(), 50);
        }
    }, [open]);

    useEffect(() => {
        const handleKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && open) onClose();
        };
        window.addEventListener('keydown', handleKey);
        return () => window.removeEventListener('keydown', handleKey);
    }, [open, onClose]);

    const searchStocks = useCallback(async (q: string) => {
        if (!q.trim()) { setResults([]); return; }
        try {
            const res = await fetch(
                `${API_BASE}/api/stock-analyzer/search?q=${encodeURIComponent(q)}`,
                { headers: API_HEADERS }
            );
            if (res.ok) {
                const data = await res.json();
                setResults(data);
                setSelected(0);
            }
        } catch { setResults([]); }
    }, []);

    const handleInput = (val: string) => {
        setQuery(val);
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => searchStocks(val), 300);
    };

    const goToAnalyzer = (stock: Stock) => {
        const params = new URLSearchParams({
            name: stock.name,
            ticker: stock.ticker,
            code: stock.code,
            market: stock.market,
        });
        onClose();
        navigate(`/dashboard/stock-analyzer?${params.toString()}`);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setSelected(prev => Math.min(prev + 1, results.length - 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setSelected(prev => Math.max(prev - 1, 0));
        } else if (e.key === 'Enter' && results.length > 0) {
            e.preventDefault();
            goToAnalyzer(results[selected]);
        }
    };

    if (!open) return null;

    return (
        <div className="fixed inset-0 z-[999] flex items-start justify-center pt-[15vh]" onClick={onClose}>
            <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

            <div
                className="relative w-full max-w-lg mx-4 bg-[#0a0a0c] border border-white/10 rounded-xl shadow-2xl overflow-hidden"
                onClick={e => e.stopPropagation()}
            >
                <div className="flex items-center px-4 border-b border-white/5">
                    <i className="fas fa-search text-gray-500 text-sm mr-3"></i>
                    <input
                        ref={inputRef}
                        type="text"
                        value={query}
                        onChange={e => handleInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        className="w-full py-3.5 bg-transparent text-sm text-white placeholder-gray-500 outline-none"
                        placeholder="종목명 또는 티커를 입력하세요..."
                    />
                    {query && (
                        <button onClick={() => handleInput('')} className="text-gray-500 hover:text-white ml-2">
                            <i className="fas fa-times text-xs"></i>
                        </button>
                    )}
                </div>

                {results.length > 0 && (
                    <div className="max-h-64 overflow-y-auto">
                        {results.map((stock, i) => (
                            <button
                                key={`${stock.type}-${stock.ticker}`}
                                onClick={() => goToAnalyzer(stock)}
                                className={`w-full flex items-center justify-between px-4 py-2.5 text-left transition-colors ${
                                    i === selected ? 'bg-blue-500/10 text-white' : 'text-gray-300 hover:bg-white/5'
                                }`}
                            >
                                <div className="flex items-center gap-3">
                                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                                        stock.type === 'US' ? 'bg-blue-500/20 text-blue-400' : 'bg-emerald-500/20 text-emerald-400'
                                    }`}>{stock.type}</span>
                                    <span className="text-sm">{stock.name_kr || stock.name}</span>
                                    <span className="text-xs text-gray-500">{stock.ticker}</span>
                                </div>
                                <i className="fas fa-arrow-right text-[10px] text-gray-600"></i>
                            </button>
                        ))}
                    </div>
                )}

                {results.length === 0 && query === '' && (
                    <div className="px-4 py-6 text-center">
                        <p className="text-gray-600 text-xs">종목을 검색하면 ProPicks 분석 페이지로 이동합니다</p>
                    </div>
                )}

                <div className="flex items-center justify-between px-4 py-2 border-t border-white/5 bg-white/[0.02]">
                    <div className="flex items-center gap-3 text-[10px] text-gray-600">
                        <span><kbd className="px-1 py-0.5 bg-white/5 rounded border border-gray-700 font-mono">↑↓</kbd> 이동</span>
                        <span><kbd className="px-1 py-0.5 bg-white/5 rounded border border-gray-700 font-mono">Enter</kbd> 선택</span>
                        <span><kbd className="px-1 py-0.5 bg-white/5 rounded border border-gray-700 font-mono">Esc</kbd> 닫기</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
