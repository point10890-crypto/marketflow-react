import { NextRequest, NextResponse } from 'next/server';
import krStocks from '@/data/kr-stocks.json';

// [ticker, english_name, korean_name]
const US_POPULAR: [string, string, string][] = [
  ['AAPL', 'Apple', '애플'], ['MSFT', 'Microsoft', '마이크로소프트'], ['GOOGL', 'Alphabet', '알파벳/구글'],
  ['AMZN', 'Amazon', '아마존'], ['NVDA', 'NVIDIA', '엔비디아'], ['META', 'Meta Platforms', '메타'],
  ['TSLA', 'Tesla', '테슬라'], ['BRK-B', 'Berkshire Hathaway', '버크셔해서웨이'], ['JPM', 'JPMorgan Chase', 'JP모건'],
  ['V', 'Visa', '비자'], ['UNH', 'UnitedHealth', '유나이티드헬스'], ['MA', 'Mastercard', '마스터카드'],
  ['HD', 'Home Depot', '홈디포'], ['PG', 'Procter & Gamble', 'P&G/프록터앤갬블'], ['JNJ', 'Johnson & Johnson', '존슨앤존슨'],
  ['COST', 'Costco', '코스트코'], ['ABBV', 'AbbVie', '애브비'], ['CRM', 'Salesforce', '세일즈포스'],
  ['MRK', 'Merck', '머크'], ['AVGO', 'Broadcom', '브로드컴'], ['KO', 'Coca-Cola', '코카콜라'],
  ['PEP', 'PepsiCo', '펩시코'], ['TMO', 'Thermo Fisher', '써모피셔'], ['AMD', 'AMD', 'AMD'],
  ['NFLX', 'Netflix', '넷플릭스'], ['ADBE', 'Adobe', '어도비'], ['DIS', 'Disney', '디즈니'],
  ['INTC', 'Intel', '인텔'], ['QCOM', 'Qualcomm', '퀄컴'], ['CSCO', 'Cisco', '시스코'],
  ['BA', 'Boeing', '보잉'], ['GS', 'Goldman Sachs', '골드만삭스'], ['CAT', 'Caterpillar', '캐터필러'],
  ['IBM', 'IBM', 'IBM'], ['GE', 'GE Aerospace', 'GE/제너럴일렉트릭'], ['UBER', 'Uber', '우버'],
  ['PLTR', 'Palantir', '팔란티어'], ['COIN', 'Coinbase', '코인베이스'], ['MSTR', 'MicroStrategy', '마이크로스트래티지'],
  ['ARM', 'ARM Holdings', 'ARM/에이알엠'], ['SMCI', 'Super Micro', '슈퍼마이크로'], ['MU', 'Micron', '마이크론'],
  ['SNOW', 'Snowflake', '스노우플레이크'], ['PANW', 'Palo Alto Networks', '팔로알토'], ['CRWD', 'CrowdStrike', '크라우드스트라이크'],
  ['SQ', 'Block', '블록/스퀘어'], ['SHOP', 'Shopify', '쇼피파이'], ['ROKU', 'Roku', '로쿠'],
  ['SOFI', 'SoFi', '소파이'], ['RIVN', 'Rivian', '리비안'],
];

export async function GET(request: NextRequest) {
  const q = (request.nextUrl.searchParams.get('q') || '').trim().toLowerCase();
  const market = (request.nextUrl.searchParams.get('market') || 'all').trim().toLowerCase();

  if (!q) return NextResponse.json([]);

  const results: Array<{ name: string; name_kr?: string; ticker: string; code: string; market: string; type: string }> = [];

  // 1) KR stocks
  if ((market === 'kr' || market === 'all') && results.length < 20) {
    for (const s of krStocks as Array<{ t: string; y: string; n: string; m: string }>) {
      if (s.n.toLowerCase().includes(q) || s.t.toLowerCase().includes(q) || s.y.toLowerCase().includes(q)) {
        results.push({ name: s.n, ticker: s.y, code: s.t, market: s.m, type: 'KR' });
        if (results.length >= 20) break;
      }
    }
  }

  // 2) US popular stocks (영문명 + 한글명 매칭)
  if ((market === 'us' || market === 'all') && results.length < 20) {
    for (const [ticker, name, nameKr] of US_POPULAR) {
      if (ticker.toLowerCase().includes(q) || name.toLowerCase().includes(q) || nameKr.toLowerCase().includes(q)) {
        results.push({ name, name_kr: nameKr, ticker, code: ticker, market: 'US', type: 'US' });
        if (results.length >= 20) break;
      }
    }
  }

  // 3) Direct US ticker input (영문 only)
  if (results.length === 0 && /^[a-zA-Z]{1,5}$/.test(q)) {
    results.push({ name: q.toUpperCase(), ticker: q.toUpperCase(), code: q.toUpperCase(), market: 'US', type: 'US_DIRECT' });
  }

  return NextResponse.json(results);
}
