

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
    updateType?: string;
}

// Category grouping for section headers
const CATEGORY_ORDER = ['KR', 'US', 'Crypto'] as const;
const CATEGORY_MAP: Record<string, string> = {
    'Daily Prices': 'KR', 'AI Jongga V2': 'KR', 'Leading LIVE': 'KR',
    'Market Gate': 'KR', 'Institutional Trend': 'KR', 'VCP Signals': 'KR',
    'KR VCP Enhanced': 'KR',
    'US Smart Money': 'US', 'US Decision Signal': 'US', 'US Sector Heatmap': 'US',
    'US VCP Enhanced': 'US',
    'US Earnings': 'US', 'US Portfolio': 'US',
    'Crypto Overview': 'Crypto', 'Crypto Market Gate': 'Crypto', 'Crypto Briefing': 'Crypto',
    'BTC Prediction': 'Crypto', 'Crypto Risk': 'Crypto', 'Lead-Lag Analysis': 'Crypto',
    'Crypto VCP Signals': 'Crypto', 'Crypto Backtest': 'Crypto',
};

const CATEGORY_LABELS: Record<string, { label: string; icon: string; color: string }> = {
    'KR': { label: 'KR Market', icon: 'fa-won-sign', color: 'text-blue-400' },
    'US': { label: 'US Market', icon: 'fa-dollar-sign', color: 'text-green-400' },
    'Crypto': { label: 'Crypto', icon: 'fa-bitcoin-sign', color: 'text-amber-400' },
};



// Map data names to update types
const UPDATE_TYPE_MAP: Record<string, string> = {
    // KR Market
    'Daily Prices': 'prices',
    'AI Jongga V2': 'jongga_v2',
    'Leading LIVE': 'leading',
    'Institutional Trend': 'institutional',
    'VCP Signals': 'vcp_signals',
    'KR VCP Enhanced': 'vcp_kr',
    // US Market (batch update)
    'US Smart Money': 'us_market',
    'US Decision Signal': 'us_market',
    'US Sector Heatmap': 'us_market',
    'US Earnings': 'us_market',
    'US Portfolio': 'us_market',
    'US VCP Enhanced': 'vcp_us',
    // Crypto Analytics
    'Crypto Overview': 'crypto_all',
    'Crypto Market Gate': 'crypto_gate',
    'Crypto Briefing': 'crypto_briefing',
    'BTC Prediction': 'crypto_prediction',
    'Crypto Risk': 'crypto_risk',
    'Lead-Lag Analysis': 'crypto_leadlag',
    'Crypto VCP Signals': 'crypto_scan',
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

    const STALE_DAYS = 7;

    const isStale = (file: DataStatus) => {
        if (!file.exists || !file.lastModified) return true;
        const diffMs = Date.now() - new Date(file.lastModified).getTime();
        return diffMs > STALE_DAYS * 24 * 60 * 60 * 1000;
    };

    const activeFiles = dataFiles.filter(f => !isStale(f));
    const inactiveFiles = dataFiles.filter(f => isStale(f));
    const activeCount = activeFiles.length;
    const totalCount = dataFiles.length;

    const renderSection = (files: DataStatus[], sectionType: 'active' | 'inactive') => {
        return CATEGORY_ORDER.map((cat) => {
            const catFiles = files.filter(f => CATEGORY_MAP[f.name] === cat);
            if (catFiles.length === 0) return null;
            const info = CATEGORY_LABELS[cat];
            return (
                <div key={cat} className="space-y-3">
                    <div className="flex items-center gap-2 px-1">
                        <i className={`fas ${info.icon} ${sectionType === 'inactive' ? 'text-gray-600' : info.color} text-sm`}></i>
                        <h3 className={`text-sm font-bold ${sectionType === 'inactive' ? 'text-gray-600' : info.color}`}>{info.label}</h3>
                        <span className="text-[10px] text-gray-600 font-mono">{catFiles.length}</span>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 md:gap-4">
                        {renderCards(catFiles)}
                    </div>
                </div>
            );
        });
    };

    const renderMobileCard = (file: DataStatus) => (
        <div key={file.path} className="p-3 rounded-xl bg-[#1c1c1e] border border-white/10 flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${file.exists ? 'bg-cyan-500/10 text-cyan-400' : 'bg-red-500/10 text-red-400'}`}>
                        <i className={`fas ${file.exists ? 'fa-file-alt' : 'fa-file-excel'} text-xs`}></i>
                    </div>
                    <div className="min-w-0">
                        <h3 className="text-sm text-white font-bold truncate">{file.name}</h3>
                        {file.menu && <div className="text-[10px] text-gray-600 truncate">{file.menu}</div>}
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
                    {file.rowCount != null && (<><span className="text-gray-700">|</span><span className="font-mono">{file.rowCount.toLocaleString()} rows</span></>)}
                </div>
            )}
            {(file.updateType || file.link) && (
                <div className="flex gap-2">
                    {file.updateType && (
                        <button onClick={() => triggerSingleUpdate(file.updateType!, file.name)} disabled={updating || !!updatingItem}
                            className={`flex-1 py-1.5 flex items-center justify-center gap-1.5 rounded-lg text-[11px] font-bold transition-all border ${isUpdatingThis(file.updateType) ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' : 'bg-white/5 text-gray-400 border-white/5'} disabled:opacity-50 disabled:cursor-not-allowed`}>
                            <i className={`fas fa-sync-alt ${isUpdatingThis(file.updateType) ? 'animate-spin' : ''}`}></i>
                            {isUpdatingThis(file.updateType) ? 'Updating...' : 'Update'}
                        </button>
                    )}
                    {file.link && (
                        <a href={file.link} className="flex-1 py-1.5 flex items-center justify-center gap-1.5 rounded-lg bg-white/5 text-gray-400 text-[11px] font-bold transition-all border border-white/5">
                            View <i className="fas fa-arrow-right text-[9px]"></i>
                        </a>
                    )}
                </div>
            )}
        </div>
    );

    const renderDesktopCard = (file: DataStatus) => (
        <div key={file.path} className="p-5 rounded-2xl bg-[#1c1c1e] border border-white/10 hover:border-white/20 transition-all group flex flex-col">
            <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${file.exists ? 'bg-cyan-500/10 text-cyan-400' : 'bg-red-500/10 text-red-400'}`}>
                        <i className={`fas ${file.exists ? 'fa-file-alt' : 'fa-file-excel'}`}></i>
                    </div>
                    <div>
                        <h3 className="text-white font-bold">{file.name}</h3>
                        {file.menu && <div className="text-[10px] text-gray-500 mt-0.5 flex items-center gap-1"><i className="fas fa-link text-gray-600"></i> {file.menu}</div>}
                        <p className="text-[10px] text-gray-700 font-mono truncate max-w-[150px] mt-0.5">{file.path}</p>
                    </div>
                </div>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${getStatusColor(file.exists, file.lastModified)}`}>
                    {file.exists ? 'OK' : 'MISSING'}
                </span>
            </div>
            {file.exists && (
                <div className="space-y-2 text-sm flex-1">
                    <div className="flex justify-between text-gray-400"><span>Last Updated</span><span className="text-white font-medium">{formatTime(file.lastModified)}</span></div>
                    <div className="flex justify-between text-gray-400"><span>File Size</span><span className="text-white font-mono text-xs">{file.size}</span></div>
                    {file.rowCount != null && <div className="flex justify-between text-gray-400"><span>Records</span><span className="text-white font-mono text-xs">{file.rowCount.toLocaleString()}</span></div>}
                </div>
            )}
            <div className="mt-4 flex gap-2">
                {file.updateType && (
                    <button onClick={() => triggerSingleUpdate(file.updateType!, file.name)} disabled={updating || !!updatingItem}
                        className={`flex-1 py-2 flex items-center justify-center gap-2 rounded-lg text-xs font-bold transition-all border ${isUpdatingThis(file.updateType) ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' : 'bg-white/5 hover:bg-cyan-500/20 text-gray-400 hover:text-cyan-400 border-white/5 hover:border-cyan-500/30'} disabled:opacity-50 disabled:cursor-not-allowed`}>
                        <i className={`fas fa-sync-alt ${isUpdatingThis(file.updateType) ? 'animate-spin' : ''}`}></i>
                        {isUpdatingThis(file.updateType) ? 'Updating...' : 'Update'}
                    </button>
                )}
                {file.link && (
                    <a href={file.link} className="flex-1 py-2 flex items-center justify-center gap-2 rounded-lg bg-white/5 hover:bg-cyan-500/20 text-gray-400 hover:text-cyan-400 text-xs font-bold transition-all border border-white/5 hover:border-cyan-500/30">
                        View <i className="fas fa-arrow-right"></i>
                    </a>
                )}
            </div>
        </div>
    );

    const renderCards = (files: DataStatus[]) => files.map((file) => isMobile ? renderMobileCard(file) : renderDesktopCard(file));

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
                        <p className="text-gray-400 text-sm md:text-lg">
                            <span className="text-emerald-400 font-bold">{activeCount}</span>
                            <span className="text-gray-600">/{totalCount}</span> 서비스 운영 중
                            {inactiveFiles.length > 0 && (
                                <span className="ml-2 text-gray-600">· <span className="text-red-400/60">{inactiveFiles.length}</span> 비활성</span>
                            )}
                        </p>
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

            {loading && dataFiles.length === 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 md:gap-4">
                    {Array.from({ length: 6 }).map((_, i) => (
                        <div key={i} className="p-4 md:p-5 rounded-2xl bg-[#1c1c1e] border border-white/10 animate-pulse">
                            <div className="h-4 bg-white/10 rounded w-1/2 mb-3"></div>
                            <div className="h-3 bg-white/10 rounded w-3/4 mb-2"></div>
                            <div className="h-3 bg-white/10 rounded w-1/3"></div>
                        </div>
                    ))}
                </div>
            ) : dataFiles.length === 0 ? (
                <div className="text-center py-20 text-gray-500">
                    <i className="fas fa-database text-4xl mb-4 opacity-30"></i>
                    <p>No data files found</p>
                </div>
            ) : (
                <>
                {/* ── Active Services ── */}
                <div className="space-y-6">
                    <div className="flex items-center gap-3">
                        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        <h3 className="text-base font-bold text-white">Active Services</h3>
                        <span className="text-xs text-emerald-400/60 font-mono">{activeCount}</span>
                    </div>
                    {renderSection(activeFiles, 'active')}
                </div>

                {/* ── Inactive Services ── */}
                {inactiveFiles.length > 0 && (
                    <div className="space-y-6 mt-8 pt-6 border-t border-white/5">
                        <div className="flex items-center gap-3">
                            <span className="w-2 h-2 rounded-full bg-gray-600"></span>
                            <h3 className="text-base font-bold text-gray-500">Inactive / Stale</h3>
                            <span className="text-xs text-gray-600 font-mono">{inactiveFiles.length}</span>
                            <span className="text-[10px] text-gray-700">7일 이상 미갱신</span>
                        </div>
                        {renderSection(inactiveFiles, 'inactive')}
                    </div>
                )}
                </>
            )}

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

