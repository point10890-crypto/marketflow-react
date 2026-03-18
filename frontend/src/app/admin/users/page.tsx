'use client';

import { useEffect, useState } from 'react';
import { useSession } from 'next-auth/react';
import { adminAPI, AdminUser } from '@/lib/api';

export default function AdminUsersPage() {
    const { data: session } = useSession();
    const [users, setUsers] = useState<AdminUser[]>([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [filterRole, setFilterRole] = useState<string>('all');
    const [filterTier, setFilterTier] = useState<string>('all');
    const [filterStatus, setFilterStatus] = useState<string>('all');
    const [actionMsg, setActionMsg] = useState('');

    const apiToken = (session?.user as Record<string, unknown>)?.apiToken as string | undefined;

    useEffect(() => { loadUsers(); }, [apiToken]);

    const loadUsers = async () => {
        setLoading(true);
        try {
            const res = await adminAPI.getUsers(apiToken);
            setUsers(res.users || []);
        } catch (err) {
            console.error('Failed to load users:', err);
        } finally {
            setLoading(false);
        }
    };

    const showAction = (msg: string) => {
        setActionMsg(msg);
        setTimeout(() => setActionMsg(''), 3000);
    };

    const handleRoleChange = async (userId: number, newRole: string) => {
        try {
            await adminAPI.setUserRole(userId, newRole, apiToken);
            setUsers(prev => prev.map(u => u.id === userId ? { ...u, role: newRole } : u));
            showAction(`Role updated to ${newRole}`);
        } catch (err: any) {
            showAction(`Error: ${err.message}`);
        }
    };

    const handleTierChange = async (userId: number, newTier: string) => {
        try {
            await adminAPI.setUserTier(userId, newTier, apiToken);
            setUsers(prev => prev.map(u => u.id === userId ? { ...u, tier: newTier } : u));
            showAction(`Tier updated to ${newTier}`);
        } catch (err: any) {
            showAction(`Error: ${err.message}`);
        }
    };

    const handleStatusChange = async (userId: number, newStatus: string) => {
        try {
            await adminAPI.setUserStatus(userId, newStatus, apiToken);
            setUsers(prev => prev.map(u => u.id === userId ? { ...u, subscription_status: newStatus } : u));
            showAction(`Status updated to ${newStatus}`);
        } catch (err: any) {
            showAction(`Error: ${err.message}`);
        }
    };

    const filtered = users.filter(u => {
        if (search && !u.email.toLowerCase().includes(search.toLowerCase()) && !u.name.toLowerCase().includes(search.toLowerCase())) return false;
        if (filterRole !== 'all' && u.role !== filterRole) return false;
        if (filterTier !== 'all' && u.tier !== filterTier) return false;
        if (filterStatus !== 'all' && u.subscription_status !== filterStatus) return false;
        return true;
    });

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-red-500"></div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold text-white">User Management</h1>
                <span className="text-sm text-gray-400">{users.length} total users</span>
            </div>

            {/* Action message */}
            {actionMsg && (
                <div className="p-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400 text-sm animate-pulse">
                    {actionMsg}
                </div>
            )}

            {/* Filters */}
            <div className="flex flex-wrap gap-3">
                <div className="relative flex-1 min-w-[200px]">
                    <i className="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm"></i>
                    <input
                        type="text"
                        placeholder="Search by name or email..."
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="w-full pl-10 pr-4 py-2.5 bg-white/5 border border-white/10 rounded-lg text-white text-sm focus:outline-none focus:border-red-500/50"
                    />
                </div>
                <select
                    value={filterRole}
                    onChange={(e) => setFilterRole(e.target.value)}
                    className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-lg text-white text-sm focus:outline-none"
                >
                    <option value="all">All Roles</option>
                    <option value="admin">Admin</option>
                    <option value="user">User</option>
                </select>
                <select
                    value={filterTier}
                    onChange={(e) => setFilterTier(e.target.value)}
                    className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-lg text-white text-sm focus:outline-none"
                >
                    <option value="all">All Tiers</option>
                    <option value="pro">Pro</option>
                    <option value="free">Free</option>
                    <option value="premium">Premium</option>
                </select>
                <select
                    value={filterStatus}
                    onChange={(e) => setFilterStatus(e.target.value)}
                    className="px-3 py-2.5 bg-white/5 border border-white/10 rounded-lg text-white text-sm focus:outline-none"
                >
                    <option value="all">All Status</option>
                    <option value="pending">Pending</option>
                    <option value="approved">Approved</option>
                    <option value="rejected">Rejected</option>
                    <option value="suspended">Suspended</option>
                </select>
            </div>

            {/* Users Table */}
            <div className="apple-glass rounded-xl overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead>
                            <tr className="border-b border-white/5">
                                <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">User</th>
                                <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">Role</th>
                                <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">Tier</th>
                                <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">Status</th>
                                <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">Joined</th>
                                <th className="text-left text-xs font-semibold text-gray-400 uppercase px-4 py-3">Last Login</th>
                            </tr>
                        </thead>
                        <tbody>
                            {filtered.map((user) => (
                                <tr key={user.id} className="border-b border-white/5 hover:bg-white/[0.02]">
                                    <td className="px-4 py-3">
                                        <div className="flex items-center gap-3">
                                            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white ${user.role === 'admin' ? 'bg-red-500' : user.tier === 'pro' ? 'bg-purple-500' : 'bg-gray-600'}`}>
                                                {user.name.charAt(0).toUpperCase()}
                                            </div>
                                            <div>
                                                <div className="text-sm text-white font-medium">{user.name}</div>
                                                <div className="text-xs text-gray-500">{user.email}</div>
                                            </div>
                                        </div>
                                    </td>
                                    <td className="px-4 py-3">
                                        <select
                                            value={user.role}
                                            onChange={(e) => handleRoleChange(user.id, e.target.value)}
                                            className={`text-xs px-2 py-1 rounded border-0 focus:outline-none cursor-pointer ${user.role === 'admin' ? 'bg-red-500/20 text-red-400' : 'bg-gray-500/20 text-gray-400'}`}
                                        >
                                            <option value="user">User</option>
                                            <option value="admin">Admin</option>
                                        </select>
                                    </td>
                                    <td className="px-4 py-3">
                                        <select
                                            value={user.tier}
                                            onChange={(e) => handleTierChange(user.id, e.target.value)}
                                            className={`text-xs px-2 py-1 rounded border-0 focus:outline-none cursor-pointer ${user.tier === 'pro' ? 'bg-purple-500/20 text-purple-400' : user.tier === 'premium' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-gray-500/20 text-gray-400'}`}
                                        >
                                            <option value="free">Free</option>
                                            <option value="pro">Pro</option>
                                            <option value="premium">Premium</option>
                                        </select>
                                    </td>
                                    <td className="px-4 py-3">
                                        <select
                                            value={user.subscription_status}
                                            onChange={(e) => handleStatusChange(user.id, e.target.value)}
                                            className={`text-xs px-2 py-1 rounded border-0 focus:outline-none cursor-pointer ${
                                                user.subscription_status === 'approved' ? 'bg-green-500/20 text-green-400' :
                                                user.subscription_status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' :
                                                user.subscription_status === 'suspended' ? 'bg-red-500/20 text-red-400' :
                                                'bg-gray-500/20 text-gray-500'
                                            }`}
                                        >
                                            <option value="pending">Pending</option>
                                            <option value="approved">Approved</option>
                                            <option value="rejected">Rejected</option>
                                            <option value="suspended">Suspended</option>
                                        </select>
                                    </td>
                                    <td className="px-4 py-3 text-xs text-gray-500">
                                        {user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}
                                    </td>
                                    <td className="px-4 py-3 text-xs text-gray-500">
                                        {(user as any).last_login_at ? new Date((user as any).last_login_at).toLocaleString() : 'Never'}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                {filtered.length === 0 && (
                    <div className="text-center py-8 text-gray-500 text-sm">No users found</div>
                )}
            </div>
        </div>
    );
}
