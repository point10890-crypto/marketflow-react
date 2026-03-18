'use client';

interface PredictionData {
  timestamp: string;
  spy: {
    bullish_probability: number;
    direction: string;
  };
}

export default function Prediction({ data }: { data: PredictionData | null }) {
  if (!data) return <PredictionSkeleton />;

  const { bullish_probability: prob, direction } = data.spy;

  const getDirectionStyle = (dir: string) => {
    if (dir === 'Bullish') return { color: '#10b981', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', icon: 'fa-arrow-trend-up' };
    if (dir === 'Bearish') return { color: '#ef4444', bg: 'bg-red-500/10', border: 'border-red-500/30', icon: 'fa-arrow-trend-down' };
    return { color: '#eab308', bg: 'bg-yellow-500/10', border: 'border-yellow-500/30', icon: 'fa-minus' };
  };

  const style = getDirectionStyle(direction);

  // SVG circular progress
  const radius = 55;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (prob / 100) * circumference;

  return (
    <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-6">
      <div className="flex items-center gap-2 mb-4">
        <i className="fas fa-brain text-purple-400"></i>
        <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider">ML Prediction</h3>
      </div>

      <div className="flex flex-col items-center">
        <div className="relative">
          <svg width="140" height="140" viewBox="0 0 140 140">
            {/* Background circle */}
            <circle cx="70" cy="70" r={radius} fill="none" stroke="#374151" strokeWidth="8" opacity="0.3" />
            {/* Progress circle */}
            <circle
              cx="70" cy="70" r={radius}
              fill="none"
              stroke={style.color}
              strokeWidth="8"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              transform="rotate(-90 70 70)"
              className="transition-all duration-1000"
            />
            {/* Center text */}
            <text x="70" y="62" textAnchor="middle" fill="white" fontSize="28" fontWeight="bold">{prob}%</text>
            <text x="70" y="82" textAnchor="middle" fill="#9ca3af" fontSize="11">Bullish</text>
          </svg>
        </div>

        <div className={`mt-3 px-4 py-1.5 rounded-full text-sm font-bold border ${style.bg} ${style.border}`} style={{ color: style.color }}>
          <i className={`fas ${style.icon} mr-1.5`}></i>
          SPY 5-Day: {direction}
        </div>

        <p className="text-xs text-gray-500 mt-3 text-center">
          GradientBoosting · RSI, MACD, VIX, Volume
        </p>

        <div className="w-full mt-4 flex justify-between text-xs text-gray-500">
          <span>0%</span>
          <div className="flex-1 mx-2 bg-gray-700/50 rounded-full h-2 self-center relative overflow-hidden">
            <div
              className="absolute left-0 top-0 h-full rounded-full transition-all duration-1000"
              style={{ width: `${prob}%`, background: `linear-gradient(90deg, #ef4444, #eab308, #10b981)` }}
            ></div>
          </div>
          <span>100%</span>
        </div>
      </div>
    </div>
  );
}

function PredictionSkeleton() {
  return (
    <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-6">
      <div className="w-24 h-4 rounded bg-gray-700 animate-pulse mb-6"></div>
      <div className="flex flex-col items-center">
        <div className="w-[140px] h-[140px] rounded-full bg-gray-800 animate-pulse"></div>
        <div className="w-32 h-8 rounded-full bg-gray-700 animate-pulse mt-4"></div>
      </div>
    </div>
  );
}
