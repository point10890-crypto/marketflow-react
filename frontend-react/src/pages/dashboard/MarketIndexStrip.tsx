/**
 * 주요 시장 지수 — 데이터 변화에 반응하는 지수 스트립.
 *
 * 요약 화면은 "조용한 표면, 읽히는 데이터" 원칙을 따른다. 그래서 장식용 반복
 * 애니메이션 대신 값이 실제로 바뀔 때만 움직인다:
 *   - 진입: 타일이 순서대로 떠오른다(stagger)
 *   - 갱신: 이전 값 → 새 값 카운트업 + 상승/하락 틱 플래시
 *   - 크기: 등락폭에 비례해 차오르는 게이지
 * 상시 움직임은 제목 옆 LIVE 펄스 하나뿐이다.
 * prefers-reduced-motion 이면 CSS·JS 모두 즉시 최종 값으로 렌더한다.
 */
import { useEffect, useRef, useState } from 'react';
import type { MarketIndexItem } from '@/lib/api';

/** 게이지가 가득 차는 등락폭(%). 지수 하루 변동 3%면 큰 움직임이다. */
const BAR_CAP_PCT = 3;
const BAR_MIN_PCT = 4;
const COUNT_MS = 700;
const TICK_MS = 1200;

export function parsePrice(raw: string): { value: number; decimals: number } | null {
    const text = String(raw ?? '').replace(/,/g, '').trim();
    if (!/^-?\d+(\.\d+)?$/.test(text)) return null;
    const dot = text.indexOf('.');
    return { value: Number(text), decimals: dot < 0 ? 0 : text.length - dot - 1 };
}

export function formatPrice(value: number, decimals: number): string {
    return value.toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

export function changeBarPct(changePct: number): number {
    const pct = (Math.abs(Number(changePct) || 0) / BAR_CAP_PCT) * 100;
    return Math.min(100, Math.max(BAR_MIN_PCT, pct));
}

function prefersReducedMotion(): boolean {
    try {
        return typeof window !== 'undefined'
            && typeof window.matchMedia === 'function'
            && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch {
        return false;
    }
}

/** 값이 바뀌면 이전 값에서 새 값까지 easeOutCubic 으로 따라간다. */
function useCountUp(target: number | null): number | null {
    const [shown, setShown] = useState<number | null>(target);
    const fromRef = useRef<number | null>(target);

    useEffect(() => {
        const from = fromRef.current;
        fromRef.current = target;
        if (target == null || from == null || from === target || prefersReducedMotion()
            || typeof window.requestAnimationFrame !== 'function') {
            setShown(target);
            return undefined;
        }

        let frame = 0;
        const start = performance.now();
        const step = (now: number) => {
            const t = Math.min(1, (now - start) / COUNT_MS);
            const eased = 1 - (1 - t) ** 3;
            setShown(from + (target - from) * eased);
            if (t < 1) frame = window.requestAnimationFrame(step);
        };
        frame = window.requestAnimationFrame(step);
        return () => {
            window.cancelAnimationFrame(frame);
            setShown(target);
        };
    }, [target]);

    return shown;
}

function IndexTile({ idx, order }: { idx: MarketIndexItem; order: number }) {
    const parsed = parsePrice(idx.price);
    const shown = useCountUp(parsed?.value ?? null);
    const prevRef = useRef<number | null>(parsed?.value ?? null);
    const [tick, setTick] = useState<'up' | 'down' | null>(null);

    useEffect(() => {
        const prev = prevRef.current;
        const next = parsed?.value ?? null;
        prevRef.current = next;
        if (prev == null || next == null || prev === next) return undefined;
        setTick(next > prev ? 'up' : 'down');
        const timer = setTimeout(() => setTick(null), TICK_MS);
        return () => clearTimeout(timer);
    }, [parsed?.value]);

    const up = idx.change_pct >= 0;
    const priceText = parsed && shown != null ? formatPrice(shown, parsed.decimals) : idx.price;

    return (
        <div
            data-testid="market-index-tile"
            data-tick={tick ?? undefined}
            className="summary-index"
            style={{ '--i': String(order) } as React.CSSProperties}
        >
            <span className="summary-index-label">{idx.name}</span>
            <strong className="summary-index-price">{priceText}</strong>
            <span className={`summary-index-change text-xs font-semibold tabular-nums ${up ? 'text-emerald-400' : 'text-red-400'}`}>
                <span className="summary-index-arrow" aria-hidden="true">{up ? '▲' : '▼'}</span>
                {' '}{up ? '+' : ''}{idx.change_pct.toFixed(2)}%
            </span>
            <span className="summary-index-track" aria-hidden="true">
                <span
                    data-testid="market-index-bar"
                    className={`summary-index-bar ${up ? 'is-up' : 'is-down'}`}
                    style={{ width: `${changeBarPct(idx.change_pct)}%` }}
                />
            </span>
        </div>
    );
}

export default function MarketIndexStrip({ indices }: { indices: MarketIndexItem[] }) {
    return (
        <section className="summary-indices hidden md:block" aria-label="주요 시장 지수">
            <h2 className="summary-section-heading summary-indices-heading">
                주요 시장 지수
                <span className="summary-live">
                    <span className="summary-live-dot" aria-hidden="true" />
                    LIVE
                </span>
            </h2>
            {indices.length > 0 && (
                <div className="summary-index-grid">
                    {indices.map((idx, i) => (
                        <IndexTile key={idx.name} idx={idx} order={i} />
                    ))}
                </div>
            )}
        </section>
    );
}
