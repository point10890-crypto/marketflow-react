/**
 * RAG 지식베이스 현황 — 검색 계층이 지금 무엇을 알고 있는지.
 *
 * 판단 화면이 조회 전에는 비어 있어 시스템이 아무것도 모르는 것처럼 보였다.
 * 지식그래프 규모·뉴스 수집량·종목 커버리지·신선도를 조회 전에도 보여준다.
 * 읽기전용이며 수집을 트리거하지 않는다.
 */
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { fetchAuthAPI } from '@/lib/api';

const ENDPOINT = '/api/kr/rag/status';

interface RagStatus {
    graph: {
        entities: number;
        relations: number;
        entity_types: Record<string, number>;
        top_relations: { relation: string; count: number }[];
        updated_at: string | null;
    };
    news: {
        total: number;
        last_24h: number;
        last_collected_at: string | null;
        by_grade: Record<string, number>;
        by_source: Record<string, number>;
        stale: boolean;
    };
    coverage: { symbols: number; top_symbols: { symbol: string; count: number }[] };
    errors: Record<string, string>;
}

const TYPE_LABEL: Record<string, string> = {
    company: '기업', metric: '지표', event: '이벤트', asset: '자산', sector: '섹터',
    risk: '리스크', policy: '정책', country: '국가', person: '인물', index: '지수',
    product: '제품', investor: '투자자', signal: '시그널', entity: '기타',
};

const RELATION_LABEL: Record<string, string> = {
    related_to: '연관', impacts: '영향', mentions: '언급', produces: '생산',
    competes_with: '경쟁', supplies: '공급', owns: '보유',
};

function isRagStatus(v: unknown): v is RagStatus {
    const o = v as Partial<RagStatus> | null;
    return !!o && typeof o === 'object' && !!o.graph && !!o.news && !!o.coverage;
}

function fmtAge(ts: string | null): string {
    if (!ts) return '수집 이력 없음';
    const ms = Date.now() - Date.parse(ts);
    if (!Number.isFinite(ms) || ms < 0) return '-';
    const min = Math.round(ms / 60000);
    if (min < 60) return `${Math.max(1, min)}분 전`;
    const hr = Math.round(min / 60);
    return hr < 48 ? `${hr}시간 전` : `${Math.round(hr / 24)}일 전`;
}

export default function RagStatusCard() {
    const { token } = useAuth();
    const [data, setData] = useState<RagStatus | null>(null);
    const [failed, setFailed] = useState(false);

    const load = useCallback(async () => {
        try {
            const res = await fetchAuthAPI<unknown>(ENDPOINT, token ?? undefined);
            if (isRagStatus(res)) { setData(res); setFailed(false); } else { setFailed(true); }
        } catch {
            setFailed(true);
        }
    }, [token]);

    useEffect(() => { void load(); }, [load]);

    if (!data) {
        return (
            <section className="rounded-2xl border border-white/[0.06] bg-[#13151f] p-5">
                <Header />
                <p className="text-sm text-gray-500">
                    {failed ? '지식베이스 현황을 불러오지 못했습니다' : '불러오는 중...'}
                </p>
            </section>
        );
    }

    const { graph, news, coverage } = data;
    const types = Object.entries(graph.entity_types)
        .sort((a, b) => b[1] - a[1]).slice(0, 6);
    const maxType = types.length ? types[0][1] : 1;
    const sources = Object.entries(news.by_source).sort((a, b) => b[1] - a[1]).slice(0, 4);

    return (
        <section className="rounded-2xl border border-white/[0.06] bg-[#13151f] p-5">
            <Header />

            <div className="grid gap-3 sm:grid-cols-3">
                <Metric label="지식그래프" value={graph.entities.toLocaleString('ko-KR')}
                    unit="엔티티" sub={`관계 ${graph.relations.toLocaleString('ko-KR')}`} />
                <Metric label="수집 사건" value={news.total.toLocaleString('ko-KR')}
                    unit="건" sub={`최근 24시간 ${news.last_24h}`}
                    warn={news.stale} />
                <Metric label="종목 커버리지" value={coverage.symbols.toLocaleString('ko-KR')}
                    unit="종목" sub={`최근 수집 ${fmtAge(news.last_collected_at)}`} />
            </div>

            {/* 그래프 구성 */}
            {types.length > 0 && (
                <div className="mt-4">
                    <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">
                        그래프 구성
                    </div>
                    <ul className="space-y-1.5">
                        {types.map(([type, count]) => (
                            <li key={type} className="flex items-center gap-3">
                                <span className="w-14 shrink-0 text-[12px] text-gray-400">
                                    {TYPE_LABEL[type] ?? type}
                                </span>
                                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.05]">
                                    <span className="block h-full rounded-full bg-teal-400/60"
                                        style={{ width: `${Math.max(3, (count / maxType) * 100)}%` }} />
                                </span>
                                <span className="w-10 shrink-0 text-right font-mono text-[11.5px] tabular-nums text-gray-500">
                                    {count}
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {/* 관계 유형 + 수집 소스 */}
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {graph.top_relations.length > 0 && (
                    <div>
                        <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">
                            관계 유형
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                            {graph.top_relations.map((r) => (
                                <span key={r.relation}
                                    className="rounded-lg bg-white/[0.05] px-2 py-1 text-[11.5px] text-gray-300">
                                    {RELATION_LABEL[r.relation] ?? r.relation}
                                    <b className="ml-1.5 font-mono text-[11px] text-gray-500">{r.count}</b>
                                </span>
                            ))}
                        </div>
                    </div>
                )}

                <div>
                    <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">
                        수집 소스
                    </div>
                    {sources.length === 0 ? (
                        <p className="text-[12px] text-gray-600">
                            아직 수집된 뉴스가 없습니다 — 15분 주기 센서가 채웁니다
                        </p>
                    ) : (
                        <div className="flex flex-wrap gap-1.5">
                            {sources.map(([name, count]) => (
                                <span key={name}
                                    className="rounded-lg bg-white/[0.05] px-2 py-1 text-[11.5px] text-gray-300">
                                    {name}
                                    <b className="ml-1.5 font-mono text-[11px] text-gray-500">{count}</b>
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* 최다 언급 종목 */}
            {coverage.top_symbols.length > 0 && (
                <div className="mt-4 border-t border-white/[0.06] pt-3">
                    <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-gray-500">
                        최근 언급 상위
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                        {coverage.top_symbols.map((s) => (
                            <span key={s.symbol}
                                className="rounded-lg border border-teal-400/20 bg-teal-500/[0.07] px-2 py-1 font-mono text-[11.5px] text-teal-200">
                                {s.symbol}
                                <b className="ml-1.5 text-[11px] text-teal-300/70">{s.count}</b>
                            </span>
                        ))}
                    </div>
                </div>
            )}

            <p className="mt-3 text-[11px] text-gray-600">
                이 근거들이 심층 분석의 토론 프롬프트에 투입됩니다 · 종목 키 정확 검색 · 출처 등급 부착
            </p>
        </section>
    );
}

function Header() {
    return (
        <h2 className="mb-3 flex items-center gap-2.5 text-base font-bold text-white">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-teal-400/20 bg-teal-500/10">
                <i className="fas fa-diagram-project text-[13px] text-teal-300" />
            </span>
            <span>지식베이스</span>
            <span className="rounded-full border border-teal-400/25 bg-teal-500/10 px-2 py-0.5 text-[10px] font-bold text-teal-300">
                RAG
            </span>
            <span className="text-[11px] font-medium text-gray-500">검색이 알고 있는 것</span>
        </h2>
    );
}

function Metric({ label, value, unit, sub, warn }: {
    label: string; value: string; unit: string; sub?: string; warn?: boolean;
}) {
    return (
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-3">
            <div className="text-[10.5px] font-bold uppercase tracking-wider text-gray-500">{label}</div>
            <div className="mt-1 flex items-baseline gap-1">
                <span className="text-xl font-bold text-white">{value}</span>
                <span className="text-[11px] text-gray-500">{unit}</span>
            </div>
            {sub && (
                <div className={`mt-0.5 text-[11px] ${warn ? 'text-amber-300/80' : 'text-gray-500'}`}>
                    {sub}
                </div>
            )}
        </div>
    );
}
