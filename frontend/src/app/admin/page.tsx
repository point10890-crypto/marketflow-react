'use client';

import { useEffect, useState } from 'react';
import { useSession } from 'next-auth/react';
import { adminAPI, AdminDashboard } from '@/lib/api';
import Link from 'next/link';

export default function AdminDashboardPage() {
    const { data: session } = useSession();
    const [data, setData] = useState<AdminDashboard | null>(null);
    const [loading, setLoading] = useState(true);

    const apiToken = (session?.user as Record<string, unknown>)?.apiToken as string | undefined;

    useEffect(() => {
        adminAPI.getDashboard(apiToken)
            .then(setData)
            .catch(console.error)
            .finally(() => setLoading(false));
    }, [apiToken]);

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-red-500"></div>
            </div>
        );
    }

    const stats = [
        { label: 'Total Users', value: data?.total_users || 0, icon: 'fa-users', color: 'text-blue-400', bg: 'bg-blue-500/10' },
        { label: 'Pro Users', value: data?.pro_users || 0, icon: 'fa-crown', color: 'text-yellow-400', bg: 'bg-yellow-500/10' },
        { label: 'Free Users', value: data?.free_users || 0, icon: 'fa-user', color: 'text-gray-400', bg: 'bg-gray-500/10' },
        { label: 'Admins', value: data?.admin_users || 0, icon: 'fa-shield-alt', color: 'text-red-400', bg: 'bg-red-500/10' },
        { label: 'Pending Subs', value: data?.pending_subscriptions || 0, icon: 'fa-clock', color: 'text-orange-400', bg: 'bg-orange-500/10' },
    ];

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold text-white">Admin Dashboard</h1>
                <span className="text-xs text-red-400 bg-red-500/10 px-3 py-1 rounded-full font-semibold">
                    <i className="fas fa-shield-alt mr-1"></i> Admin Only
                </span>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                {stats.map((stat) => (
                    <div key={stat.label} className="apple-glass rounded-xl p-4">
                        <div className={`w-10 h-10 ${stat.bg} rounded-lg flex items-center justify-center mb-3`}>
                            <i className={`fas ${stat.icon} ${stat.color}`}></i>
                        </div>
                        <div className="text-2xl font-bold text-white">{stat.value}</div>
                        <div className="text-xs text-gray-400 mt-1">{stat.label}</div>
                    </div>
                ))}
            </div>

            {/* Quick Links */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Link href="/admin/users" className="apple-glass rounded-xl p-6 hover:bg-white/5 transition-colors group">
                    <div className="flex items-center gap-3">
                        <i className="fas fa-users-cog text-red-400 text-xl"></i>
                        <div>
                            <div className="text-white font-semibold group-hover:text-red-400 transition-colors">User Management</div>
                            <div className="text-xs text-gray-500">Manage roles, tiers, and permissions</div>
                        </div>
                        <i className="fas fa-chevron-right text-gray-600 ml-auto"></i>
                    </div>
                </Link>
                <Link href="/admin/subscriptions" className="apple-glass rounded-xl p-6 hover:bg-white/5 transition-colors group">
                    <div className="flex items-center gap-3">
                        <i className="fas fa-credit-card text-red-400 text-xl"></i>
                        <div>
                            <div className="text-white font-semibold group-hover:text-red-400 transition-colors">Subscriptions</div>
                            <div className="text-xs text-gray-500">
                                {(data?.pending_subscriptions || 0) > 0
                                    ? `${data?.pending_subscriptions} pending approval`
                                    : 'No pending requests'}
                            </div>
                        </div>
                        <i className="fas fa-chevron-right text-gray-600 ml-auto"></i>
                    </div>
                </Link>
                <Link href="/admin/system" className="apple-glass rounded-xl p-6 hover:bg-white/5 transition-colors group">
                    <div className="flex items-center gap-3">
                        <i className="fas fa-server text-red-400 text-xl"></i>
                        <div>
                            <div className="text-white font-semibold group-hover:text-red-400 transition-colors">System Monitor</div>
                            <div className="text-xs text-gray-500">Server health, data status, scheduler</div>
                        </div>
                        <i className="fas fa-chevron-right text-gray-600 ml-auto"></i>
                    </div>
                </Link>
            </div>
        </div>
    );
}
