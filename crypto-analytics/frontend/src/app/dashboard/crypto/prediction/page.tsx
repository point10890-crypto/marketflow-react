'use client';

import { useEffect, useState, useRef } from 'react';
import { cryptoAPI, CryptoPredictionData } from '@/lib/api';
import HelpButton from '@/components/ui/HelpButton';
import { createChart, IChartApi, LineSeries, CrosshairMode, Time, LineData } from 'lightweight-charts';

const IMPACT_BAR_SCALE = 500;

export default function CryptoPredictionPage() {
    const [loading, setLoading] = useState(true);
    const [data, setData] = useState<CryptoPredictionData | null>(null);
    const [predHistory, setPredHistory] = useState<Array<{date: string; bullish_probability: number; btc_price: number}>>([]);

    const predChartContainerRef = useRef<HTMLDivElement>(null);
    const predChartRef = useRef<IChartApi | null>(null);

    useEffect(() => {
        loadData();
    }, []);

    const loadData = async () => {
        setLoading(true);
        try {
            const [res, histRes] = await Promise.all([
                cryptoAPI.getPrediction(),
                cryptoAPI.getPredictionHistory().catch(() => null),
            ]);
            setData(res);
            setPredHistory(histRes?.history ?? []);
        } catch (error) {
            console.error('Failed to load prediction data:', error);
        } finally {
            setLoading(false);
        }
    };

    // Prediction History Chart
    useEffect(() => {
        if (predHistory.length === 0 || !predChartContainerRef.current) return;

        if (predChartRef.current) {
            predChartRef.current.remove();
            predChartRef.current = null;
        }

        const chart = createChart(predChartContainerRef.current, {
            width: predChartContainerRef.current.clientWidth,
            height: 250,
            layout: { background: { color: 'transparent' }, textColor: '#6b7280' },
            grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
            rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
            timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: false },
            crosshair: { mode: CrosshairMode.Normal },
        });
        predChartRef.current = chart;

        // Bullish probability line
        const probLine = chart.addSeries(LineSeries, {
            color: '#3b82f6',
            lineWidth: 2,
            priceFormat: { type: 'custom', formatter: (v: number) => `${v.toFixed(1)}%` },
        });

        const last30 = predHistory.slice(-30);
        const chartData: LineData<Time>[] = last30.map(d => ({
            time: d.date as Time,
            value: d.bullish_probability,
        }));
        probLine.setData(chartData);

        // 50% reference line
        const refLine = chart.addSeries(LineSeries, {
            color: 'rgba(107,114,128,0.5)',
            lineWidth: 1,
            lineStyle: 2,
            crosshairMarkerVisible: false,
            lastValueVisible: false,
            priceLineVisible: false,
        });
        if (last30.length >= 2) {
            refLine.setData([
                { time: last30[0].date as Time, value: 50 },
                { time: last30[last30.length - 1].date as Time, value: 50 },
            ]);
        }

        chart.timeScale().fitContent();

        const handleResize = () => {
            if (predChartContainerRef.current) {
                chart.applyOptions({ width: predChartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
            predChartRef.current = null;
        };
    }, [predHistory]);

    const getConfidenceColor = (level: string) => {
        if (level === 'High') return 'text-green-400';
        if (level === 'Moderate') return 'text-yellow-400';
        return 'text-gray-400';
    };

    const getConfidenceBg = (level: string) => {
        if (level === 'High') return 'bg-green-500/10 border-green-500/20';
        if (level === 'Moderate') return 'bg-yellow-500/10 border-yellow-500/20';
        return 'bg-gray-500/10 border-gray-500/20';
    };

    const getProbBarColor = (prob: number, isBullish: boolean) => {
        if (isBullish) {
            if (prob >= 65) return 'bg-green-500';
            if (prob >= 55) return 'bg-green-400/80';
            return 'bg-green-400/50';
        }
        if (prob >= 65) return 'bg-red-500';
        if (prob >= 55) return 'bg-red-400/80';
        return 'bg-red-400/50';
    };

    if (loading) {
        return (
            <div className="space-y-6 animate-pulse">
                <div className="h-16 bg-[#2c2c2e] rounded-xl w-1/3"></div>
                <div className="h-64 bg-[#2c2c2e] rounded-xl"></div>
                <div className="h-48 bg-[#2c2c2e] rounded-xl"></div>
                <div className="grid grid-cols-2 gap-4">
                    <div className="h-40 bg-[#2c2c2e] rounded-xl"></div>
                    <div className="h-40 bg-[#2c2c2e] rounded-xl"></div>
                </div>
            </div>
        );
    }

    if (!data || !data.predictions || Object.keys(data.predictions).length === 0) {
        return (
            <div className="space-y-6">
                {/* Header */}
                <div>
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-orange-500/20 bg-orange-500/5 text-xs text-orange-400 font-medium mb-4">
                        <span className="w-1.5 h-1.5 rounded-full bg-orange-500 animate-ping"></span>
                        ML Prediction
                    </div>
                    <div className="flex items-center gap-3">
                        <h2 className="text-3xl md:text-4xl font-bold tracking-tighter text-white leading-tight mb-2">
                            BTC Direction <span className="text-transparent bg-clip-text bg-gradient-to-r from-orange-400 to-yellow-400">Prediction</span>
                        </h2>
                        <HelpButton title="BTC Prediction 가이드" sections={[
                            { heading: '작동 원리', body: 'ML 모델이 BTC의 다음 방향을 예측합니다.' },
                        ]} />
                    </div>
                </div>
                <div className="p-12 rounded-2xl bg-[#2c2c2e] border border-white/10 text-center">
                    <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-orange-500/10 flex items-center justify-center">
                        <i className="fas fa-brain text-2xl text-orange-500"></i>
                    </div>
                    <div className="text-gray-500 text-lg mb-2">No prediction data available</div>
                    <div className="text-xs text-gray-600">Run: python3 crypto_market/crypto_prediction.py</div>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div>
                <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-orange-500/20 bg-orange-500/5 text-xs text-orange-400 font-medium mb-4">
                    <span className="w-1.5 h-1.5 rounded-full bg-orange-500 animate-ping"></span>
                    ML Prediction
                </div>
                <div className="flex items-center justify-between">
                    <div>
                        <div className="flex items-center gap-3">
                            <h2 className="text-3xl md:text-4xl font-bold tracking-tighter text-white leading-tight mb-2">
                                BTC Direction <span className="text-transparent bg-clip-text bg-gradient-to-r from-orange-400 to-yellow-400">Prediction</span>
                            </h2>
                            <HelpButton title="BTC Prediction 가이드" sections={[
                                { heading: '작동 원리', body: 'ML 앙상블 모델이 BTC의 방향을 예측합니다.\n\n- 입력 피처: RSI, MACD, 볼린저밴드, 거래량, 온체인 지표 등\n- 출력: Bullish/Bearish 확률 (0~100%)\n- Confidence Level: 예측 신뢰도 (High/Moderate/Low)' },
                                { heading: '해석 방법', body: '- Bullish 65%+: 강한 상승 신호\n- Bullish 55~65%: 약한 상승 신호, 선별적 접근\n- 50% 근처: 방향성 불확실, 관망 권장\n- Key Drivers: 예측에 가장 크게 기여한 지표\n- 과거 정확도(Accuracy)를 함께 참고하세요' },
                                { heading: '활용 팁', body: '- Fear & Greed가 극단적일 때는 예측 반대 방향도 고려\n- 여러 시그널(VCP, Gate, Prediction)이 일치하면 신뢰도 상승\n- 크립토는 24시간 거래 -> 예측 시점 주의\n- 레버리지 사용 시 반드시 스톱로스 설정' },
                            ]} />
                        </div>
                        <p className="text-gray-400">ML 기반 BTC 방향 예측</p>
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

            {/* Disclaimer */}
            <div className="p-3 rounded-xl bg-yellow-500/10 border border-yellow-500/20 text-center">
                <span className="text-yellow-400 text-xs font-medium">
                    <i className="fas fa-exclamation-triangle mr-1"></i>
                    본 예측은 교육 및 참고 목적으로만 제공됩니다. 투자 조언이 아니며, 암호화폐 투자는 원금 손실 위험이 있습니다.
                </span>
            </div>

            {/* Prediction Cards */}
            {Object.entries(data.predictions).map(([ticker, pred]) => {
                const isBullish = pred.bullish_probability >= 50;
                const mainColor = isBullish ? 'from-green-500 to-emerald-600' : 'from-red-500 to-rose-600';
                const mainTextColor = isBullish ? 'text-green-400' : 'text-red-400';

                return (
                    <div key={ticker} className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 space-y-6">
                        {/* Ticker Header */}
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-4">
                                <div className={`w-14 h-14 rounded-2xl bg-gradient-to-br ${mainColor} flex items-center justify-center shadow-lg`}>
                                    <i className="fab fa-bitcoin text-2xl text-white"></i>
                                </div>
                                <div>
                                    <h3 className="text-2xl font-black text-white">{ticker.toUpperCase()}</h3>
                                    <span className="text-gray-500 text-sm">${pred.current_price?.toLocaleString() ?? '--'}</span>
                                </div>
                            </div>
                            <div className={`px-4 py-2 rounded-xl text-sm font-bold border ${getConfidenceBg(pred.confidence_level)} ${getConfidenceColor(pred.confidence_level)}`}>
                                {pred.confidence_level} Confidence
                            </div>
                        </div>

                        {/* Main Probability Display */}
                        <div className="bg-[#1c1c1e] rounded-xl p-6 border border-white/5">
                            <div className="flex justify-between text-sm text-gray-500 mb-3">
                                <span>Bearish <span className="text-red-400 font-bold">{pred.bearish_probability}%</span></span>
                                <span>Bullish <span className="text-green-400 font-bold">{pred.bullish_probability}%</span></span>
                            </div>

                            {/* Probability Bar */}
                            <div className="h-8 bg-white/5 rounded-full overflow-hidden flex mb-4">
                                <div
                                    className={`h-full ${getProbBarColor(pred.bearish_probability, false)} transition-all duration-500`}
                                    style={{ width: `${pred.bearish_probability}%` }}
                                ></div>
                                <div
                                    className={`h-full ${getProbBarColor(pred.bullish_probability, true)} transition-all duration-500`}
                                    style={{ width: `${pred.bullish_probability}%` }}
                                ></div>
                            </div>

                            {/* Direction Label */}
                            <div className="text-center">
                                <span className={`text-4xl font-black ${mainTextColor}`}>
                                    {isBullish ? 'BULLISH' : 'BEARISH'}
                                </span>
                                <div className="text-sm text-gray-500 mt-1">
                                    {Math.max(pred.bullish_probability, pred.bearish_probability)}% probability
                                </div>
                            </div>
                        </div>

                        {/* Key Drivers */}
                        {pred.key_drivers && pred.key_drivers.length > 0 && (
                            <div>
                                <h4 className="text-sm font-bold text-gray-400 mb-3 flex items-center gap-2">
                                    <span className="w-1 h-4 bg-orange-500 rounded-full"></span>
                                    Key Drivers
                                </h4>
                                <div className="space-y-2.5">
                                    {pred.key_drivers.map((driver, i) => {
                                        const driverIsBullish = driver.direction === 'bullish';
                                        const barColor = driverIsBullish ? 'bg-green-500' : 'bg-red-500';
                                        const textColor = driverIsBullish ? 'text-green-400' : 'text-red-400';
                                        const barWidth = Math.min(driver.impact * IMPACT_BAR_SCALE, 100);

                                        return (
                                            <div key={i} className="flex items-center gap-3 p-2 rounded-lg hover:bg-white/5 transition-colors">
                                                <span className={`w-5 text-center font-bold ${textColor}`}>
                                                    {driverIsBullish ? '\u2191' : '\u2193'}
                                                </span>
                                                <span className="text-sm text-gray-300 flex-1 min-w-0 truncate">
                                                    {driver.feature.replace(/_/g, ' ')}
                                                </span>
                                                <span className="text-xs text-gray-500 font-mono w-16 text-right">
                                                    {driver.value?.toFixed(2) ?? '--'}
                                                </span>
                                                <div className="w-24 h-2 bg-white/5 rounded-full overflow-hidden">
                                                    <div
                                                        className={`h-full rounded-full ${barColor}`}
                                                        style={{ width: `${barWidth}%` }}
                                                    ></div>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                );
            })}

            {/* Model Info */}
            {data.model_info && (
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6 space-y-5">
                    <h3 className="text-sm font-bold text-gray-400 flex items-center gap-2">
                        <span className="w-1 h-4 bg-orange-500 rounded-full"></span>
                        Model Info
                    </h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div className="p-3 rounded-lg bg-[#1c1c1e] border border-white/5">
                            <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Algorithm</div>
                            <div className="text-sm font-bold text-white">{data.model_info.algorithm || 'N/A'}</div>
                        </div>
                        <div className="p-3 rounded-lg bg-[#1c1c1e] border border-white/5">
                            <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Ensemble Accuracy</div>
                            <div className="text-sm font-bold text-white">{data.model_info.training_accuracy || 'N/A'}%</div>
                        </div>
                        <div className="p-3 rounded-lg bg-[#1c1c1e] border border-white/5">
                            <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Training Samples</div>
                            <div className="text-sm font-bold text-white">{data.model_info.training_samples?.toLocaleString() || '0'}</div>
                        </div>
                        <div className="p-3 rounded-lg bg-[#1c1c1e] border border-white/5">
                            <div className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Last Trained</div>
                            <div className="text-sm font-bold text-white">
                                {data.model_info.last_trained
                                    ? new Date(data.model_info.last_trained).toLocaleDateString('ko-KR')
                                    : 'N/A'}
                            </div>
                        </div>
                    </div>

                    {/* Per-Model Predictions */}
                    {data.model_info.ensemble_models && data.model_info.ensemble_models.length > 0 && (
                        <div>
                            <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">Per-Model Predictions</h4>
                            <div className="space-y-2">
                                {data.model_info.ensemble_models.map((model) => {
                                    const modelBullish = model.bullish >= 50;
                                    return (
                                        <div key={model.name} className="flex items-center gap-3 p-3 rounded-lg bg-[#1c1c1e] border border-white/5">
                                            <span className="text-sm font-medium text-gray-300 w-40 truncate">{model.name}</span>
                                            <span className="text-[10px] text-gray-500 w-20 text-right">Acc {model.accuracy.toFixed(1)}%</span>
                                            <div className="flex-1 h-2 bg-white/5 rounded-full overflow-hidden flex">
                                                <div
                                                    className="h-full bg-red-500/70 transition-all duration-500"
                                                    style={{ width: `${100 - model.bullish}%` }}
                                                ></div>
                                                <div
                                                    className="h-full bg-green-500/70 transition-all duration-500"
                                                    style={{ width: `${model.bullish}%` }}
                                                ></div>
                                            </div>
                                            <span className={`text-sm font-bold w-16 text-right ${modelBullish ? 'text-green-400' : 'text-red-400'}`}>
                                                {model.bullish.toFixed(1)}%
                                            </span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Prediction History Chart */}
            {predHistory.length > 0 && (
                <div className="bg-[#2c2c2e] border border-white/10 rounded-xl p-6">
                    <h3 className="text-sm font-bold text-white mb-4 flex items-center gap-2">
                        <span className="w-1 h-4 bg-blue-500 rounded-full"></span>
                        Prediction History (30d)
                    </h3>
                    <div className="flex items-center gap-4 text-[10px] mb-3">
                        <span className="flex items-center gap-1.5">
                            <span className="w-2.5 h-0.5 bg-blue-500 inline-block rounded"></span>
                            <span className="text-gray-400">Bullish Probability</span>
                        </span>
                        <span className="flex items-center gap-1.5">
                            <span className="w-2.5 h-0.5 bg-gray-500 inline-block rounded border-dashed"></span>
                            <span className="text-gray-400">50% Neutral Line</span>
                        </span>
                    </div>
                    <div ref={predChartContainerRef} className="w-full" />
                </div>
            )}

            {/* Korean Disclaimer */}
            <div className="p-4 rounded-xl bg-[#2c2c2e] border border-white/10 text-center">
                <p className="text-xs text-gray-500 leading-relaxed">
                    본 예측 결과는 머신러닝 모델의 통계적 분석에 기반한 것으로, 미래 가격 변동을 보장하지 않습니다.
                    암호화폐 투자에는 높은 리스크가 따르며, 원금 손실이 발생할 수 있습니다.
                    반드시 본인의 판단과 책임 하에 투자 결정을 내려주세요.
                </p>
            </div>
        </div>
    );
}
