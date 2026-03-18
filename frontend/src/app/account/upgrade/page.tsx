'use client';

import { useState } from 'react';
import { useSession } from 'next-auth/react';
import { stripeAPI } from '@/lib/api';

export default function UpgradePage() {
    const { data: session } = useSession();
    const user = session?.user as Record<string, unknown> | undefined;
    const apiToken = (user?.apiToken as string) || '';
    const tier = (user?.tier as string) || 'free';
    const [loading, setLoading] = useState(false);

    const handleUpgrade = async () => {
        if (!apiToken) return;
        setLoading(true);
        try {
            const res = await stripeAPI.createCheckout(apiToken);
            if (res.url) {
                window.location.href = res.url;
            } else if (res.status === 'not_configured') {
                alert('Payment system is not configured yet. Please contact support.');
            }
        } catch (err) {
            console.error('Checkout error:', err);
            alert('Failed to start checkout. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    if (tier === 'pro') {
        return (
            <div className="max-w-lg mx-auto text-center py-12">
                <i className="fas fa-crown text-yellow-400 text-4xl mb-4"></i>
                <h1 className="text-2xl font-bold text-white mb-2">Already Pro!</h1>
                <p className="text-gray-400">You already have full access to all MarketFlow features.</p>
            </div>
        );
    }

    return (
        <div className="max-w-lg mx-auto space-y-6">
            <h1 className="text-2xl font-bold text-white text-center">Upgrade to Pro</h1>

            <div className="apple-glass rounded-2xl p-8 border border-purple-500/20">
                <div className="text-center mb-6">
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-500/10 text-purple-400 text-sm font-semibold mb-4">
                        <i className="fas fa-crown"></i> MarketFlow Pro
                    </div>
                    <div className="text-4xl font-bold text-white mb-1">
                        $29<span className="text-lg text-gray-400 font-normal">/mo</span>
                    </div>
                    <div className="text-sm text-gray-500">Cancel anytime</div>
                </div>

                <div className="space-y-3 mb-8">
                    {[
                        'AI-Powered BTC Price Prediction',
                        'Portfolio Risk Analysis (VaR/CVaR)',
                        'Lead-Lag Granger Causality',
                        'Full Backtest Results & History',
                        'Advanced Signal Analysis & Scoring',
                        'Priority Support',
                    ].map((feature) => (
                        <div key={feature} className="flex items-center gap-3">
                            <i className="fas fa-check-circle text-purple-400"></i>
                            <span className="text-sm text-white">{feature}</span>
                        </div>
                    ))}
                </div>

                <button
                    onClick={handleUpgrade}
                    disabled={loading || !apiToken}
                    className="w-full py-3 bg-gradient-to-r from-purple-500 to-indigo-500 text-white rounded-xl font-semibold text-sm hover:from-purple-600 hover:to-indigo-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {loading ? (
                        <><i className="fas fa-spinner fa-spin mr-2"></i>Processing...</>
                    ) : (
                        <><i className="fas fa-rocket mr-2"></i>Upgrade Now</>
                    )}
                </button>

                <p className="text-xs text-gray-500 text-center mt-4">
                    After payment, your account will be upgraded upon admin approval (usually within 24 hours).
                </p>
            </div>
        </div>
    );
}
