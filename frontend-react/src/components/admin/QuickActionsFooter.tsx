/**
 * Quick Actions Footer — 우측 패널 하단 빠른 액션 버튼 묶음.
 *
 * 기존 엔드포인트들을 한 줄 컨트롤로 노출 (안전 — read or dry_run 기본):
 *  - 🔄 Force Scan      → POST /scanner/runs (즉시 신규 스캐너 실행)
 *  - 🔍 Outcomes 새로고침 → POST /workflows/{latest}/outcomes/refresh
 *  - 🚨 Test Alert (dry) → POST /scanner/alerts/check  { dry_run: true }
 *  - 🌐 KR Gate 새로고침 → GET /api/kr/market-gate
 *
 * 결과는 우측 카드 자동 폴링이 다음 사이클에 반영하므로 별도 invalidate 불필요.
 */
import { useState } from 'react';
import { mirofishApi } from '@/lib/mirofishApi';
import { postAuthAPI } from '@/lib/api';

type ActionState = 'idle' | 'running' | 'ok' | 'failed';

interface Action {
    key: string;
    label: string;
    emoji: string;
    description: string;
    run: () => Promise<string>;
}

async function fetchKrGate(): Promise<string> {
    const resp = await fetch('/api/kr/market-gate', { credentials: 'include' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    return data?.label || data?.status || 'updated';
}

async function refreshLatestOutcomes(): Promise<string> {
    const latest = await mirofishApi.getLatestWorkflow();
    const latestId = (latest as any)?.id;
    if (!latestId) return 'no workflow';
    const res = await mirofishApi.refreshWorkflowOutcomes(latestId);
    const evaluated = (res as any)?.summary?.evaluated_count ?? 0;
    const pending = (res as any)?.summary?.pending_count ?? 0;
    return `${evaluated} 평가완료 / ${pending} 진행중`;
}

async function forceScannerRun(): Promise<string> {
    const run = await mirofishApi.startScannerRun({ limit: 20 });
    const count = (run as any)?.candidate_count ?? ((run as any)?.candidates?.length ?? 0);
    return `${count} candidates`;
}

async function testAlertDryRun(): Promise<string> {
    const res = await postAuthAPI<{ events?: unknown[]; new_event_count?: number }>(
        '/api/admin/mirofish/scanner/alerts/check',
        { dry_run: true, send_telegram: false },
        undefined,
        60000,
    );
    const events = res?.events?.length ?? res?.new_event_count ?? 0;
    return `${events} new event${events === 1 ? '' : 's'}`;
}

export default function QuickActionsFooter() {
    const [states, setStates] = useState<Record<string, ActionState>>({});
    const [results, setResults] = useState<Record<string, string>>({});

    const actions: Action[] = [
        {
            key: 'scan',
            label: 'Force Scan',
            emoji: '🔄',
            description: '즉시 신규 스캐너 실행',
            run: forceScannerRun,
        },
        {
            key: 'outcomes',
            label: 'Outcomes 새로고침',
            emoji: '🔍',
            description: '최신 워크플로우 forward outcomes 재계산',
            run: refreshLatestOutcomes,
        },
        {
            key: 'alert',
            label: 'Alert Dry-Run',
            emoji: '🚨',
            description: '알림 발송 대상 미리보기 (전송 X)',
            run: testAlertDryRun,
        },
        {
            key: 'gate',
            label: 'KR Gate',
            emoji: '🌐',
            description: 'KR 시장 게이트 라이브 재계산',
            run: fetchKrGate,
        },
    ];

    async function exec(action: Action) {
        if (states[action.key] === 'running') return;
        setStates((prev) => ({ ...prev, [action.key]: 'running' }));
        setResults((prev) => ({ ...prev, [action.key]: '' }));
        try {
            const text = await action.run();
            setStates((prev) => ({ ...prev, [action.key]: 'ok' }));
            setResults((prev) => ({ ...prev, [action.key]: text }));
            setTimeout(() => {
                setStates((prev) => (prev[action.key] === 'ok' ? { ...prev, [action.key]: 'idle' } : prev));
            }, 4000);
        } catch (err) {
            setStates((prev) => ({ ...prev, [action.key]: 'failed' }));
            const msg = err instanceof Error ? err.message : 'failed';
            setResults((prev) => ({ ...prev, [action.key]: msg.slice(0, 60) }));
        }
    }

    return (
        <section className="rounded-xl border border-violet-300/15 bg-slate-950/60 p-3 shadow-[0_18px_70px_rgba(167,139,250,0.10)] sm:p-4">
            <header className="flex items-center justify-between">
                <div className="min-w-0">
                    <div className="flex items-center gap-1.5 text-[10px] font-black uppercase tracking-[0.18em] text-violet-200/70 sm:text-[11px] sm:tracking-[0.22em]">
                        <i className="fas fa-bolt text-violet-300" />
                        <span className="truncate">Quick Actions</span>
                    </div>
                    <h3 className="mt-1 text-sm font-black text-white sm:text-base">빠른 액션 콘솔</h3>
                </div>
            </header>

            {/* 모바일: 1열 / sm+: 2열 — 터치 타겟 ≥44px */}
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                {actions.map((action) => {
                    const state = states[action.key] || 'idle';
                    const tone =
                        state === 'running' ? 'border-violet-300/30 bg-violet-300/10 text-violet-100' :
                        state === 'ok' ? 'border-emerald-300/30 bg-emerald-300/10 text-emerald-100' :
                        state === 'failed' ? 'border-rose-300/30 bg-rose-300/10 text-rose-100' :
                        'border-white/10 bg-black/30 text-slate-200 hover:border-violet-300/30 hover:bg-violet-300/[0.08] active:bg-violet-300/[0.12]';
                    return (
                        <button
                            key={action.key}
                            type="button"
                            disabled={state === 'running'}
                            onClick={() => exec(action)}
                            className={`group flex min-h-[52px] flex-col justify-center rounded-lg border px-3 py-2 text-left text-[11px] font-bold transition-colors disabled:cursor-wait sm:min-h-[48px] ${tone}`}
                            title={action.description}
                        >
                            <div className="flex items-center justify-between gap-2">
                                <span className="font-black truncate">{action.emoji} {action.label}</span>
                                {state === 'running' && (
                                    <span className="inline-block h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-current" />
                                )}
                            </div>
                            <div className="mt-0.5 truncate text-[10px] font-bold opacity-70">
                                {results[action.key] || action.description}
                            </div>
                        </button>
                    );
                })}
            </div>
            <div className="mt-2 text-[10px] font-bold leading-snug text-slate-500">
                액션 결과는 우측 카드 자동 폴링에 반영됩니다. dry-run은 텔레그램 전송 없이 검사만 합니다.
            </div>
        </section>
    );
}
