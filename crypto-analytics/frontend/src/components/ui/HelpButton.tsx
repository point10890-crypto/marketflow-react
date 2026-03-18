'use client';

import { useState, useEffect, useCallback } from 'react';

interface HelpSection {
    heading: string;
    body: string;
}

interface HelpButtonProps {
    title: string;
    sections: HelpSection[];
}

export default function HelpButton({ title, sections }: HelpButtonProps) {
    const [open, setOpen] = useState(false);

    const close = useCallback(() => setOpen(false), []);

    useEffect(() => {
        if (!open) return;
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [open, close]);

    return (
        <>
            <button
                onClick={() => setOpen(true)}
                className="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 hover:border-white/20 transition-all shrink-0"
                title="도움말"
            >
                <span className="text-sm font-bold">?</span>
            </button>

            {open && (
                <div className="fixed inset-0 z-[100] flex justify-end">
                    {/* Overlay */}
                    <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={close} />

                    {/* Panel */}
                    <div className="relative w-full max-w-md bg-[#1c1c1e] border-l border-white/10 overflow-y-auto animate-slide-in-right">
                        {/* Header */}
                        <div className="sticky top-0 z-10 flex items-center justify-between p-5 border-b border-white/10 bg-[#1c1c1e]/95 backdrop-blur-sm">
                            <div className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded-lg bg-[#2997ff]/10 flex items-center justify-center">
                                    <i className="fas fa-question text-[#2997ff] text-sm"></i>
                                </div>
                                <h3 className="text-lg font-bold text-white">{title}</h3>
                            </div>
                            <button
                                onClick={close}
                                className="w-8 h-8 rounded-lg bg-white/5 hover:bg-white/10 flex items-center justify-center text-gray-400 hover:text-white transition-all"
                            >
                                <i className="fas fa-times text-sm"></i>
                            </button>
                        </div>

                        {/* Content */}
                        <div className="p-5 space-y-6">
                            {sections.map((section, i) => (
                                <div key={i}>
                                    <h4 className="text-sm font-bold text-white mb-2 flex items-center gap-2">
                                        <span className="w-5 h-5 rounded-md bg-[#2997ff]/10 flex items-center justify-center text-[10px] text-[#2997ff] font-black">
                                            {i + 1}
                                        </span>
                                        {section.heading}
                                    </h4>
                                    <p className="text-sm text-gray-400 leading-relaxed whitespace-pre-line">
                                        {section.body}
                                    </p>
                                </div>
                            ))}
                        </div>

                        {/* Footer */}
                        <div className="p-5 border-t border-white/10">
                            <p className="text-[10px] text-gray-600 text-center">
                                이 정보는 교육 목적으로만 제공됩니다. 투자 조언이 아닙니다.
                            </p>
                        </div>
                    </div>
                </div>
            )}

            <style jsx>{`
                @keyframes slideInRight {
                    from { transform: translateX(100%); }
                    to { transform: translateX(0); }
                }
                .animate-slide-in-right {
                    animation: slideInRight 0.25s ease-out;
                }
            `}</style>
        </>
    );
}
