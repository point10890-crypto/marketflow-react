'use client';

interface HeaderProps {
    title: string;
}

export default function Header({ title }: HeaderProps) {
    return (
        <header className="h-16 flex items-center justify-between px-6 border-b border-white/5 bg-[#09090b]/80 backdrop-blur-md shrink-0 z-40">
            {/* Breadcrumbs */}
            <div className="flex items-center gap-2">
                <span className="text-gray-500">
                    <i className="fas fa-home"></i>
                </span>
                <span className="text-gray-600">/</span>
                <span className="text-gray-200 font-medium">{title}</span>
            </div>

            {/* Search */}
            <div className="max-w-md w-full mx-4">
                <div className="relative group">
                    <i className="fas fa-search absolute left-3 top-2.5 text-gray-500 group-focus-within:text-blue-500 transition-colors"></i>
                    <input
                        type="text"
                        className="block w-full pl-10 pr-12 py-2 bg-[#18181b] border border-white/10 rounded-full text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all"
                        placeholder="Search markets, tickers, or commands..."
                    />
                    <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none">
                        <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-[10px] font-mono text-gray-500 bg-white/5 rounded border border-gray-600">
                            ⌘K
                        </kbd>
                    </div>
                </div>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-3">
                <button className="p-2 text-gray-400 hover:text-white hover:bg-white/10 rounded-full transition-colors relative">
                    <i className="far fa-bell"></i>
                    <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-red-500 rounded-full border border-black"></span>
                </button>
            </div>
        </header>
    );
}
