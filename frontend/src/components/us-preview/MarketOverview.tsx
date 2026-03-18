'use client';

import { useEffect, useState } from 'react';

interface MarketItem {
  name: string;
  price: number;
  change: number;
}

interface MarketData {
  indices: Record<string, MarketItem>;
  volatility: Record<string, MarketItem>;
  bonds: Record<string, MarketItem>;
  currencies: Record<string, MarketItem>;
  commodities: Record<string, MarketItem>;
}

export default function MarketOverview({ data }: { data: MarketData | null }) {
  if (!data) return <MarketOverviewSkeleton />;

  const allItems: { key: string; name: string; price: number; change: number; icon: string }[] = [];

  const iconMap: Record<string, string> = {
    'S&P 500': 'fa-chart-line', 'NASDAQ 100': 'fa-laptop-code', 'Dow Jones': 'fa-industry',
    'Russell 2000': 'fa-chart-area', 'VIX': 'fa-bolt', '10Y Treasury': 'fa-landmark',
    'Dollar Index': 'fa-dollar-sign', 'USD/KRW': 'fa-won-sign', 'Gold': 'fa-coins', 'Bitcoin': 'fa-bitcoin',
  };

  for (const [, items] of Object.entries(data)) {
    if (typeof items === 'object' && items !== null && !Array.isArray(items)) {
      for (const [ticker, item] of Object.entries(items)) {
        if (item && typeof item === 'object' && 'name' in item) {
          const mi = item as MarketItem;
          allItems.push({ key: ticker, name: mi.name, price: mi.price, change: mi.change, icon: iconMap[mi.name] || 'fa-chart-bar' });
        }
      }
    }
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <i className="fas fa-globe text-blue-400"></i>
        <h2 className="text-lg font-bold text-white">Market Overview</h2>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {allItems.map((item) => (
          <div key={item.key} className="rounded-xl bg-[#1c1c1e] border border-white/10 p-4 hover:border-white/20 transition-all hover:scale-[1.02]">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-500 font-medium">{item.name}</span>
              <i className={`fas ${item.icon} text-xs ${item.change >= 0 ? 'text-emerald-400/60' : 'text-red-400/60'}`}></i>
            </div>
            <div className="text-lg font-bold text-white">
              {item.price >= 1000 ? item.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : item.price.toFixed(2)}
            </div>
            <div className={`text-sm font-semibold mt-1 ${item.change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {item.change >= 0 ? '▲' : '▼'} {item.change >= 0 ? '+' : ''}{item.change.toFixed(2)}%
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MarketOverviewSkeleton() {
  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <div className="w-5 h-5 rounded bg-gray-700 animate-pulse"></div>
        <div className="w-32 h-5 rounded bg-gray-700 animate-pulse"></div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="rounded-xl bg-[#1c1c1e] border border-white/10 p-4">
            <div className="w-16 h-3 rounded bg-gray-700 animate-pulse mb-3"></div>
            <div className="w-24 h-6 rounded bg-gray-700 animate-pulse mb-2"></div>
            <div className="w-16 h-4 rounded bg-gray-700 animate-pulse"></div>
          </div>
        ))}
      </div>
    </div>
  );
}
