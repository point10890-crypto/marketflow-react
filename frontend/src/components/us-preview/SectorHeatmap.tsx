'use client';

interface SectorItem {
  ticker: string;
  name: string;
  price: number;
  change: number;
}

interface SectorData {
  timestamp: string;
  sectors: SectorItem[];
}

export default function SectorHeatmap({ data }: { data: SectorData | null }) {
  if (!data) return <SectorSkeleton />;

  const sectors = data.sectors || [];

  const getHeatColor = (change: number) => {
    const intensity = Math.min(Math.abs(change) * 40, 100);
    if (change >= 0) {
      return {
        bg: `rgba(16, 185, 129, ${(intensity / 100) * 0.35})`,
        border: `rgba(16, 185, 129, ${(intensity / 100) * 0.5})`,
        text: 'text-emerald-400',
      };
    }
    return {
      bg: `rgba(239, 68, 68, ${(intensity / 100) * 0.35})`,
      border: `rgba(239, 68, 68, ${(intensity / 100) * 0.5})`,
      text: 'text-red-400',
    };
  };

  return (
    <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-6">
      <div className="flex items-center gap-2 mb-4">
        <i className="fas fa-th text-cyan-400"></i>
        <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider">Sector Heatmap</h3>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {sectors.map((s) => {
          const heat = getHeatColor(s.change);
          return (
            <div
              key={s.ticker}
              className="rounded-lg p-3 transition-all hover:scale-[1.03] cursor-default"
              style={{ background: heat.bg, border: `1px solid ${heat.border}` }}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400 font-medium">{s.ticker}</span>
                <span className={`text-sm font-bold ${heat.text}`}>
                  {s.change >= 0 ? '+' : ''}{s.change.toFixed(2)}%
                </span>
              </div>
              <div className="text-xs font-semibold text-white mt-1 truncate">{s.name}</div>
            </div>
          );
        })}
      </div>

      {sectors.length === 0 && (
        <div className="text-center text-gray-500 text-sm py-8">
          No sector data available
        </div>
      )}
    </div>
  );
}

function SectorSkeleton() {
  return (
    <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-6">
      <div className="w-28 h-4 rounded bg-gray-700 animate-pulse mb-4"></div>
      <div className="grid grid-cols-2 gap-2">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="rounded-lg bg-gray-800/50 p-3">
            <div className="w-12 h-3 rounded bg-gray-700 animate-pulse mb-2"></div>
            <div className="w-20 h-3 rounded bg-gray-700 animate-pulse"></div>
          </div>
        ))}
      </div>
    </div>
  );
}
