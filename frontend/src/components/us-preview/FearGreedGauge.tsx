'use client';

interface FearGreedData {
  score: number;
  level: string;
  vix: number;
}

export default function FearGreedGauge({ data }: { data: FearGreedData | null }) {
  if (!data) return <GaugeSkeleton />;

  const { score, level, vix } = data;

  // SVG semi-circle gauge
  const radius = 80;
  const cx = 100;
  const cy = 95;
  const startAngle = Math.PI;
  const endAngle = 0;
  const angleRange = startAngle - endAngle;
  const needleAngle = startAngle - (score / 100) * angleRange;

  const needleX = cx + radius * 0.75 * Math.cos(needleAngle);
  const needleY = cy - radius * 0.75 * Math.sin(needleAngle);

  const getColor = (s: number) => {
    if (s <= 25) return { main: '#ef4444', label: 'Extreme Fear', bg: 'bg-red-500/10 border-red-500/30' };
    if (s <= 40) return { main: '#f97316', label: 'Fear', bg: 'bg-orange-500/10 border-orange-500/30' };
    if (s <= 60) return { main: '#eab308', label: 'Neutral', bg: 'bg-yellow-500/10 border-yellow-500/30' };
    if (s <= 75) return { main: '#22c55e', label: 'Greed', bg: 'bg-emerald-500/10 border-emerald-500/30' };
    return { main: '#10b981', label: 'Extreme Greed', bg: 'bg-emerald-500/10 border-emerald-500/30' };
  };

  const colorInfo = getColor(score);

  // Arc path segments
  const createArc = (startPct: number, endPct: number) => {
    const s = startAngle - startPct * angleRange;
    const e = startAngle - endPct * angleRange;
    const x1 = cx + radius * Math.cos(s);
    const y1 = cy - radius * Math.sin(s);
    const x2 = cx + radius * Math.cos(e);
    const y2 = cy - radius * Math.sin(e);
    return `M ${x1} ${y1} A ${radius} ${radius} 0 0 1 ${x2} ${y2}`;
  };

  return (
    <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-6">
      <div className="flex items-center gap-2 mb-4">
        <i className="fas fa-heartbeat text-yellow-400"></i>
        <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider">Fear & Greed</h3>
      </div>

      <div className="flex justify-center">
        <svg width="200" height="120" viewBox="0 0 200 120">
          {/* Background arc segments */}
          <path d={createArc(0, 0.25)} fill="none" stroke="#ef4444" strokeWidth="12" strokeLinecap="round" opacity="0.3" />
          <path d={createArc(0.25, 0.45)} fill="none" stroke="#f97316" strokeWidth="12" strokeLinecap="round" opacity="0.3" />
          <path d={createArc(0.45, 0.55)} fill="none" stroke="#eab308" strokeWidth="12" strokeLinecap="round" opacity="0.3" />
          <path d={createArc(0.55, 0.75)} fill="none" stroke="#22c55e" strokeWidth="12" strokeLinecap="round" opacity="0.3" />
          <path d={createArc(0.75, 1)} fill="none" stroke="#10b981" strokeWidth="12" strokeLinecap="round" opacity="0.3" />

          {/* Active arc */}
          <path d={createArc(0, score / 100)} fill="none" stroke={colorInfo.main} strokeWidth="12" strokeLinecap="round" opacity="0.8" />

          {/* Needle */}
          <line x1={cx} y1={cy} x2={needleX} y2={needleY} stroke="white" strokeWidth="2.5" strokeLinecap="round" />
          <circle cx={cx} cy={cy} r="5" fill={colorInfo.main} stroke="white" strokeWidth="2" />

          {/* Score text */}
          <text x={cx} y={cy - 15} textAnchor="middle" fill="white" fontSize="28" fontWeight="bold">{score}</text>
          <text x={cx} y={cy + 5} textAnchor="middle" fill="#9ca3af" fontSize="10">{level}</text>
        </svg>
      </div>

      <div className="flex items-center justify-center gap-4 mt-2">
        <div className={`px-3 py-1 rounded-full text-xs font-semibold border ${colorInfo.bg}`} style={{ color: colorInfo.main }}>
          {colorInfo.label}
        </div>
        <div className="text-xs text-gray-500">
          VIX <span className="text-white font-bold">{vix}</span>
        </div>
      </div>
    </div>
  );
}

function GaugeSkeleton() {
  return (
    <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-6">
      <div className="w-24 h-4 rounded bg-gray-700 animate-pulse mb-6"></div>
      <div className="flex justify-center">
        <div className="w-[200px] h-[120px] rounded bg-gray-800 animate-pulse"></div>
      </div>
      <div className="flex justify-center mt-4">
        <div className="w-20 h-6 rounded-full bg-gray-700 animate-pulse"></div>
      </div>
    </div>
  );
}
