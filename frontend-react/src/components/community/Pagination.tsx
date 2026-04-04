interface PaginationProps {
    page: number;
    totalPages: number;
    onPageChange: (page: number) => void;
}

export default function Pagination({ page, totalPages, onPageChange }: PaginationProps) {
    if (totalPages <= 1) return null;

    // Build page number list: show max 5 around current page with ellipsis
    const pages: (number | 'ellipsis')[] = [];
    const range = 2; // pages before/after current

    if (totalPages <= 7) {
        for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
        pages.push(1);
        const start = Math.max(2, page - range);
        const end = Math.min(totalPages - 1, page + range);
        if (start > 2) pages.push('ellipsis');
        for (let i = start; i <= end; i++) pages.push(i);
        if (end < totalPages - 1) pages.push('ellipsis');
        pages.push(totalPages);
    }

    return (
        <div className="flex items-center justify-center gap-1 mt-6">
            <button
                onClick={() => onPageChange(page - 1)}
                disabled={page <= 1}
                className="px-2.5 py-1 text-xs text-gray-400 rounded-md hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
                이전
            </button>

            {pages.map((p, i) =>
                p === 'ellipsis' ? (
                    <span key={`e-${i}`} className="px-1.5 text-xs text-gray-600">
                        ...
                    </span>
                ) : (
                    <button
                        key={p}
                        onClick={() => onPageChange(p)}
                        className={`min-w-[28px] h-7 text-xs rounded-md transition-colors ${
                            p === page
                                ? 'bg-[#2997ff] text-white font-medium'
                                : 'text-gray-400 hover:bg-white/10'
                        }`}
                    >
                        {p}
                    </button>
                )
            )}

            <button
                onClick={() => onPageChange(page + 1)}
                disabled={page >= totalPages}
                className="px-2.5 py-1 text-xs text-gray-400 rounded-md hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
                다음
            </button>
        </div>
    );
}
