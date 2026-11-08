/** The app's primary identity, shared by the mobile header and desktop/drawer navigation. */
export default function AppBrand({ compact = false }: { compact?: boolean }) {
    return (
        <span className={`inline-flex min-w-0 items-center ${compact ? 'gap-2' : 'gap-3'}`}>
            <span aria-hidden="true" className={`relative flex shrink-0 items-center justify-center bg-gradient-to-br from-[#ff8a6b] via-[#ff5a3c] to-[#b91c1c] font-extrabold text-white shadow-lg shadow-[#ff5a3c]/20 ring-1 ring-[#ff8a6b]/30 ${compact ? 'h-7 w-7 rounded-lg text-base' : 'h-9 w-9 rounded-xl text-[22px]'}`}>
                B
            </span>
            <span className="flex min-w-0 flex-col items-start text-left">
                <span className={`inline-flex items-center gap-1.5 font-extrabold leading-none tracking-tight ${compact ? 'text-[17px]' : 'text-[22px]'}`}>
                    <span className="bg-gradient-to-r from-[#ffb4a3] via-[#ff7a5c] to-[#ffb4a3] bg-clip-text text-transparent">BitMan</span>{' '}
                    <span className={`rounded border border-[#7dd3fc]/35 bg-[#7dd3fc]/10 font-bold tracking-wide text-[#b5e9ff] ${compact ? 'px-1 py-0.5 text-[10px]' : 'px-1.5 py-0.5 text-xs'}`}>AI</span>
                </span>{' '}
                <span className={`mt-1 whitespace-nowrap font-medium leading-tight tracking-[-0.02em] text-[#c3d7e6] ${compact ? 'text-[11px]' : 'text-[12px]'}`}>주식분석 에이전트</span>
            </span>
        </span>
    );
}
