# PART9: 프론트엔드 (dashboard.html)

## 핵심 구조

> ⚠️ 실제 dashboard.html은 5000줄 이상입니다.
> 완전한 파일: `/Users/seoheun/Documents/국내주식/templates/dashboard.html`

---

## HTML 기본 구조

```html
<!DOCTYPE html>
<html lang="ko" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Market Analysis</title>
    
    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    
    <!-- Font Awesome -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    
    <!-- Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    
    <style>
        /* Dark Theme */
        body {
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
            min-height: 100vh;
        }
        
        /* Glassmorphism */
        .glass-card {
            background: rgba(255, 255, 255, 0.03);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow: 
                0 4px 24px -1px rgba(0, 0, 0, 0.2),
                inset 0 1px 0 rgba(255, 255, 255, 0.05);
        }
        
        .glass-card:hover {
            background: rgba(255, 255, 255, 0.06);
            border-color: rgba(255, 255, 255, 0.08);
            transform: translateY(-2px);
            transition: all 0.3s ease;
        }
        
        /* Gradient Text */
        .gradient-text {
            background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        /* Animations */
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }
        
        .live-indicator {
            animation: pulse 2s infinite;
        }
    </style>
</head>
<body class="text-white font-sans antialiased">
    <div id="app" class="min-h-screen">
        <!-- Header -->
        <header class="sticky top-0 z-50 glass-card border-b border-white/5">
            <div class="container mx-auto px-6 py-4 flex items-center justify-between">
                <h1 class="text-2xl font-bold gradient-text">
                    🪙 Crypto Analysis
                </h1>
                <div class="text-sm text-gray-400" id="last-update"></div>
            </div>
        </header>
        
        <!-- Main Content -->
        <main class="container mx-auto px-6 py-8 space-y-8">
            <!-- Market Gate Section -->
            <section id="market-gate-section"></section>
            
            <!-- Lead-Lag Section -->
            <section id="lead-lag-section"></section>
            
            <!-- VCP Signals Section -->
            <section id="vcp-signals-section"></section>
        </main>
    </div>
    
    <script>
        // JavaScript (아래 코드 참조)
    </script>
</body>
</html>
```

---

## JavaScript 핵심 로직

```javascript
const CryptoApp = {
    // Market Gate 로딩
    async loadMarketGate() {
        const container = document.getElementById('market-gate-section');
        
        try {
            const res = await fetch('/api/crypto/market-gate');
            const data = await res.json();
            
            if (data.error) {
                container.innerHTML = `<div class="text-red-400">${data.error}</div>`;
                return;
            }
            
            const gateColor = data.gate_color === 'GREEN' ? '#10b981' :
                              data.gate_color === 'YELLOW' ? '#f59e0b' : '#ef4444';
            
            container.innerHTML = `
                <div class="glass-card rounded-3xl p-8">
                    <div class="flex items-center justify-between mb-8">
                        <div>
                            <h2 class="text-3xl font-black">Market Gate Analysis</h2>
                            <p class="text-gray-500 text-sm mt-1">${data.summary}</p>
                        </div>
                        
                        <!-- Gauge -->
                        <div class="relative w-32 h-32">
                            <svg class="w-full h-full -rotate-90">
                                <circle cx="64" cy="64" r="56" fill="none" 
                                        stroke="rgba(255,255,255,0.05)" stroke-width="8"/>
                                <circle cx="64" cy="64" r="56" fill="none" 
                                        stroke="${gateColor}" stroke-width="8" stroke-linecap="round"
                                        stroke-dasharray="352" 
                                        stroke-dashoffset="${352 * (1 - data.score / 100)}"
                                        style="transition: stroke-dashoffset 1s ease-out"/>
                            </svg>
                            <div class="absolute inset-0 flex flex-col items-center justify-center">
                                <span class="text-4xl font-black">${data.score}</span>
                                <span class="text-xs font-bold px-2 py-0.5 rounded-full" 
                                      style="background: ${gateColor}20; color: ${gateColor}">
                                    ${data.gate_color}
                                </span>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Indicators Grid -->
                    <div class="grid grid-cols-1 md:grid-cols-3 gap-6" id="gate-indicators">
                        ${this.renderIndicators(data.indicators)}
                    </div>
                </div>
            `;
        } catch (e) {
            container.innerHTML = `<div class="text-red-400">Error: ${e.message}</div>`;
        }
    },
    
    renderIndicators(indicators) {
        const categories = {
            trend: { title: 'Trend & Momentum', items: ['btc_price', 'btc_ema50', 'btc_ema200', 'btc_ema200_slope_pct_20'] },
            volatility: { title: 'Volatility & Risk', items: ['btc_atrp_14_pct', 'btc_volume_z_50'] },
            health: { title: 'Market Health', items: ['fear_greed_index', 'alt_breadth_above_ema50', 'funding_rate'] }
        };
        
        return Object.entries(categories).map(([key, cat]) => {
            const catIndicators = indicators.filter(i => cat.items.includes(i.name));
            const bullish = catIndicators.filter(i => i.signal === 'Bullish').length;
            const pct = Math.round((bullish / catIndicators.length) * 100) || 0;
            
            return `
                <div class="glass-card rounded-2xl p-5">
                    <div class="flex justify-between items-center mb-4">
                        <h3 class="font-bold">${cat.title}</h3>
                        <span class="${pct > 50 ? 'text-emerald-400' : 'text-rose-400'}">${pct}%</span>
                    </div>
                    <div class="h-2 bg-gray-800 rounded-full overflow-hidden mb-4">
                        <div class="h-full ${pct > 50 ? 'bg-emerald-500' : 'bg-rose-500'}" 
                             style="width: ${pct}%"></div>
                    </div>
                    <div class="space-y-2 text-sm">
                        ${catIndicators.map(ind => `
                            <div class="flex justify-between">
                                <span class="text-gray-400">${ind.name}</span>
                                <span class="${ind.signal === 'Bullish' ? 'text-emerald-400' : 
                                               ind.signal === 'Bearish' ? 'text-rose-400' : 'text-gray-400'}">
                                    ${typeof ind.value === 'number' ? ind.value.toFixed(2) : ind.value || 'N/A'}
                                </span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }).join('');
    },
    
    // Lead-Lag 로딩
    async loadLeadLag() {
        const container = document.getElementById('lead-lag-section');
        
        try {
            const res = await fetch('/api/crypto/lead-lag');
            const data = await res.json();
            
            if (data.error) {
                container.innerHTML = `<div class="text-red-400">${data.error}</div>`;
                return;
            }
            
            const varMap = {
                'TNX': '🇺🇸 10년물 국채',
                'TNX_MoM': '🇺🇸 10년물 국채 (MoM)',
                'SPY': '🇺🇸 S&P 500',
                'SPY_MoM': '🇺🇸 S&P 500 (MoM)',
                'VIX': '🫣 공포지수',
                'VIX_MoM': '🫣 공포지수 (MoM)',
                'DXY': '💵 달러 인덱스',
                'DXY_MoM': '💵 달러 인덱스 (MoM)',
                'GOLD': '🥇 금',
                'GOLD_MoM': '🥇 금 (MoM)',
            };
            
            container.innerHTML = `
                <div class="glass-card rounded-3xl p-8">
                    <div class="flex items-center justify-between mb-6">
                        <div>
                            <h2 class="text-2xl font-bold">Lead-Lag Analytics</h2>
                            <p class="text-gray-500 text-sm">비트코인 선행 지표 분석 (Granger Causality)</p>
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
                        ${data.leading_indicators.slice(0, 6).map(item => {
                            const niceName = varMap[item.variable] || item.variable;
                            const isInverse = item.correlation < 0;
                            const strength = Math.abs(item.correlation) * 100;
                            
                            return `
                                <div class="glass-card rounded-2xl p-5">
                                    <div class="flex items-center gap-3 mb-4">
                                        <div class="w-10 h-10 rounded-full bg-gray-800 flex items-center justify-center text-xs font-bold">
                                            ${item.lag}일
                                        </div>
                                        <div>
                                            <div class="font-bold">${niceName}</div>
                                            <div class="text-xs text-gray-500">${item.variable}</div>
                                        </div>
                                    </div>
                                    <div class="mb-3">
                                        <div class="flex justify-between text-xs mb-1">
                                            <span class="text-gray-500">상관관계</span>
                                            <span class="${isInverse ? 'text-rose-400' : 'text-emerald-400'}">
                                                ${strength.toFixed(1)}%
                                            </span>
                                        </div>
                                        <div class="h-2 bg-gray-800 rounded-full overflow-hidden">
                                            <div class="h-full ${isInverse ? 'bg-rose-500' : 'bg-emerald-500'}" 
                                                 style="width: ${strength}%"></div>
                                        </div>
                                    </div>
                                    <div class="text-xs text-gray-400 bg-black/20 rounded-lg p-2">
                                        ${isInverse ? '📉 지표 ↑ → 비트코인 ↓' : '📈 지표 ↑ → 비트코인 ↑'}
                                    </div>
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
            `;
        } catch (e) {
            container.innerHTML = `<div class="text-red-400">Error: ${e.message}</div>`;
        }
    },
    
    // 초기화
    init() {
        this.loadMarketGate();
        this.loadLeadLag();
        
        // 10분마다 자동 갱신
        setInterval(() => {
            this.loadMarketGate();
            this.loadLeadLag();
        }, 10 * 60 * 1000);
        
        // 마지막 업데이트 시간
        document.getElementById('last-update').textContent = 
            `Last Updated: ${new Date().toLocaleTimeString('ko-KR')}`;
    }
};

document.addEventListener('DOMContentLoaded', () => CryptoApp.init());
```

---

## 디자인 시스템

### Glassmorphism
```css
.glass-card {
    background: rgba(255, 255, 255, 0.03);
    backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.05);
}
```

### 색상 팔레트
| 용도 | 색상 |
|------|------|
| Bullish | `#10b981` (emerald-500) |
| Bearish | `#ef4444` (rose-500) |
| Neutral | `#6b7280` (gray-500) |
| Background | `#0a0a0a → #1a1a2e` |
