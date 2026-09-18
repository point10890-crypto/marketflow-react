/** 등급 배지 — 종가베팅·주도주 S/A/B/C 공통 색 (KrClosingBet·TrackRecord 와 동일 팔레트). */
const GRADE_STYLE: Record<string, string> = {
    S: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    A: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    B: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
    C: 'bg-red-500/20 text-red-400 border-red-500/30',
};

export default function GradeBadge({ grade, className = '' }: { grade?: string | null; className?: string }) {
    const g = String(grade || '-').toUpperCase();
    return (
        <span className={`inline-flex min-w-[22px] items-center justify-center rounded border px-1.5 py-0.5 text-[10px] font-bold ${GRADE_STYLE[g] ?? 'bg-white/[0.04] text-gray-500 border-white/10'} ${className}`}>
            {g}
        </span>
    );
}
