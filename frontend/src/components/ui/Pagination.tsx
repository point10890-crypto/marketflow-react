export default function Pagination({ current, total, count, pageSize, onChange }: {
    current: number;
    total: number;
    count: number;
    pageSize: number;
    onChange: (page: number) => void;
}) {
    const from = current * pageSize + 1;
    const to = Math.min((current + 1) * pageSize, count);

    return (
        <div className="flex items-center justify-between px-4 py-3 border-t border-white/5">
            <span className="text-[11px] text-gray-500">
                {from}–{to} of {count}
            </span>
            <div className="flex items-center gap-1">
                <button
                    onClick={() => onChange(0)}
                    disabled={current === 0}
                    className="px-2 py-1 rounded text-[11px] text-gray-400 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                    <i className="fas fa-angle-double-left"></i>
                </button>
                <button
                    onClick={() => onChange(current - 1)}
                    disabled={current === 0}
                    className="px-2 py-1 rounded text-[11px] text-gray-400 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                    <i className="fas fa-angle-left"></i>
                </button>
                <span className="px-3 py-1 text-[11px] text-gray-300 font-mono">
                    {current + 1} / {total}
                </span>
                <button
                    onClick={() => onChange(current + 1)}
                    disabled={current >= total - 1}
                    className="px-2 py-1 rounded text-[11px] text-gray-400 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                    <i className="fas fa-angle-right"></i>
                </button>
                <button
                    onClick={() => onChange(total - 1)}
                    disabled={current >= total - 1}
                    className="px-2 py-1 rounded text-[11px] text-gray-400 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                    <i className="fas fa-angle-double-right"></i>
                </button>
            </div>
        </div>
    );
}
