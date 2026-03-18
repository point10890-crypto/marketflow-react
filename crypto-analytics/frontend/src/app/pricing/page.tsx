'use client';

import { useSession } from 'next-auth/react';
import Link from 'next/link';

const plans = [
    {
        name: 'Free',
        price: '$0',
        period: 'forever',
        features: [
            'KR Market Overview',
            'Basic VCP Signals',
            'US Market Summary',
            'Crypto Overview',
            'Economic Indicators',
        ],
        missing: [
            'AI Top Picks Report',
            'Smart Money Screener',
            'Risk Alerts & VaR',
            'Decision Signal Engine',
            'Earnings Strategy',
            'Auto Pipeline',
            'Priority Support',
        ],
        cta: 'Current Plan',
        disabled: true,
    },
    {
        name: 'Pro',
        price: '$29',
        period: '/month',
        features: [
            'Everything in Free',
            'AI Top Picks Report',
            'Smart Money Screener',
            'Risk Alerts & VaR/CVaR',
            'Decision Signal Engine',
            'Earnings Impact Strategy',
            'Sector Rotation Analysis',
            'Index Prediction (ML)',
            'Backtest Engine',
            'Auto Pipeline Updates',
            'Priority Support',
        ],
        missing: [],
        cta: 'Upgrade to Pro',
        disabled: false,
        highlight: true,
    },
];

export default function PricingPage() {
    const { data: session } = useSession();
    const userTier = (session?.user as Record<string, unknown>)?.tier as string || 'free';

    const handleUpgrade = async () => {
        const apiToken = (session?.user as Record<string, unknown>)?.apiToken as string;
        if (!apiToken) {
            window.location.href = '/login';
            return;
        }

        try {
            const res = await fetch('/api/stripe/create-checkout', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${apiToken}`,
                },
            });
            const data = await res.json();
            if (data.url) {
                window.location.href = data.url;
            }
        } catch {
            alert('Failed to create checkout session');
        }
    };

    return (
        <div className="min-h-screen bg-black flex flex-col items-center justify-center p-8">
            <div className="text-center mb-12">
                <h1 className="text-5xl font-bold text-white tracking-tighter mb-4">
                    Simple <span className="text-[#2997ff]">Pricing</span>
                </h1>
                <p className="text-gray-400 text-lg">Choose the plan that fits your trading style</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-4xl w-full">
                {plans.map((plan) => (
                    <div
                        key={plan.name}
                        className={`p-8 rounded-2xl border ${plan.highlight
                            ? 'bg-[#1c1c1e] border-[#2997ff]/30 ring-1 ring-[#2997ff]/20'
                            : 'bg-[#1c1c1e] border-white/10'
                            }`}
                    >
                        {plan.highlight && (
                            <div className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-[#2997ff]/10 text-[#2997ff] text-xs font-bold mb-4">
                                <i className="fas fa-star"></i> Recommended
                            </div>
                        )}
                        <h3 className="text-2xl font-bold text-white mb-1">{plan.name}</h3>
                        <div className="flex items-baseline gap-1 mb-6">
                            <span className="text-4xl font-black text-white">{plan.price}</span>
                            <span className="text-gray-500">{plan.period}</span>
                        </div>

                        <ul className="space-y-3 mb-8">
                            {plan.features.map((f) => (
                                <li key={f} className="flex items-center gap-2 text-sm text-gray-300">
                                    <i className="fas fa-check text-green-400 text-xs"></i>
                                    {f}
                                </li>
                            ))}
                            {plan.missing.map((m) => (
                                <li key={m} className="flex items-center gap-2 text-sm text-gray-600">
                                    <i className="fas fa-times text-gray-700 text-xs"></i>
                                    {m}
                                </li>
                            ))}
                        </ul>

                        {plan.highlight && userTier !== 'pro' ? (
                            <button
                                onClick={handleUpgrade}
                                className="w-full py-3 rounded-xl bg-[#2997ff] hover:bg-[#2997ff]/90 text-white font-bold transition-all"
                            >
                                {plan.cta}
                            </button>
                        ) : (
                            <div className="w-full py-3 rounded-xl bg-white/5 text-gray-500 font-bold text-center">
                                {userTier === 'pro' && plan.highlight ? 'Current Plan' : plan.cta}
                            </div>
                        )}
                    </div>
                ))}
            </div>

            <div className="mt-12">
                <Link href="/dashboard" className="text-gray-500 hover:text-white transition-colors text-sm">
                    <i className="fas fa-arrow-left mr-2"></i>Back to Dashboard
                </Link>
            </div>
        </div>
    );
}
