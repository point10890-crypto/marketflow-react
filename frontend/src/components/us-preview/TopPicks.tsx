'use client';

interface Pick {
  rank?: number;
  ticker: string;
  name: string;
  sector: string;
  price: number;
  composite_score: number;
  rsi: number;
  grade?: string;
  signal?: string;
}

interface TopPicksData {
  timestamp: string;
  top_picks: Pick[];
}

export default function TopPicks({ data }: { data: TopPicksData | null }) {
  if (!data) return <TopPicksSkeleton />;

  const picks = data.top_picks || [];

  const getGradeBadge = (grade: string) => {
    const colors: Record<string, string> = {
      'A': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
      'B': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
      'C': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    };
    return colors[grade] || 'bg-gray-500/20 text-gray-400 border-gray-500/30';
  };

  const getSignalColor = (signal: string) => {
    if (signal === 'Strong Buy') return 'text-emerald-400';
    if (signal === 'Buy') return 'text-blue-400';
    return 'text-yellow-400';
  };

  const getRsiColor = (rsi: number) => {
    if (rsi >= 70) return 'text-red-400';
    if (rsi <= 30) return 'text-emerald-400';
    return 'text-gray-300';
  };

  return (
    <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <i className="fas fa-trophy text-yellow-400"></i>
          <h3 className="text-lg font-bold text-white">Smart Money Top Picks</h3>
        </div>
        <span className="text-xs text-gray-500">{picks.length} stocks</span>
      </div>

      {/* Desktop Table */}
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="text-xs text-gray-500 uppercase border-b border-white/5">
              <th className="text-left py-2 px-2">#</th>
              <th className="text-left py-2 px-2">Ticker</th>
              <th className="text-left py-2 px-2">Sector</th>
              <th className="text-right py-2 px-2">Price</th>
              <th className="text-right py-2 px-2">Score</th>
              <th className="text-right py-2 px-2">RSI</th>
              <th className="text-center py-2 px-2">Grade</th>
              <th className="text-center py-2 px-2">Signal</th>
            </tr>
          </thead>
          <tbody>
            {picks.map((pick, i) => (
              <tr key={pick.ticker} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                <td className="py-3 px-2 text-sm text-gray-500 font-bold">{pick.rank || i + 1}</td>
                <td className="py-3 px-2">
                  <div className="text-sm font-bold text-white">{pick.ticker}</div>
                  <div className="text-xs text-gray-500 truncate max-w-[120px]">{pick.name}</div>
                </td>
                <td className="py-3 px-2 text-xs text-gray-400">{pick.sector}</td>
                <td className="py-3 px-2 text-sm text-white text-right font-mono">${pick.price?.toFixed(2) || '0.00'}</td>
                <td className="py-3 px-2 text-right">
                  <span className="text-sm font-bold text-white">{pick.composite_score}</span>
                  <div className="w-full bg-gray-700/50 rounded-full h-1 mt-1">
                    <div className="bg-blue-500 h-1 rounded-full" style={{ width: `${pick.composite_score}%` }}></div>
                  </div>
                </td>
                <td className={`py-3 px-2 text-sm text-right font-mono ${getRsiColor(pick.rsi)}`}>{pick.rsi}</td>
                <td className="py-3 px-2 text-center">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-bold border ${getGradeBadge(pick.grade || 'C')}`}>
                    {pick.grade || '-'}
                  </span>
                </td>
                <td className={`py-3 px-2 text-center text-xs font-bold ${getSignalColor(pick.signal || 'Hold')}`}>
                  {pick.signal || '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile Cards */}
      <div className="md:hidden space-y-2">
        {picks.map((pick, i) => (
          <div key={pick.ticker} className="rounded-xl bg-black/30 border border-white/5 p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 font-bold">#{pick.rank || i + 1}</span>
                <span className="text-sm font-bold text-white">{pick.ticker}</span>
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold border ${getGradeBadge(pick.grade || 'C')}`}>
                  {pick.grade || '-'}
                </span>
              </div>
              <span className={`text-xs font-bold ${getSignalColor(pick.signal || 'Hold')}`}>{pick.signal}</span>
            </div>
            <div className="flex items-center justify-between text-xs">
              <span className="text-gray-400">{pick.sector}</span>
              <div className="flex gap-3">
                <span className="text-white font-mono">${pick.price?.toFixed(2) || '0.00'}</span>
                <span className="text-blue-400">Score {pick.composite_score}</span>
                <span className={getRsiColor(pick.rsi)}>RSI {pick.rsi}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {picks.length === 0 && (
        <div className="text-center text-gray-500 text-sm py-12">
          <i className="fas fa-search text-2xl mb-2 opacity-30"></i>
          <p>No stock picks available. Run screener first.</p>
        </div>
      )}
    </div>
  );
}

function TopPicksSkeleton() {
  return (
    <div className="rounded-2xl bg-[#1c1c1e] border border-white/10 p-6">
      <div className="w-40 h-5 rounded bg-gray-700 animate-pulse mb-4"></div>
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4">
            <div className="w-6 h-4 rounded bg-gray-700 animate-pulse"></div>
            <div className="w-16 h-4 rounded bg-gray-700 animate-pulse"></div>
            <div className="flex-1 h-4 rounded bg-gray-700 animate-pulse"></div>
            <div className="w-16 h-4 rounded bg-gray-700 animate-pulse"></div>
          </div>
        ))}
      </div>
    </div>
  );
}
