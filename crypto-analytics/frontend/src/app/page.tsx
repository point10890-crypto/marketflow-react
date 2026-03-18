import Link from 'next/link';

export default function Home() {
  return (
    <div className="min-h-screen bg-black flex flex-col items-center justify-center p-8">
      {/* Hero Section */}
      <div className="text-center max-w-3xl mx-auto">
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-yellow-500/20 bg-yellow-500/5 text-sm text-yellow-400 font-medium mb-8">
          <span className="w-2 h-2 rounded-full bg-yellow-500 animate-ping"></span>
          AI-Powered Crypto Analysis
        </div>

        <h1 className="text-5xl md:text-7xl font-bold tracking-tighter text-white leading-tight mb-6">
          Crypto<span className="text-yellow-500">Analytics</span>
        </h1>

        <p className="text-xl text-gray-400 mb-12 leading-relaxed">
          VCP 패턴 스캐너 & Lead-Lag 분석<br />
          AI 기반 암호화폐 시장 분석 플랫폼
        </p>

        <Link
          href="/dashboard/crypto"
          className="inline-flex items-center gap-3 px-8 py-4 bg-yellow-500 hover:bg-yellow-500/90 text-black text-lg font-bold rounded-2xl transition-all transform hover:scale-105 shadow-lg shadow-yellow-500/25"
        >
          <i className="fab fa-bitcoin"></i>
          Enter Dashboard
        </Link>
      </div>

      {/* Features Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-20 max-w-5xl mx-auto">
        <div className="p-6 rounded-2xl bg-[#1c1c1e] border border-white/10">
          <div className="w-12 h-12 rounded-xl bg-yellow-500/10 flex items-center justify-center mb-4">
            <i className="fab fa-bitcoin text-yellow-400 text-xl"></i>
          </div>
          <h3 className="text-lg font-bold text-white mb-2">Market Briefing</h3>
          <p className="text-gray-500 text-sm">BTC/ETH 시장 현황, Fear & Greed, 펀딩비율 분석</p>
        </div>

        <div className="p-6 rounded-2xl bg-[#1c1c1e] border border-white/10">
          <div className="w-12 h-12 rounded-xl bg-orange-500/10 flex items-center justify-center mb-4">
            <i className="fas fa-chart-line text-orange-400 text-xl"></i>
          </div>
          <h3 className="text-lg font-bold text-white mb-2">VCP Signals</h3>
          <p className="text-gray-500 text-sm">암호화폐 VCP 패턴 스캐너 & 매매 시그널</p>
        </div>

        <div className="p-6 rounded-2xl bg-[#1c1c1e] border border-white/10">
          <div className="w-12 h-12 rounded-xl bg-red-500/10 flex items-center justify-center mb-4">
            <i className="fas fa-brain text-red-400 text-xl"></i>
          </div>
          <h3 className="text-lg font-bold text-white mb-2">AI Prediction</h3>
          <p className="text-gray-500 text-sm">ML 기반 가격 예측 & Lead-Lag 분석</p>
        </div>
      </div>

      {/* Footer */}
      <div className="mt-20 text-center text-gray-600 text-sm space-y-3">
        <p>Powered by Next.js + Flask API</p>
        <div className="flex items-center justify-center gap-4 text-xs">
          <Link href="/terms" className="hover:text-white transition-colors">Terms</Link>
          <span className="text-gray-700">|</span>
          <Link href="/privacy" className="hover:text-white transition-colors">Privacy</Link>
          <span className="text-gray-700">|</span>
          <Link href="/disclaimer" className="hover:text-white transition-colors">Disclaimer</Link>
          <span className="text-gray-700">|</span>
          <Link href="/pricing" className="hover:text-white transition-colors">Pricing</Link>
        </div>
      </div>
    </div>
  );
}
