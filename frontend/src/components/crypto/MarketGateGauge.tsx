'use client';

interface MarketGateGaugeProps {
    score: number;
    gate: string;
    size?: number;
}

export default function MarketGateGauge({ score, gate, size = 200 }: MarketGateGaugeProps) {
    const cx = size / 2;
    const cy = size / 2;
    const r = size * 0.38;
    const strokeW = size * 0.08;

    // Create arc path
    const createArc = (startPct: number, endPct: number) => {
        const startAngle = Math.PI + startPct * Math.PI;
        const endAngle = Math.PI + endPct * Math.PI;
        const x1 = cx + r * Math.cos(startAngle);
        const y1 = cy + r * Math.sin(startAngle);
        const x2 = cx + r * Math.cos(endAngle);
        const y2 = cy + r * Math.sin(endAngle);
        const largeArc = endPct - startPct > 0.5 ? 1 : 0;
        return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`;
    };

    // Needle angle
    const clampedScore = Math.min(100, Math.max(0, score));
    const needleAngle = Math.PI + (clampedScore / 100) * Math.PI;
    const needleLen = r - strokeW;
    const nx = cx + needleLen * Math.cos(needleAngle);
    const ny = cy + needleLen * Math.sin(needleAngle);

    // Colors for gate
    const gateColors: Record<string, { fill: string; glow: string; text: string }> = {
        RED: { fill: '#ef4444', glow: 'rgba(239,68,68,0.4)', text: 'text-red-400' },
        YELLOW: { fill: '#eab308', glow: 'rgba(234,179,8,0.4)', text: 'text-yellow-400' },
        GREEN: { fill: '#22c55e', glow: 'rgba(34,197,94,0.4)', text: 'text-emerald-400' },
    };
    const gc = gateColors[gate] || gateColors.RED;

    return (
        <div className="flex flex-col items-center">
            <svg width={size} height={size * 0.6} viewBox={`0 0 ${size} ${size * 0.6}`}>
                <defs>
                    <filter id="gateGlow">
                        <feGaussianBlur stdDeviation="3" result="blur" />
                        <feMerge>
                            <feMergeNode in="blur" />
                            <feMergeNode in="SourceGraphic" />
                        </feMerge>
                    </filter>
                </defs>

                {/* Background arc */}
                <path d={createArc(0, 1)} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth={strokeW} strokeLinecap="round" />

                {/* RED zone: 0-48 */}
                <path d={createArc(0, 0.48)} fill="none" stroke="#ef4444" strokeWidth={strokeW} strokeLinecap="round" opacity={0.3} />
                {/* YELLOW zone: 48-72 */}
                <path d={createArc(0.48, 0.72)} fill="none" stroke="#eab308" strokeWidth={strokeW} strokeLinecap="round" opacity={0.3} />
                {/* GREEN zone: 72-100 */}
                <path d={createArc(0.72, 1)} fill="none" stroke="#22c55e" strokeWidth={strokeW} strokeLinecap="round" opacity={0.3} />

                {/* Active arc up to score */}
                <path d={createArc(0, clampedScore / 100)} fill="none" stroke={gc.fill} strokeWidth={strokeW} strokeLinecap="round" filter="url(#gateGlow)" />

                {/* Needle */}
                <line x1={cx} y1={cy} x2={nx} y2={ny} stroke="white" strokeWidth={2} strokeLinecap="round" />
                <circle cx={cx} cy={cy} r={4} fill="white" />

                {/* Score text */}
                <text x={cx} y={cy - 8} textAnchor="middle" fill={gc.fill} fontSize={size * 0.16} fontWeight="bold">
                    {score}
                </text>
                <text x={cx} y={cy + 8} textAnchor="middle" fill="rgba(255,255,255,0.5)" fontSize={size * 0.06}>
                    / 100
                </text>
            </svg>
            <div className={`text-sm font-black tracking-wider ${gc.text}`}>{gate}</div>
        </div>
    );
}
