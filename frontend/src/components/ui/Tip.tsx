export default function Tip({ text }: { text: string }) {
    return (
        <span className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-52 rounded-lg bg-gray-900 border border-white/10 px-3 py-2 text-[11px] leading-relaxed text-gray-300 font-normal normal-case tracking-normal opacity-0 group-hover:opacity-100 transition-opacity duration-200 z-50 shadow-xl shadow-black/40 text-left">
            {text}
            <span className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
        </span>
    );
}
