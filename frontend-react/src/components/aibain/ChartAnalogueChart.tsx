import { useId } from 'react';
import type { ChartAnaloguePrediction } from '@/lib/chartAnalogueApi';

export const formatAnaloguePrice = (price: number | undefined) =>
    typeof price === 'number' && Number.isFinite(price) ? `${price.toLocaleString('ko-KR', { maximumFractionDigits: 0 })}원` : '—';
export const formatAnalogueReturn = (value: number | undefined) =>
    typeof value === 'number' && Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(1)}%` : '—';

/** Fixed-height SVG uses observed session positions, never calendar-date interpolation. */
export default function ChartAnalogueChart({ data }: { data: ChartAnaloguePrediction }) {
    const titleId = useId();
    const descId = useId();
    const { history, fan } = data;
    const prices = [...history.map(row => row.close), ...fan.flatMap(row => [row.p10_price, row.p90_price])];
    const low = Math.min(...prices);
    const high = Math.max(...prices);
    const padding = Math.max((high - low) * 0.08, high * 0.005);
    const bottom = low - padding;
    const top = high + padding;
    const lastHistory = history.length - 1;
    const maxSession = lastHistory + Math.max(...fan.map(row => row.session));
    const x = (session: number) => (session / maxSession) * 1000;
    const y = (price: number) => 300 - ((price - bottom) / (top - bottom)) * 300;
    const point = (session: number, price: number) => `${x(session).toFixed(2)},${y(price).toFixed(2)}`;
    const historyPoints = history.map((row, index) => point(index, row.close)).join(' ');
    const medianPoints = fan.map(row => point(lastHistory + row.session, row.median_price)).join(' ');
    const bandPoints = [
        ...fan.map(row => point(lastHistory + row.session, row.p90_price)),
        ...[...fan].reverse().map(row => point(lastHistory + row.session, row.p10_price)),
    ].join(' ');
    const ticks = [0, 1, 2, 3, 4].map(i => top - (i / 4) * (top - bottom));

    return (
        <figure className="min-w-0">
            <div className="mb-4 flex flex-wrap gap-x-4 gap-y-2 text-xs text-gray-300" aria-hidden="true">
                <span><span className="mr-1.5 inline-block h-0.5 w-4 bg-[#acd3ff] align-middle" />과거 종가</span>
                <span><span className="mr-1.5 inline-block h-0.5 w-4 bg-teal-300 align-middle" />유사 사례 중앙값</span>
                <span><span className="mr-1.5 inline-block h-2 w-4 bg-teal-400/20 align-middle" />10~90백분위</span>
                <span>기준선 {history[lastHistory].date}</span>
            </div>
            <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
                <div className="relative h-[300px] text-right font-mono text-[10px] tabular-nums text-gray-400" aria-hidden="true">
                    {ticks.map((price, i) => <span key={i} className="absolute right-0" style={{ top: `${i * 25}%`, transform: `translateY(${i === 0 ? 0 : i === 4 ? -100 : -50}%)` }}>
                        {formatAnaloguePrice(price)}
                    </span>)}
                </div>
                <svg role="img" aria-labelledby={`${titleId} ${descId}`} viewBox="0 0 1000 300" preserveAspectRatio="none" className="h-[300px] w-full overflow-visible">
                    <title id={titleId}>{data.target} 과거 종가와 유사 사례의 관측 분포</title>
                    <desc id={descId}>가로축은 관측 거래일, 세로축은 원 단위 가격입니다. 실선은 과거 종가, 점선은 유사 사례 중앙값, 음영은 10~90백분위입니다. 차트 수치 보기에서 원본 값을 확인할 수 있습니다.</desc>
                    {ticks.map((price, i) => <line key={i} x1="0" x2="1000" y1={y(price)} y2={y(price)} stroke="#30363f" strokeWidth="1" vectorEffect="non-scaling-stroke" />)}
                    <line x1={x(lastHistory)} x2={x(lastHistory)} y1="0" y2="300" stroke="#7a8593" strokeDasharray="4 5" vectorEffect="non-scaling-stroke" />
                    <polygon data-series="fan-band" points={bandPoints} fill="#2dd4bf" fillOpacity="0.16" />
                    <polyline data-series="history" points={historyPoints} fill="none" stroke="#acd3ff" strokeWidth="2" vectorEffect="non-scaling-stroke" />
                    <polyline data-series="median" points={medianPoints} fill="none" stroke="#5eead4" strokeWidth="2" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />
                </svg>
                <div />
                <div className="flex justify-between gap-2 text-[10px] tabular-nums text-gray-400" aria-hidden="true">
                    <span>{history[0].date}</span><span>+40관측일</span>
                </div>
            </div>
            <figcaption className="mt-3 text-xs leading-relaxed text-gray-400">음영은 과거 사례의 분포이며 미래 가격의 보장 구간이 아닙니다. 현재 기준 종가로 환산했습니다.</figcaption>
            <details className="mt-4 border-t border-[#30363f] pt-3">
                <summary className="w-fit cursor-pointer text-xs font-medium text-[#acd3ff]">차트 수치 보기</summary>
                <div className="mt-3 max-h-72 overflow-auto rounded-lg border border-[#30363f]" tabIndex={0}>
                    <table aria-label="차트의 원본 수치" className="w-full min-w-[470px] text-right text-xs tabular-nums">
                        <thead className="sticky top-0 bg-[#1b2129] text-gray-400"><tr><th className="p-2 text-left">일자 / 거래일</th><th className="p-2">종가 / 중앙값</th><th className="p-2">10백분위</th><th className="p-2">90백분위</th></tr></thead>
                        <tbody>{history.map(row => <tr key={row.date} className="border-t border-[#30363f]"><th className="p-2 text-left font-normal">{row.date}</th><td className="p-2">{formatAnaloguePrice(row.close)}</td><td className="p-2">—</td><td className="p-2">—</td></tr>)}
                            {fan.map(row => <tr key={`fan-${row.session}`} className="border-t border-[#30363f] text-teal-200"><th className="p-2 text-left font-normal">+{row.session}거래일 · 유사 사례</th><td className="p-2">{formatAnaloguePrice(row.median_price)}</td><td className="p-2">{formatAnaloguePrice(row.p10_price)}</td><td className="p-2">{formatAnaloguePrice(row.p90_price)}</td></tr>)}</tbody>
                    </table>
                </div>
            </details>
        </figure>
    );
}
