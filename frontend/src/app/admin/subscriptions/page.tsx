'use client';

import { useEffect, useState } from 'react';
import { useSession } from 'next-auth/react';
import { adminAPI, SubscriptionRequest } from '@/lib/api';

export default function AdminSubscriptionsPage() {
    const { data: session } = useSession();
    const [requests, setRequests] = useState<SubscriptionRequest[]>([]);
    const [loading, setLoading] = useState(true);
    const [actionMsg, setActionMsg] = useState('');

    const apiToken = (session?.user as Record<string, unknown>)?.apiToken as string | undefined;

    useEffect(() => { loadRequests(); }, [apiToken]);

    const loadRequests = async () => {
        setLoading(true);
        try {
            const res = await adminAPI.getSubscriptions(apiToken);
            setRequests(res.requests || []);
        } catch (err) {
            console.error('Failed to load subscriptions:', err);
        } finally {
            setLoading(false);
        }
    };

    const showAction = (msg: string) => {
        setActionMsg(msg);
        setTimeout(() => setActionMsg(''), 3000);
    };

    const handleApprove = async (id: number) => {
        try {
            await adminAPI.approveSubscription(id, apiToken);
            setRequests(prev => prev.map(r => r.id === id ? { ...r, status: 'approved' } : r));
            showAction('Subscription approved successfully');
        } catch (err: any) {
            showAction(`Error: ${err.message}`);
        }
    };

    const handleReject = async (id: number) => {
        const note = prompt('Rejection reason (optional):');
        try {
            await adminAPI.rejectSubscription(id, note || undefined, apiToken);
            setRequests(prev => prev.map(r => r.id === id ? { ...r, status: 'rejected', admin_note: note } : r));
            showAction('Subscription request rejected');
        } catch (err: any) {
            showAction(`Error: ${err.message}`);
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-red-500"></div>
            </div>
        );
    }

    const pending = requests.filter(r => r.status === 'pending');
    const processed = requests.filter(r => r.status !== 'pending');

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold text-white">Subscription Management</h1>
                <button
                    onClick={loadRequests}
                    className="text-xs text-gray-400 hover:text-white px-3 py-1.5 rounded bg-white/5 hover:bg-white/10 transition-colors"
                >
                    <i className="fas fa-sync-alt mr-1"></i> Refresh
                </button>
            </div>

            {/* Action message */}
            {actionMsg && (
                <div className="p-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400 text-sm animate-pulse">
                    {actionMsg}
                </div>
            )}

            {/* Pending Requests */}
            <div>
                <h2 className="text-lg font-semibold text-yellow-400 mb-3">
                    <i className="fas fa-clock mr-2"></i>
                    Pending Requests ({pending.length})
                </h2>
                {pending.length === 0 ? (
                    <div className="apple-glass rounded-xl p-8 text-center text-gray-500">
                        <i className="fas fa-check-circle text-3xl mb-3 text-green-500/50"></i>
                        <div>No pending subscription requests</div>
                    </div>
                ) : (
                    <div className="space-y-3">
                        {pending.map((req) => (
                            <div key={req.id} className="apple-glass rounded-xl p-4 border border-yellow-500/20">
                                <div className="flex items-center justify-between flex-wrap gap-3">
                                    <div className="flex items-center gap-3">
                                        <div className="w-10 h-10 bg-yellow-500/10 rounded-full flex items-center justify-center">
                                            <i className={`fas ${req.request_type === 'upgrade' ? 'fa-arrow-up text-yellow-400' : 'fa-arrow-down text-blue-400'}`}></i>
                                        </div>
                                        <div>
                                            <div className="text-white font-medium">{req.user_name || `User #${req.user_id}`}</div>
                                            <div className="text-xs text-gray-400">{req.user_email || ''}</div>
                                            <div className="text-xs text-gray-500 mt-1">
                                                <span className={`px-1.5 py-0.5 rounded ${req.from_tier === 'free' ? 'bg-gray-500/20 text-gray-400' : 'bg-purple-500/20 text-purple-400'}`}>
                                                    {req.from_tier}
                                                </span>
                                                <span className="mx-2">&rarr;</span>
                                                <span className={`px-1.5 py-0.5 rounded ${req.to_tier === 'pro' ? 'bg-purple-500/20 text-purple-400' : 'bg-gray-500/20 text-gray-400'}`}>
                                                    {req.to_tier}
                                                </span>
                                                <span className="ml-2 text-gray-600">{new Date(req.created_at).toLocaleString()}</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="flex gap-2">
                                        <button
                                            onClick={() => handleApprove(req.id)}
                                            className="px-4 py-2 bg-green-500/20 text-green-400 rounded-lg text-sm font-medium hover:bg-green-500/30 transition-colors"
                                        >
                                            <i className="fas fa-check mr-1"></i> Approve
                                        </button>
                                        <button
                                            onClick={() => handleReject(req.id)}
                                            className="px-4 py-2 bg-red-500/20 text-red-400 rounded-lg text-sm font-medium hover:bg-red-500/30 transition-colors"
                                        >
                                            <i className="fas fa-times mr-1"></i> Reject
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Processed Requests */}
            {processed.length > 0 && (
                <div>
                    <h2 className="text-lg font-semibold text-gray-400 mb-3">
                        <i className="fas fa-history mr-2"></i>
                        History ({processed.length})
                    </h2>
                    <div className="apple-glass rounded-xl overflow-hidden">
                        <table className="w-full">
                            <thead>
                                <tr className="border-b border-white/5">
                                    <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">User</th>
                                    <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">Change</th>
                                    <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">Status</th>
                                    <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">Date</th>
                                    <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">Note</th>
                                </tr>
                            </thead>
                            <tbody>
                                {processed.map((req) => (
                                    <tr key={req.id} className="border-b border-white/5">
                                        <td className="px-4 py-3 text-sm text-white">{req.user_name || `#${req.user_id}`}</td>
                                        <td className="px-4 py-3 text-xs text-gray-400">{req.from_tier} &rarr; {req.to_tier}</td>
                                        <td className="px-4 py-3">
                                            <span className={`text-xs px-2 py-1 rounded ${req.status === 'approved' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                                                {req.status}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-xs text-gray-500">
                                            {req.processed_at ? new Date(req.processed_at).toLocaleDateString() : '-'}
                                        </td>
                                        <td className="px-4 py-3 text-xs text-gray-500">{req.admin_note || '-'}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}
