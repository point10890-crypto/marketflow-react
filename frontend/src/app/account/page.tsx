'use client';

import { useEffect, useState } from 'react';
import { useSession, signOut } from 'next-auth/react';
import { subscriptionAPI, SubscriptionRequest } from '@/lib/api';
import Link from 'next/link';

export default function AccountPage() {
    const { data: session } = useSession();
    const user = session?.user as Record<string, unknown> | undefined;
    const apiToken = (user?.apiToken as string) || '';

    const name = (user?.name as string) || 'User';
    const email = (user?.email as string) || '';
    const tier = (user?.tier as string) || 'free';
    const role = (user?.role as string) || 'user';

    const [subRequests, setSubRequests] = useState<SubscriptionRequest[]>([]);
    const [requesting, setRequesting] = useState(false);
    const [actionMsg, setActionMsg] = useState('');

    useEffect(() => {
        if (apiToken) {
            subscriptionAPI.getStatus(apiToken)
                .then((res) => setSubRequests(res.requests || []))
                .catch(() => {});
        }
    }, [apiToken]);

    const hasPending = subRequests.some(r => r.status === 'pending');

    const handleRequestUpgrade = async () => {
        if (!apiToken || hasPending) return;
        setRequesting(true);
        try {
            await subscriptionAPI.requestUpgrade('pro', apiToken);
            setActionMsg('Upgrade request submitted! Admin will review shortly.');
            // Refresh
            const res = await subscriptionAPI.getStatus(apiToken);
            setSubRequests(res.requests || []);
        } catch (err: any) {
            setActionMsg(`Error: ${err.message}`);
        } finally {
            setRequesting(false);
        }
    };

    return (
        <div className="max-w-2xl mx-auto space-y-6">
            <h1 className="text-2xl font-bold text-white">My Account</h1>

            {/* Action message */}
            {actionMsg && (
                <div className="p-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400 text-sm">
                    {actionMsg}
                </div>
            )}

            {/* Profile Card */}
            <div className="apple-glass rounded-xl p-6">
                <div className="flex items-center gap-4 mb-6">
                    <div className={`w-16 h-16 rounded-full flex items-center justify-center text-2xl font-bold text-white ${tier === 'pro' || tier === 'premium' ? 'bg-gradient-to-tr from-indigo-500 to-purple-500' : 'bg-gradient-to-tr from-gray-600 to-gray-500'}`}>
                        {name.charAt(0).toUpperCase()}
                    </div>
                    <div>
                        <div className="text-xl font-bold text-white">{name}</div>
                        <div className="text-sm text-gray-400">{email}</div>
                        <div className="flex items-center gap-2 mt-1">
                            <span className={`text-xs px-2 py-0.5 rounded font-semibold ${tier === 'pro' ? 'bg-purple-500/20 text-purple-400' : tier === 'premium' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-gray-500/20 text-gray-400'}`}>
                                {tier === 'pro' ? 'Pro Plan' : tier === 'premium' ? 'Premium' : 'Free Plan'}
                            </span>
                            {role === 'admin' && (
                                <span className="text-xs px-2 py-0.5 rounded font-semibold bg-red-500/20 text-red-400">
                                    Admin
                                </span>
                            )}
                        </div>
                    </div>
                </div>
                <div className="flex gap-3">
                    <button
                        onClick={() => signOut({ callbackUrl: '/login' })}
                        className="text-sm px-4 py-2 rounded-lg bg-white/5 text-gray-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                    >
                        <i className="fas fa-sign-out-alt mr-2"></i>Sign Out
                    </button>
                </div>
            </div>

            {/* Subscription */}
            <div className="apple-glass rounded-xl p-6">
                <h2 className="text-lg font-semibold text-white mb-4">
                    <i className="fas fa-crown text-yellow-400 mr-2"></i>
                    Subscription
                </h2>
                {tier === 'pro' || tier === 'premium' ? (
                    <div>
                        <div className="flex items-center gap-2 mb-3">
                            <span className="text-white font-medium">MarketFlow {tier === 'premium' ? 'Premium' : 'Pro'} Active</span>
                            <span className="text-xs px-2 py-0.5 rounded bg-green-500/20 text-green-400">Active</span>
                        </div>
                        <p className="text-sm text-gray-400 mb-4">
                            Full access to AI Prediction, Risk Analysis, Lead-Lag, Backtest, and Signal Analysis.
                        </p>
                        <Link
                            href="/pricing"
                            className="text-sm text-gray-400 hover:text-white transition-colors"
                        >
                            View Plans &rarr;
                        </Link>
                    </div>
                ) : (
                    <div>
                        <p className="text-sm text-gray-400 mb-4">
                            Upgrade to Pro for access to advanced analytics: AI Prediction, Risk Assessment, Lead-Lag Analysis, and more.
                        </p>
                        <div className="flex gap-3">
                            <Link
                                href="/account/upgrade"
                                className="inline-flex items-center gap-2 px-4 py-2 bg-[#2997ff] text-white rounded-lg font-medium text-sm hover:bg-[#2997ff]/80 transition-colors"
                            >
                                <i className="fas fa-credit-card"></i>
                                Pay & Upgrade
                            </Link>
                            {!hasPending && (
                                <button
                                    onClick={handleRequestUpgrade}
                                    disabled={requesting}
                                    className="inline-flex items-center gap-2 px-4 py-2 bg-purple-500/20 text-purple-400 rounded-lg font-medium text-sm hover:bg-purple-500/30 transition-colors disabled:opacity-50"
                                >
                                    <i className="fas fa-paper-plane"></i>
                                    {requesting ? 'Requesting...' : 'Request Upgrade'}
                                </button>
                            )}
                            {hasPending && (
                                <span className="inline-flex items-center gap-2 px-4 py-2 bg-yellow-500/10 text-yellow-400 rounded-lg text-sm">
                                    <i className="fas fa-clock"></i>
                                    Request Pending
                                </span>
                            )}
                        </div>
                    </div>
                )}
            </div>

            {/* Subscription History */}
            {subRequests.length > 0 && (
                <div className="apple-glass rounded-xl p-6">
                    <h2 className="text-lg font-semibold text-white mb-4">
                        <i className="fas fa-history text-gray-400 mr-2"></i>
                        Subscription History
                    </h2>
                    <div className="space-y-3">
                        {subRequests.map((req) => (
                            <div key={req.id} className="flex items-center justify-between p-3 bg-white/[0.02] rounded-lg">
                                <div>
                                    <div className="text-sm text-white">
                                        {req.from_tier} <span className="text-gray-500">&rarr;</span> {req.to_tier}
                                        <span className="text-xs text-gray-500 ml-2">({req.request_type})</span>
                                    </div>
                                    <div className="text-xs text-gray-500">{new Date(req.created_at).toLocaleString()}</div>
                                </div>
                                <span className={`text-xs px-2 py-1 rounded font-medium ${
                                    req.status === 'approved' ? 'bg-green-500/20 text-green-400' :
                                    req.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' :
                                    'bg-red-500/20 text-red-400'
                                }`}>
                                    {req.status}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Features by Tier */}
            <div className="apple-glass rounded-xl p-6">
                <h2 className="text-lg font-semibold text-white mb-4">
                    <i className="fas fa-list-check text-blue-400 mr-2"></i>
                    Feature Access
                </h2>
                <div className="space-y-3">
                    {[
                        { name: 'Market Overview', free: true, pro: true },
                        { name: 'VCP Signals', free: true, pro: true },
                        { name: 'Market Gate', free: true, pro: true },
                        { name: 'Crypto Briefing', free: true, pro: true },
                        { name: 'AI Prediction', free: false, pro: true },
                        { name: 'Risk Analysis', free: false, pro: true },
                        { name: 'Lead-Lag Analysis', free: false, pro: true },
                        { name: 'Backtest Results', free: false, pro: true },
                        { name: 'Signal Analysis', free: false, pro: true },
                        { name: 'Telegram Alerts', free: false, pro: true },
                    ].map((feature) => {
                        const hasAccess = tier === 'pro' || tier === 'premium' ? feature.pro : feature.free;
                        return (
                            <div key={feature.name} className="flex items-center justify-between">
                                <span className={`text-sm ${hasAccess ? 'text-white' : 'text-gray-600'}`}>
                                    {feature.name}
                                </span>
                                {hasAccess ? (
                                    <i className="fas fa-check text-green-400 text-sm"></i>
                                ) : (
                                    <i className="fas fa-lock text-gray-600 text-sm"></i>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
}
