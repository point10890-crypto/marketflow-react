'use client';

import { useEffect, useState, useCallback } from 'react';
import { API_BASE } from '@/lib/api';
import { useIsMobile } from '@/hooks/useIsMobile';
import { usePullToRefreshRegister } from '@/components/layout/PullToRefreshProvider';

interface DataStatus {
    name: string;
    path: string;
    exists: boolean;
    lastModified: string;
    size: string;
    rowCount?: number;
    link?: string;
    menu?: string;
    updateType?: string; // Added for individual updates
}



// Map data names to update types
const UPDATE_TYPE_MAP: Record<string, string> = {
    'Daily Prices': 'daily_prices',
    'Institutional Trend': 'institutional',
    'AI Analysis': 'ai_analysis',
    'VCP Signals': 'vcp_signals',
    'AI Jongga V2': 'jongga_v2',
    // Crypto Analytics
    'Crypto Market Gate': 'crypto_gate',
    'Crypto VCP Signals': 'crypto_scan',
    'Crypto Briefing': 'crypto_briefing',
    'BTC Prediction': 'crypto_prediction',
    'Crypto Risk': 'crypto_risk',
    'Lead-Lag Analysis': 'crypto_leadlag',
};

export default function DataStatusPage() {
    const isMobile = useIsMobile();
    const [dataFiles, setDataFiles] = useState<DataStatus[]>([]);

    const [loading, setLoading] = useState(true);
    const [updating, setUpdating] = useState(false);
    const [updatingItem, setUpdatingItem] = useState<string | null>(null);
    const [logs, setLogs] = useState<string[]>([]);

    const loadStatus = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetch(`${API_BASE}/api/system/data-status`);
            if (res.ok) {
                const data = await res.json();
                // Add updateType to each file
                const filesWithType = (data.files || []).map((f: DataStatus) => ({
                    ...f,
                    updateType: UPDATE_TYPE_MAP[f.name] || null
                }));
                setDataFiles(filesWithType);

            }
        } catch (error) {
            console.error('Failed to load data status:', error);
        } finally {
            setLoading(false);
        }
    }, []);

    const triggerUpdate = () => {
        if (updating || updatingItem) return;

        setUpdating(true);
        setLogs(['Initializing update process...']);

        const eventSource = new EventSource(`${API_BASE}/api/system/update-data-stream`);

        eventSource.onmessage = (event) => {
            if (event.data === 'close') {
                eventSource.close();
                setUpdating(false);
                setLogs(prev => [...prev, '--- Update Complete ---']);
                loadStatus();
                return;
            }
            setLogs(prev => [...prev, event.data]);
        };

        // Handle custom 'end' event from SSE
        eventSource.addEventListener('end', () => {
            eventSource.close();
            setUpdating(false);
            setLogs(prev => [...prev, '--- Update Complete ---']);
            loadStatus();
        });

        eventSource.onerror = () => {
            if (eventSource.readyState !== EventSource.CLOSED) {
                console.error('EventSource connection error');
                setLogs(prev => [...prev, '[ERROR] Connection lost.']);
            }
            eventSource.close();
            setUpdating(false);
        };
    };

    const triggerSingleUpdate = (updateType: string, displayName: string) => {
        if (updating || updatingItem) return;

        setUpdatingItem(updateType);
        setLogs([`Starting ${displayName} update...`]);

        const eventSource = new EventSource(`${API_BASE}/api/system/update-single?type=${updateType}`);

        eventSource.onmessage = (event) => {
            if (event.data === 'close') {
                eventSource.close();
                setUpdatingItem(null);
                setLogs(prev => [...prev, '--- Update Complete ---']);
                loadStatus();
                return;
            }
            setLogs(prev => [...prev, event.data]);
        };

        // Handle custom 'end' event from SSE
        eventSource.addEventListener('end', () => {
            eventSource.close();
            setUpdatingItem(null);
            setLogs(prev => [...prev, '--- Update Complete ---']);
            loadStatus();
        });

        eventSource.onerror = () => {
            // Only show error if not already closed
            if (eventSource.readyState !== EventSource.CLOSED) {
                console.error('EventSource connection error');
                setLogs(prev => [...prev, '[ERROR] Connection lost.']);
            }
            eventSource.close();
            setUpdatingItem(null);
        };
    };

    useEffect(() => {
        const el = document.getElementById('log-end');
        if (el) {
            el.scrollIntoView({ behavior: 'smooth' });
        }
    }, [logs]);

    usePullToRefreshRegister(loadStatus);

    useEffect(() => {
        loadStatus();
        const interval = setInterval(loadStatus, 30000);
        return () => clearInterval(interval);
    }, [loadStatus]);

    const formatTime = (isoString: string) => {
        if (!isoString) return '-';
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
        const diffMins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

        if (diffHours > 24) {
            return `${Math.floor(diffHours / 24)}일 전`;
        } else if (diffHours > 0) {
            return `${diffHours}시간 ${diffMins}분 전`;
        } else {
            return `${diffMins}분 전`;
        }
    };

    const getStatusColor = (exists: boolean, lastModified: string) => {
        if (!exists) return 'text-red-400 bg-red-500/10 border-red-500/20';

        const date = new Date(lastModified);
        const now = new Date();
        const diffHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);

        if (diffHours < 1) return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20';
        if (diffHours < 24) return 'text-amber-400 bg-amber-500/10 border-amber-500/20';
        return 'text-red-400 bg-red-500/10 border-red-500/20';
    };

    const isUpdatingThis = (updateType: string | undefined) => {
        return updatingItem === updateType;
    };

    return (
        <div className="space-y-4 md:space-y-8">
            <div className="mb-4 md:mb-8">
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-cyan-500/20 bg-cyan-500/5 text-xs text-cyan-400 font-medium mb-4">
                    <span className="w-1.5 h-1.5 rounded-full bg-cyan-500"></span>
                    System Status
                </div>
                <div className="flex flex-col md:flex-row justify-between items-end gap-3 md:gap-6">
                    <div>
                        <h2 className="text-2xl md:text-5xl font-bold tracking-tighter text-white leading-tight mb-1 md:mb-2">
                            Data <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-blue-400">Status</span>
                        </h2>
                        <p className="text-gray-400 text-sm md:text-lg">데이터 파일 상태 및 업데이트 현황</p>
                    </div>
                    <button
                        onClick={triggerUpdate}
                        disabled={updating || !!updatingItem}
                        className="px-6 py-3 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-bold rounded-xl transition-all flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-cyan-500/20"
                    >
                        <i className={`fas fa-sync-alt ${updating ? 'animate-spin' : ''}`}></i>
                        {updating ? 'Updating...' : 'Update All Data'}
                    </button>
                </div>
            </div>

            {(updating || updatingItem || logs.length > 0) && (
                <div className="rounded-2xl bg-[#09090b] border border-white/10 overflow-hidden font-mono text-xs shadow-inner">
                    <div className="bg-[#27272a]/50 px-4 py-2 flex items-center justify-between border-b border-white/5">
                        <span className="text-gray-400 flex items-center gap-2">
                            <i className="fas fa-terminal"></i> Build Output
                            {updatingItem && <span className="text-cyan-400 ml-2">({updatingItem})</span>}
                        </span>
                        {(updating || updatingItem) ? (
                            <span className="text-emerald-400 flex items-center gap-1.5 text-[10px] uppercase font-bold animate-pulse">
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Live
                            </span>
                        ) : (
                            <span className="text-gray-500 text-[10px]">Finished</span>
                        )}
                    </div>
                    <div className="p-4 h-64 overflow-y-auto space-y-1 text-gray-300 font-mono bg-black/50">
                        {logs.map((log, i) => (
                            <div key={i} className="whitespace-pre-wrap break-all border-l-2 border-transparent hover:border-white/10 pl-2">
                                <span className="text-gray-600 mr-2 select-none">$</span>
                                {log}
                            </div>
                        ))}
                        <div id="log-end" />
                    </div>
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 md:gap-4">
                {loading && dataFiles.length === 0 ? (
                    Array.from({ length: 6 }).map((_, i) => (
                        <div key={i} className="p-4 md:p-5 rounded-2xl bg-[#1c1c1e] border border-white/10 animate-pulse">
                            <div className="h-4 bg-white/10 rounded w-1/2 mb-3"></div>
                            <div className="h-3 bg-white/10 rounded w-3/4 mb-2"></div>
                            <div className="h-3 bg-white/10 rounded w-1/3"></div>
                        </div>
                    ))
                ) : dataFiles.length === 0 ? (
                    <div className="col-span-full text-center py-20 text-gray-500">
                        <i className="fas fa-database text-4xl mb-4 opacity-30"></i>
                        <p>No data files found</p>
                    </div>
                ) : (
                    dataFiles.map((file) => isMobile ? (
                        /* Mobile: Compact card view */
                        <div key={file.path} className="p-3 rounded-xl bg-[#1c1c1e] border border-white/10 flex flex-col gap-2">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2 min-w-0">
                                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${file.exists ? 'bg-cyan-500/10 text-cyan-400' : 'bg-red-500/10 text-red-400'}`}>
                                        <i className={`fas ${file.exists ? 'fa-file-alt' : 'fa-file-excel'} text-xs`}></i>
                                    </div>
                                    <div className="min-w-0">
                                        <h3 className="text-sm text-white font-bold truncate">{file.name}</h3>
                                        {file.menu && (
                                            <div className="text-[10px] text-gray-600 truncate">{file.menu}</div>
                                        )}
                                    </div>
                                </div>
                                <span className={`px-2 py-0.5 rounded text-[10px] font-bold border shrink-0 ${getStatusColor(file.exists, file.lastModified)}`}>
                                    {file.exists ? 'OK' : 'MISSING'}
                                </span>
                            </div>
                            {file.exists && (
                                <div className="flex items-center gap-3 text-[11px] text-gray-500">
                                    <span className="text-white font-medium">{formatTime(file.lastModified)}</span>
                                    <span className="text-gray-700">|</span>
                                    <span className="font-mono">{file.size}</span>
                                    {file.rowCount != null && (
                                        <>
                                            <span className="text-gray-700">|</span>
                                            <span className="font-mono">{file.rowCount.toLocaleString()} rows</span>
                                        </>
                                    )}
                                </div>
                            )}
                            {(file.updateType || file.link) && (
                                <div className="flex gap-2">
                                    {file.updateType && (
                                        <button
                                            onClick={() => triggerSingleUpdate(file.updateType!, file.name)}
                                            disabled={updating || !!updatingItem}
                                            className={`flex-1 py-1.5 flex items-center justify-center gap-1.5 rounded-lg text-[11px] font-bold transition-all border ${isUpdatingThis(file.updateType)
                                                ? 'bg-amber-500/20 text-amber-400 border-amber-500/30'
                                                : 'bg-white/5 text-gray-400 border-white/5'
                                                } disabled:opacity-50 disabled:cursor-not-allowed`}
                                        >
                                            <i className={`fas fa-sync-alt ${isUpdatingThis(file.updateType) ? 'animate-spin' : ''}`}></i>
                                            {isUpdatingThis(file.updateType) ? 'Updating...' : 'Update'}
                                        </button>
                                    )}
                                    {file.link && (
                                        <a href={file.link}
                                            className="flex-1 py-1.5 flex items-center justify-center gap-1.5 rounded-lg bg-white/5 text-gray-400 text-[11px] font-bold transition-all border border-white/5">
                                            View <i className="fas fa-arrow-right text-[9px]"></i>
                                        </a>
                                    )}
                                </div>
                            )}
                        </div>
                    ) : (
                        /* Desktop: Full card view */
                        <div
                            key={file.path}
                            className="p-5 rounded-2xl bg-[#1c1c1e] border border-white/10 hover:border-white/20 transition-all group flex flex-col"
                        >
                            <div className="flex items-start justify-between mb-3">
                                <div className="flex items-center gap-3">
                                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${file.exists ? 'bg-cyan-500/10 text-cyan-400' : 'bg-red-500/10 text-red-400'}`}>
                                        <i className={`fas ${file.exists ? 'fa-file-alt' : 'fa-file-excel'}`}></i>
                                    </div>
                                    <div>
                                        <h3 className="text-white font-bold flex items-center gap-2">
                                            {file.name}
                                        </h3>
                                        {file.menu && (
                                            <div className="text-[10px] text-gray-500 mt-0.5 flex items-center gap-1">
                                                <i className="fas fa-link text-gray-600"></i> {file.menu}
                                            </div>
                                        )}
                                        <p className="text-[10px] text-gray-700 font-mono truncate max-w-[150px] mt-0.5">{file.path}</p>
                                    </div>
                                </div>
                                <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${getStatusColor(file.exists, file.lastModified)}`}>
                                    {file.exists ? 'OK' : 'MISSING'}
                                </span>
                            </div>

                            {file.exists && (
                                <div className="space-y-2 text-sm flex-1">
                                    <div className="flex justify-between text-gray-400">
                                        <span>Last Updated</span>
                                        <span className="text-white font-medium">{formatTime(file.lastModified)}</span>
                                    </div>
                                    <div className="flex justify-between text-gray-400">
                                        <span>File Size</span>
                                        <span className="text-white font-mono text-xs">{file.size}</span>
                                    </div>
                                    {file.rowCount != null && (
                                        <div className="flex justify-between text-gray-400">
                                            <span>Records</span>
                                            <span className="text-white font-mono text-xs">{file.rowCount.toLocaleString()}</span>
                                        </div>
                                    )}
                                </div>
                            )}

                            <div className="mt-4 flex gap-2">
                                {file.updateType && (
                                    <button
                                        onClick={() => triggerSingleUpdate(file.updateType!, file.name)}
                                        disabled={updating || !!updatingItem}
                                        className={`flex-1 py-2 flex items-center justify-center gap-2 rounded-lg text-xs font-bold transition-all border ${isUpdatingThis(file.updateType)
                                            ? 'bg-amber-500/20 text-amber-400 border-amber-500/30'
                                            : 'bg-white/5 hover:bg-cyan-500/20 text-gray-400 hover:text-cyan-400 border-white/5 hover:border-cyan-500/30'
                                            } disabled:opacity-50 disabled:cursor-not-allowed`}
                                    >
                                        <i className={`fas fa-sync-alt ${isUpdatingThis(file.updateType) ? 'animate-spin' : ''}`}></i>
                                        {isUpdatingThis(file.updateType) ? 'Updating...' : 'Update'}
                                    </button>
                                )}
                                {file.link && (
                                    <a
                                        href={file.link}
                                        className="flex-1 py-2 flex items-center justify-center gap-2 rounded-lg bg-white/5 hover:bg-cyan-500/20 text-gray-400 hover:text-cyan-400 text-xs font-bold transition-all border border-white/5 hover:border-cyan-500/30"
                                    >
                                        View <i className="fas fa-arrow-right"></i>
                                    </a>
                                )}
                            </div>
                        </div>
                    ))
                )}
            </div>

            {/* Update Schedule Section Removed */}

            <div className="flex justify-center">
                <button
                    onClick={loadStatus}
                    disabled={loading}
                    className="px-4 py-2 bg-white/5 hover:bg-white/10 text-gray-400 hover:text-white text-sm font-medium rounded-lg transition-all flex items-center gap-2 border border-white/10"
                >
                    <i className={`fas fa-refresh ${loading ? 'animate-spin' : ''}`}></i>
                    Refresh Status
                </button>
            </div>
        </div>
    );
}

