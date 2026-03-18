'use client';

import { useEffect, useState } from 'react';
import { cryptoAPI, CryptoRiskData } from '@/lib/api';
import HelpButton from '@/components/ui/HelpButton';

export default function CryptoRiskDashboard() {
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState<CryptoRiskData | null>(null);

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            const res = await cryptoAPI.getRisk();
            setData(res);
        } catch (error) {
            console.error('Failed to load risk data:', error);
        } finally {
            setLoading(false);
        }
    };

    const getRiskColor = (level: string) => {
        if (level === 'Low') return 'text-green-400 bg-green-500/10 border-green-500/20';
        if (level === 'High' || level === 'Critical') return 'text-red-400 bg-red-500/10 border-red-500/20';
        return 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20';
    };

    const getSeverityBadge = (severity: string) => {
        switch (severity) {
            case 'critical': return 'bg-red-500/20 text-red-400 border-red-500/30';
            case 'warning': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
            default: return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
        }
    };

    const getSeverityBorder = (severity: string) => {
        switch (severity) {
            case 'critical': return 'border-red-500/30 bg-red-500/5';
            case 'warning': return 'border-yellow-500/30 bg-yellow-500/5';
            default: return 'border-blue-500/30 bg-blue-500/5';
        }
    };

    const getHeatmapColor = (val: number) => {
        if (val >= 0.8) return 'bg-red-500/80';
        if (val >= 0.5) return 'bg-red-500/50';
        if (val >= 0.2) return 'bg-orange-500/40';
        if (val >= -0.2) return 'bg-gray-500/30';
        if (val >= -0.5) return 'bg-blue-500/40';
        if (val >= -0.8) return 'bg-blue-500/60';
        return 'bg-blue-500/80';
    };

    const getHeatmapText = (val: number) => {
        if (val >= 0.5) return 'text-white';
        if (val <= -0.5) return 'text-white';
        return 'text-gray-300';
    };

    const getVarColor = (val: number) => {
        const abs = Math.abs(val);
        if (abs > 10) return 'text-red-400';
        if (abs > 5) return 'text-orange-400';
        if (abs > 3) return 'text-yellow-400';
        return 'text-green-400';
    };

    if (loading) {
        return (
            <div className="space-y-6 animate-pulse">
                <div className="h-16 bg-[#2c2c2e] rounded-xl w-1/3"></div>
                <div className="grid grid-cols-4 gap-4">
                    {[1, 2, 3, 4].map(i => <div key={i} className="h-28 bg-[#2c2c2e] rounded-xl"></div>)}
                </div>
                <div className="h-72 bg-[#2c2c2e] rounded-xl"></div>
                <div className="h-48 bg-[#2c2c2e] rounded-xl"></div>
            </div>
        );
    }

    if (!data) {
        return (
            <div className="space-y-6">
                <div>
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-red-500/20 bg-red-500/5 text-xs text-red-400 font-medium mb-4">
                        <i className="fas fa-shield-alt"></i>
                        Risk Management
                    </div>
                    <div className="flex items-center gap-3">
                        <h2 className="text-3xl md:text-4xl font-bold tracking-tighter text-white leading-tight mb-2">
                            Crypto Risk <span className="text-transparent bg-clip-text bg-gradient-to-r from-red-400 to-orange-400">Dashboard</span>
                        </h2>
                        <HelpButton title="Crypto Risk 가이드" sections={[
                            { heading: '작동 원리', body: '암호화폐 포트폴리오의 리스크를 분석합니다.' },
                        ]} />
                    </div>
                </div>
                <div className="p-12 rounded-2xl bg-[#2c2c2e] border border-white/10 text-center">
                    <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-500/10 flex items-center justify-center">
                        <i className="fas fa-shield-alt text-2xl text-red-500"></i>
                    </div>
                    <div className="text-gray-500 text-lg mb-2">No risk data available</div>
                    <div className="text-xs text-gray-600">Run: python3 crypto_market/crypto_risk.py</div>
                </div>
            </div>
        );
    }

    const { portfolio_summary, correlation_matrix, individual_risk, concentration, alerts } = data;

    return (
        <div className="space-y-6">
            {/* Header */}
            <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-red-500/20 bg-red-500/5 text-xs text-red-400 font-medium mb-4">
                    <i className="fas fa-shield-alt"></i>
                    Risk Management
                </div>
                <div className="flex items-center justify-between">
                    <div>
                        <div className="flex items-center gap-3">
                            <h2 className="text-3xl md:text-4xl font-bold tracking-tighter text-white leading-tight mb-2">
                                Crypto Risk <span className="text-transparent bg-clip-text bg-gradient-to-r from-red-400 to-orange-400">Dashboard</span>
                            </h2>
                            <HelpButton title="Crypto Risk Dashboard 가이드" sections={[
                                { heading: '주요 지표', body: '- VaR (95%, 1D): 95% 확률로 1일 내 예상 최대 손실률\n- CVaR (95%, 1D): VaR를 초과하는 극단적 손실의 평균. 꼬리 위험 측정\n- Risk Level: Low/Moderate/High/Critical\n\n암호화폐는 전통 자산 대비 변동성이 매우 높으므로 VaR 수치가 클 수 있습니다.' },
                                { heading: 'Correlation Heatmap', body: '코인 간 상관관계를 시각적으로 보여줍니다.\n\n- +1.0 (빨강): 완전 양의 상관관계 (같은 방향 움직임)\n- 0.0 (회색): 상관관계 없음\n- -1.0 (파랑): 완전 음의 상관관계 (반대 방향)\n\n상관관계가 높은 코인들은 분산 효과가 제한적입니다.' },
                                { heading: '집중도 위험', body: '- BTC 비중이 너무 높으면 비트코인 의존도 과다\n- Top 3 비중이 90%+면 분산 부족\n- 적절한 알트코인 분배로 리스크 분산 권장\n\nAlerts에서 critical/warning 알림을 확인하세요.' },
                            ]} />
                        </div>
                        <p className="text-gray-400">VaR/CVaR, 상관관계, 포트폴리오 리스크 분석</p>
                    </div>
                    <button
                        onClick={loadData}
                        disabled={loading}
                        className="px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-white hover:bg-white/10 transition-all disabled:opacity-50"
                    >
                        <i className={`fas fa-sync-alt mr-2 ${loading ? 'animate-spin' : ''}`}></i>
                        Refresh
                    </button>
                </div>
            </div>

            {/* Top Row - Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {/* VaR */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-2">VaR (95%, 1D)</div>
                    <div className="text-3xl font-black text-orange-400">
                        {Math.abs(portfolio_summary.portfolio_var_95_1d).toFixed(2)}%
                    </div>
                    <div className="text-xs text-gray-500 mt-2">예상 최대 일일 손실률</div>
                </div>

                {/* CVaR */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-2">CVaR (95%, 1D)</div>
                    <div className="text-3xl font-black text-red-400">
                        {Math.abs(portfolio_summary.portfolio_cvar_95_1d).toFixed(2)}%
                    </div>
                    <div className="text-xs text-gray-500 mt-2">극단 손실 평균</div>
                </div>

                {/* Risk Level */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-2">Risk Level</div>
                    <div className="flex items-center gap-2 mt-1">
                        <span className={`text-2xl font-black px-4 py-1 rounded-xl border ${getRiskColor(portfolio_summary.risk_level)}`}>
                            {portfolio_summary.risk_level}
                        </span>
                    </div>
                </div>

                {/* Total Coins */}
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-2">Total Coins</div>
                    <div className="text-3xl font-black text-white">
                        {portfolio_summary.total_coins}
                    </div>
                    <div className="text-xs text-gray-500 mt-2">Tracked positions</div>
                </div>
            </div>

            {/* Correlation Heatmap */}
            {correlation_matrix && correlation_matrix.coins.length > 0 && (
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                        <span className="w-6 h-6 rounded bg-purple-500/10 flex items-center justify-center text-purple-500">
                            <i className="fas fa-th text-xs"></i>
                        </span>
                        Correlation Heatmap
                    </h3>

                    <div className="overflow-x-auto">
                        <div className="inline-block min-w-full">
                            {/* Header Row */}
                            <div className="flex">
                                <div className="w-16 h-10 shrink-0"></div>
                                {correlation_matrix.coins.map(coin => (
                                    <div key={coin} className="w-16 h-10 shrink-0 flex items-center justify-center text-[10px] font-bold text-gray-400">
                                        {coin}
                                    </div>
                                ))}
                            </div>

                            {/* Data Rows */}
                            {correlation_matrix.coins.map((rowCoin, rowIdx) => (
                                <div key={rowCoin} className="flex">
                                    <div className="w-16 h-14 shrink-0 flex items-center justify-start text-[10px] font-bold text-gray-400 pl-1">
                                        {rowCoin}
                                    </div>
                                    {correlation_matrix.values[rowIdx].map((val, colIdx) => (
                                        <div
                                            key={colIdx}
                                            className={`w-16 h-14 shrink-0 flex items-center justify-center rounded-md m-0.5 text-xs font-bold ${getHeatmapColor(val)} ${getHeatmapText(val)} transition-all hover:ring-1 hover:ring-white/30`}
                                            title={`${rowCoin} vs ${correlation_matrix.coins[colIdx]}: ${val.toFixed(3)}`}
                                        >
                                            {val.toFixed(2)}
                                        </div>
                                    ))}
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Legend */}
                    <div className="flex items-center justify-center gap-2 mt-4">
                        <span className="text-[9px] text-gray-500">-1.0</span>
                        <div className="flex gap-0.5">
                            <div className="w-6 h-3 rounded-sm bg-blue-500/80"></div>
                            <div className="w-6 h-3 rounded-sm bg-blue-500/60"></div>
                            <div className="w-6 h-3 rounded-sm bg-blue-500/40"></div>
                            <div className="w-6 h-3 rounded-sm bg-gray-500/30"></div>
                            <div className="w-6 h-3 rounded-sm bg-orange-500/40"></div>
                            <div className="w-6 h-3 rounded-sm bg-red-500/50"></div>
                            <div className="w-6 h-3 rounded-sm bg-red-500/80"></div>
                        </div>
                        <span className="text-[9px] text-gray-500">+1.0</span>
                    </div>
                </div>
            )}

            {/* Individual Risk Table */}
            {individual_risk && Object.keys(individual_risk).length > 0 && (
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                        <span className="w-6 h-6 rounded bg-orange-500/10 flex items-center justify-center text-orange-500">
                            <i className="fas fa-chart-bar text-xs"></i>
                        </span>
                        Individual Coin Risk
                    </h3>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-white/10">
                                    <th className="text-left py-2 px-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold">Coin</th>
                                    <th className="text-right py-2 px-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold">VaR (95%, 1D)</th>
                                    <th className="text-right py-2 px-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold">Max DD (30d)</th>
                                    <th className="text-right py-2 px-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold">Volatility (30d)</th>
                                    <th className="text-right py-2 px-3 text-[10px] text-gray-500 uppercase tracking-wider font-bold w-32">Severity</th>
                                </tr>
                            </thead>
                            <tbody>
                                {Object.entries(individual_risk).map(([coin, risk]) => {
                                    const varAbs = Math.abs(risk.var_95_1d);
                                    const ddAbs = Math.abs(risk.max_dd_30d);
                                    return (
                                        <tr key={coin} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                                            <td className="py-3 px-3 font-bold text-white">{coin}</td>
                                            <td className={`py-3 px-3 text-right font-bold font-mono ${getVarColor(risk.var_95_1d)}`}>
                                                {varAbs.toFixed(2)}%
                                            </td>
                                            <td className={`py-3 px-3 text-right font-bold font-mono ${getVarColor(risk.max_dd_30d)}`}>
                                                {ddAbs.toFixed(2)}%
                                            </td>
                                            <td className="py-3 px-3 text-right text-gray-400 font-mono">
                                                {risk.volatility_30d.toFixed(2)}%
                                            </td>
                                            <td className="py-3 px-3 text-right">
                                                <div className="w-full bg-white/5 rounded-full h-2 overflow-hidden">
                                                    <div
                                                        className={`h-full rounded-full ${
                                                            varAbs < 3 ? 'bg-green-500' :
                                                            varAbs < 5 ? 'bg-yellow-500' :
                                                            varAbs < 10 ? 'bg-orange-500' :
                                                            'bg-red-500'
                                                        }`}
                                                        style={{ width: `${Math.min(varAbs * 5, 100)}%` }}
                                                    />
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Concentration */}
            {concentration && (
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                        <span className="w-6 h-6 rounded bg-teal-500/10 flex items-center justify-center text-teal-500">
                            <i className="fas fa-chart-pie text-xs"></i>
                        </span>
                        Portfolio Concentration
                    </h3>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        {/* BTC Weight */}
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <span className="text-sm text-gray-400">BTC Weight</span>
                                <span className="text-sm font-bold text-orange-400">{concentration.btc_weight_pct.toFixed(1)}%</span>
                            </div>
                            <div className="w-full bg-white/5 rounded-full h-3 overflow-hidden">
                                <div
                                    className="h-full bg-gradient-to-r from-orange-500 to-yellow-500 rounded-full transition-all"
                                    style={{ width: `${concentration.btc_weight_pct}%` }}
                                />
                            </div>
                            <div className="text-[10px] text-gray-600 mt-1">
                                {concentration.btc_weight_pct > 60 ? 'High BTC concentration' : 'Balanced allocation'}
                            </div>
                        </div>

                        {/* Top 3 Weight */}
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <span className="text-sm text-gray-400">Top 3 Weight</span>
                                <span className="text-sm font-bold text-blue-400">{concentration.top3_weight_pct.toFixed(1)}%</span>
                            </div>
                            <div className="w-full bg-white/5 rounded-full h-3 overflow-hidden">
                                <div
                                    className="h-full bg-gradient-to-r from-blue-500 to-cyan-500 rounded-full transition-all"
                                    style={{ width: `${concentration.top3_weight_pct}%` }}
                                />
                            </div>
                            <div className="text-[10px] text-gray-600 mt-1">
                                {concentration.top3_weight_pct > 80 ? 'Highly concentrated in top 3' : 'Reasonably distributed'}
                            </div>
                        </div>
                    </div>

                    {/* Concentration Warnings */}
                    {concentration.warnings && concentration.warnings.length > 0 && (
                        <div className="mt-4 space-y-2">
                            {concentration.warnings.map((warning, i) => (
                                <div key={i} className="flex items-start gap-2 p-2 rounded-lg bg-yellow-500/5 border border-yellow-500/10">
                                    <i className="fas fa-exclamation-triangle text-yellow-500 text-xs mt-0.5"></i>
                                    <span className="text-xs text-yellow-400">{warning}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Alerts */}
            {alerts && alerts.length > 0 && (
                <div className="space-y-3">
                    <h3 className="text-sm font-bold text-gray-400 flex items-center gap-2">
                        <i className="fas fa-bell text-yellow-500"></i>
                        Active Alerts
                    </h3>
                    {alerts.map((alert, i) => (
                        <div key={i} className={`p-4 rounded-xl border ${getSeverityBorder(alert.severity)}`}>
                            <div className="flex items-center gap-3">
                                <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${getSeverityBadge(alert.severity)}`}>
                                    {alert.severity}
                                </span>
                                {alert.coin && <span className="text-xs font-bold text-white">{alert.coin}</span>}
                            </div>
                            <p className="text-sm text-gray-300 mt-2">{alert.message}</p>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
