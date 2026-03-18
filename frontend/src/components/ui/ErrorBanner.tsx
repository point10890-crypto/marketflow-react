'use client';

import { useState } from 'react';

export default function ErrorBanner({ message, onRetry, onDismiss }: {
    message: string;
    onRetry?: () => void;
    onDismiss?: () => void;
}) {
    const [visible, setVisible] = useState(true);
    if (!visible) return null;

    return (
        <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-sm">
            <i className="fas fa-exclamation-triangle text-red-400 shrink-0"></i>
            <span className="text-red-400 flex-1">{message}</span>
            {onRetry && (
                <button
                    onClick={onRetry}
                    className="px-3 py-1 rounded-lg text-xs font-bold text-red-400 bg-red-500/10 border border-red-500/20 hover:bg-red-500/20 transition-colors shrink-0"
                >
                    Retry
                </button>
            )}
            <button
                onClick={() => { setVisible(false); onDismiss?.(); }}
                className="text-red-400/60 hover:text-red-400 transition-colors shrink-0"
            >
                <i className="fas fa-times text-xs"></i>
            </button>
        </div>
    );
}
