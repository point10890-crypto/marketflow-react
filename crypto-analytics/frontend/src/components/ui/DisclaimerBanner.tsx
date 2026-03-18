'use client';

import { useState } from 'react';
import Link from 'next/link';

export default function DisclaimerBanner() {
    const [dismissed, setDismissed] = useState(false);

    if (dismissed) return null;

    return (
        <div className="mx-6 mb-4 px-4 py-3 rounded-xl bg-yellow-500/5 border border-yellow-500/20 flex items-center gap-3">
            <i className="fas fa-exclamation-triangle text-yellow-500 text-sm shrink-0"></i>
            <p className="text-xs text-yellow-400/80 flex-1">
                Not financial advice. Educational purposes only. Past performance does not guarantee future results.{' '}
                <Link href="/disclaimer" className="underline hover:text-yellow-300">Full Disclaimer</Link>
            </p>
            <button
                onClick={() => setDismissed(true)}
                className="text-yellow-500/50 hover:text-yellow-400 transition-colors shrink-0"
            >
                <i className="fas fa-times text-xs"></i>
            </button>
        </div>
    );
}
