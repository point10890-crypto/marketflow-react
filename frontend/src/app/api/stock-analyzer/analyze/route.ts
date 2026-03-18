import { NextRequest, NextResponse } from 'next/server';

function consensusLabel(score: number): string {
  if (score >= 4.3) return '\uc801\uadf9 \ub9e4\uc218';
  if (score >= 3.7) return '\ub9e4\uc218';
  if (score >= 2.7) return '\uc911\ub9bd';
  if (score >= 2.0) return '\ub9e4\ub3c4';
  return '\uc801\uadf9 \ub9e4\ub3c4';
}

interface YahooQuoteSummary {
  price?: {
    regularMarketPrice?: { raw?: number };
    shortName?: string;
    longName?: string;
    currency?: string;
  };
  summaryDetail?: {
    trailingPE?: { raw?: number };
    forwardPE?: { raw?: number };
    dividendYield?: { raw?: number };
    beta?: { raw?: number };
    fiftyTwoWeekHigh?: { raw?: number };
    fiftyTwoWeekLow?: { raw?: number };
    marketCap?: { raw?: number };
  };
  defaultKeyStatistics?: {
    profitMargins?: { raw?: number };
  };
  recommendationTrend?: {
    trend?: Array<{
      strongBuy?: number; buy?: number; hold?: number; sell?: number; strongSell?: number;
      period?: string;
    }>;
  };
  financialData?: {
    targetHighPrice?: { raw?: number };
    targetLowPrice?: { raw?: number };
    targetMeanPrice?: { raw?: number };
    targetMedianPrice?: { raw?: number };
    currentPrice?: { raw?: number };
    totalRevenue?: { raw?: number };
    revenueGrowth?: { raw?: number };
  };
}

// Yahoo Finance requires cookie + crumb authentication
let _cachedCrumb: { crumb: string; cookie: string; ts: number } | null = null;

async function getYahooCrumb(): Promise<{ crumb: string; cookie: string }> {
  // Cache for 30 minutes
  if (_cachedCrumb && Date.now() - _cachedCrumb.ts < 1800000) {
    return _cachedCrumb;
  }

  const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

  // Step 1: Get consent cookie
  const consentResp = await fetch('https://fc.yahoo.com/cubed/api/v1/mrt/asset', {
    headers: { 'User-Agent': UA },
    redirect: 'manual',
  });
  const setCookies = consentResp.headers.getSetCookie?.() || [];
  const cookieStr = setCookies.map(c => c.split(';')[0]).join('; ');

  // Step 2: Get crumb
  const crumbResp = await fetch('https://query2.finance.yahoo.com/v1/test/getcrumb', {
    headers: { 'User-Agent': UA, 'Cookie': cookieStr },
  });
  const crumb = await crumbResp.text();

  if (!crumb || crumb.length > 50) {
    throw new Error('Failed to get Yahoo crumb');
  }

  _cachedCrumb = { crumb, cookie: cookieStr, ts: Date.now() };
  return _cachedCrumb;
}

async function fetchYahooData(ticker: string): Promise<YahooQuoteSummary> {
  const { crumb, cookie } = await getYahooCrumb();
  const modules = 'price,summaryDetail,defaultKeyStatistics,recommendationTrend,financialData';
  const url = `https://query2.finance.yahoo.com/v10/finance/quoteSummary/${encodeURIComponent(ticker)}?modules=${modules}&crumb=${encodeURIComponent(crumb)}`;

  const resp = await fetch(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Cookie': cookie,
    },
    signal: AbortSignal.timeout(15000),
  });

  if (!resp.ok) throw new Error(`Yahoo API ${resp.status}`);
  const data = await resp.json();
  return data?.quoteSummary?.result?.[0] || {};
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const ticker = (body.ticker || '').trim();
    const name = body.name || ticker;

    if (!ticker) {
      return NextResponse.json({ error: '\ud2f0\ucee4\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.' }, { status: 400 });
    }

    const start = Date.now();
    const yahoo = await fetchYahooData(ticker);

    const price = yahoo.price;
    const summary = yahoo.summaryDetail;
    const keyStats = yahoo.defaultKeyStatistics;
    const financial = yahoo.financialData;
    const recTrend = yahoo.recommendationTrend?.trend;

    const currentPrice = price?.regularMarketPrice?.raw
      || financial?.currentPrice?.raw
      || null;

    // Key stats
    const stats = {
      name: price?.shortName || price?.longName || name,
      sector: '',
      industry: '',
      market_cap: summary?.marketCap?.raw || null,
      pe_ratio: summary?.trailingPE?.raw || null,
      forward_pe: summary?.forwardPE?.raw || null,
      dividend_yield: summary?.dividendYield?.raw || null,
      beta: summary?.beta?.raw || null,
      fifty_two_week_high: summary?.fiftyTwoWeekHigh?.raw || null,
      fifty_two_week_low: summary?.fiftyTwoWeekLow?.raw || null,
      revenue: financial?.totalRevenue?.raw || null,
      profit_margin: keyStats?.profitMargins?.raw || null,
      currency: price?.currency || (ticker.includes('.K') ? 'KRW' : 'USD'),
    };

    // Recommendation detail
    let recommendation: string | null = null;
    let consensusScore: number | null = null;
    let analystCount = 0;
    let recommendationDetail: Record<string, number> | null = null;

    if (recTrend && recTrend.length > 0) {
      // Use the "0m" (current month) period
      const current = recTrend.find(t => t.period === '0m') || recTrend[0];
      const detail = {
        strongBuy: current.strongBuy || 0,
        buy: current.buy || 0,
        hold: current.hold || 0,
        sell: current.sell || 0,
        strongSell: current.strongSell || 0,
      };
      recommendationDetail = detail;
      const total = Object.values(detail).reduce((a, b) => a + b, 0);
      if (total > 0) {
        const score = (detail.strongBuy * 5 + detail.buy * 4 + detail.hold * 3 + detail.sell * 2 + detail.strongSell * 1) / total;
        consensusScore = Math.round(score * 100) / 100;
        analystCount = total;
        recommendation = consensusLabel(score);
      }
    }

    // Price targets
    let priceTargets: Record<string, number | null> | null = null;
    let upsidePotential: number | null = null;
    if (financial?.targetMeanPrice?.raw) {
      priceTargets = {
        current: currentPrice,
        high: financial.targetHighPrice?.raw || null,
        low: financial.targetLowPrice?.raw || null,
        mean: financial.targetMeanPrice?.raw || null,
        median: financial.targetMedianPrice?.raw || null,
      };
      if (currentPrice && financial.targetMeanPrice.raw) {
        upsidePotential = Math.round(((financial.targetMeanPrice.raw - currentPrice) / currentPrice) * 1000) / 10;
      }
    }

    if (!recommendation && !currentPrice) {
      return NextResponse.json({
        error: `${name} (${ticker}) \u2014 \ub370\uc774\ud130\ub97c \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.`,
        name,
      }, { status: 404 });
    }

    const elapsed = Math.round((Date.now() - start) / 100) / 10;
    const now = new Date().toISOString().replace('T', ' ').slice(0, 19);

    return NextResponse.json({
      name,
      ticker,
      result: recommendation || '\ub370\uc774\ud130 \uc5c6\uc74c',
      date: now,
      elapsed,
      consensus_score: consensusScore,
      analyst_count: analystCount,
      recommendation_detail: recommendationDetail,
      price_targets: priceTargets,
      current_price: currentPrice,
      upside_potential: upsidePotential,
      key_stats: stats,
      source: 'yahoo-finance',
    });
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    return NextResponse.json({ error: `\ubd84\uc11d \uc2e4\ud328: ${msg.slice(0, 200)}`, name: '' }, { status: 500 });
  }
}
