'use client';

import { useEffect, useState } from 'react';
import { fetchAPI } from '@/lib/api';

interface DataFileStatus {
    exists: boolean;
    size: number;
    last_modified: string;
}

export default function AdminSystemPage() {
    const [health, setHealth] = useState<any>(null);
    const [dataStatus, setDataStatus] = useState<Record<string, DataFileStatus>>({});
    const [loading, setLoading] = useState(true);
    const [updating, setUpdating] = useState<string | null>(null);

    useEffect(() => { loadData(); }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            const [healthRes, statusRes] = await Promise.allSettled([
                fetchAPI<any>('/api/health'),
                fetchAPI<Record<string, DataFileStatus>>('/api/system/data-status'),
            ]);
            if (healthRes.status === 'fulfilled') setHealth(healthRes.value);
            if (statusRes.status === 'fulfilled') setDataStatus(statusRes.value);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const handleUpdate = async (type: string) => {
        setUpdating(type);
        try {
            const eventSource = new EventSource(`/api/system/update-single?type=${type}`);
            eventSource.addEventListener('status', (e) => {
                const data = JSON.parse(e.data);
                if (data.status === 'completed') {
                    eventSource.close();
                    setUpdating(null);
                    loadData();
                }
            });
            eventSource.onerror = () => {
                eventSource.close();
                setUpdating(null);
            };
        } catch {
            setUpdating(null);
        }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-red-500"></div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <h1 className="text-2xl font-bold text-white">System Monitor</h1>

            {/* Server Health */}
            <div className="apple-glass rounded-xl p-6">
                <h2 className="text-lg font-semibold text-white mb-4">
                    <i className="fas fa-heartbeat text-green-400 mr-2"></i>
                    Server Health
                </h2>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">Status</div>
                        <div className="text-lg font-bold text-green-400">
                            {health?.status === 'ok' ? 'Online' : 'Unknown'}
                        </div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">Backend</div>
                        <div className="text-lg font-bold text-blue-400">Flask</div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">Port</div>
                        <div className="text-lg font-bold text-white">5001</div>
                    </div>
                    <div className="p-3 bg-white/5 rounded-lg">
                        <div className="text-xs text-gray-400">Database</div>
                        <div className="text-lg font-bold text-purple-400">SQLite</div>
                    </div>
                </div>
            </div>

            {/* Data Files Status */}
            <div className="apple-glass rounded-xl p-6">
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">
                        <i className="fas fa-database text-cyan-400 mr-2"></i>
                        Data Files
                    </h2>
                    <button
                        onClick={() => loadData()}
                        className="text-xs text-gray-400 hover:text-white px-3 py-1 rounded bg-white/5 hover:bg-white/10 transition-colors"
                    >
                        <i className="fas fa-sync-alt mr-1"></i> Refresh
                    </button>
                </div>
                <div className="space-y-2">
                    {Object.entries(dataStatus).map(([key, status]) => (
                        <div key={key} className="flex items-center justify-between p-3 bg-white/[0.02] rounded-lg hover:bg-white/[0.04] transition-colors">
                            <div className="flex items-center gap-3">
                                <div className={`w-2 h-2 rounded-full ${status.exists ? 'bg-green-400' : 'bg-red-400'}`}></div>
                                <div>
                                    <div className="text-sm text-white font-medium">{key}</div>
                                    <div className="text-xs text-gray-500">
                                        {status.exists
                                            ? `${(status.size / 1024).toFixed(1)} KB | ${status.last_modified ? new Date(status.last_modified).toLocaleString() : 'Unknown'}`
                                            : 'File not found'}
                                    </div>
                                </div>
                            </div>
                            <button
                                onClick={() => handleUpdate(key)}
                                disabled={updating === key}
                                className="text-xs px-3 py-1 rounded bg-white/5 text-gray-400 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-50"
                            >
                                {updating === key ? (
                                    <><i className="fas fa-spinner fa-spin mr-1"></i> Updating</>
                                ) : (
                                    <><i className="fas fa-redo mr-1"></i> Update</>
                                )}
                            </button>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
