/**
 * AI Brain 서비스 가드 카드 — 3대 서비스(스캐너·펀드매니저·판단)의 지속성 상태.
 *
 * GET /api/admin/mirofish/service-guard (admin·AI Brain 구독자). 권한이 없거나
 * 백엔드가 아직 가드를 모르면 조용히 렌더하지 않는다 — 카드가 화면을 깨지 않는다.
 */
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { fetchAuthAPI } from '@/lib/api';

interface GuardService { status: 'ok' | 'warn' | 'fail' | string; detail?: Record<string, unknown>; checked_ms?: number; }
interface GuardPayload { generated_at: string; overall: string; services: Record<string, GuardService>; }

const LABEL: Record<string, string> = { scanner: '알파 스캐너', goodrich: 'AI 펀드매니저', decision: '판단 조회' };
const TONE: Record<string, string> = {
    ok: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300',
    warn: 'border-amber-400/30 bg-amber-500/10 text-amber-300',
    fail: 'border-red-500/40 bg-red-500/10 text-red-300',
};

function isGuardPayload(v: unknown): v is GuardPayload {
    const o = v as Partial<GuardPayload> | null;
    return !!o && typeof o === 'object' && typeof o.overall === 'string' && !!o.services;
}

function summarize(name: string, svc: GuardService): string {
    const d = svc.detail ?? {};
    if (name === 'scanner' && d.latest_run_age_h != null) return `최신 런 ${Number(d.latest_run_age_h).toFixed(1)}h 전`;
    if (name === 'goodrich') {
        if (d.service_error) return String(d.service_error);
        if (d.service_ms != null) return `응답 ${d.service_ms}ms · 원장 ${d.ledger_age_h ?? '-'}h`;
    }
    if (name === 'decision') {
        if (d.probe_error) return String(d.probe_error);
        return `프로브 ${d.probe_s}s · 최다소요 ${d.slowest_source ?? '-'}`;
    }
    return '';
}

export default function ServiceGuardCard() {
    const { token } = useAuth();
    const [data, setData] = useState<GuardPayload | null>(null);
    const [refreshing, setRefreshing] = useState(false);

    const load = useCallback(async () => {
        try {
            const res = await fetchAuthAPI<unknown>('/api/admin/mirofish/service-guard', token ?? undefined, 30000);
            if (isGuardPayload(res)) setData(res);
        } catch {
            // 권한 없음/미배포 백엔드 — 첫 프로브가 실패하면 data 가 null 그대로라
            // 카드를 그리지 않는다. 이미 표시 중이던 상태는 일시적 새로고침 실패
            // (타임아웃·재시작 중 5xx)로 지우지 않는다 — 마지막 정상 데이터를 유지한다.
        }
    }, [token]);

    useEffect(() => {
        void load();
        const timer = setInterval(() => { if (document.visibilityState === 'visible') void load(); }, 60000);
        return () => clearInterval(timer);
    }, [load]);

    if (!data) return null;

    return (
        <section className="rounded-2xl border border-white/[0.06] bg-[#13151f] p-5">
            <h2 className="mb-3 flex items-center gap-2 text-[15px] font-bold text-white">
                <i className="fas fa-shield-halved text-[13px] text-emerald-400" />
                서비스 가드
                <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase ${TONE[data.overall] ?? TONE.warn}`}>{data.overall}</span>
                <span className="ml-auto text-[11px] font-medium text-gray-500">
                    {data.generated_at.slice(5, 16).replace('T', ' ')}
                    <button
                        type="button"
                        className="ml-2 text-gray-500 transition-colors hover:text-gray-300 disabled:opacity-50"
                        disabled={refreshing}
                        onClick={() => { setRefreshing(true); void load().finally(() => setRefreshing(false)); }}
                        aria-label="서비스 가드 새로고침"
                    >
                        <i className={`fas fa-rotate-right text-[11px] ${refreshing ? 'fa-spin' : ''}`} />
                    </button>
                </span>
            </h2>
            <ul className="space-y-1.5">
                {Object.entries(data.services).map(([name, svc]) => (
                    <li key={name} className="flex items-center gap-2.5 text-[13px]">
                        <span className={`w-12 rounded-md border px-1.5 py-0.5 text-center text-[10px] font-black uppercase ${TONE[svc.status] ?? TONE.warn}`}>{svc.status}</span>
                        <b className="w-24 shrink-0 font-bold text-gray-100">{LABEL[name] ?? name}</b>
                        <span className="min-w-0 flex-1 truncate text-[12px] text-gray-400">{summarize(name, svc)}</span>
                    </li>
                ))}
            </ul>
        </section>
    );
}
