import { useEffect, useState } from 'react';
import { adminAPI, AdminUser } from '@/lib/api';

/**
 * Pro 관리 탭 — Pro 구독자 만료일 중심 뷰.
 *
 * 특징:
 *   - Pro 유저만 필터 (tier='pro'). Ultra Pro(=premium) 는 무기한이라 통계에만 표시.
 *   - 만료일 오름차순 정렬 (임박 먼저)
 *   - 통계 5종: 전체 / 만료 / D-1 / D-3 / 일반
 *   - 만료 상태별 row 배경색 + D-day 뱃지
 *   - pro_expiry_alert_stage (D-3 / D-1 / expired 알림 발송 이력) 표시
 *   - 원클릭 +30일 / +7일 연장
 *
 * API 재사용:
 *   - GET  /api/admin/users          (전체 조회)
 *   - POST /api/admin/users/<id>/extend  (연장)
 */

interface ProUser extends AdminUser {
    pro_expiry_alert_stage?: string | null;
}

export default function ProExpiryTab({ apiToken }: { apiToken?: string }) {
    const [users, setUsers] = useState<ProUser[]>([]);
    const [loading, setLoading] = useState(true);
    const [extendingId, setExtendingId] = useState<number | null>(null);
    const [revokingId, setRevokingId] = useState<number | null>(null);
    const [msg, setMsg] = useState<string>('');
    const [filter, setFilter] = useState<'all' | 'expired' | 'd3' | 'd1'>('all');

    const load = async () => {
        setLoading(true);
        try {
            const res = await adminAPI.getUsers(apiToken);
            setUsers((res.users || []) as ProUser[]);
        } catch { /* */ }
        setLoading(false);
    };
    useEffect(() => { load(); }, [apiToken]);

    const showMsg = (text: string, isErr = false) => {
        setMsg(isErr ? `error:${text}` : `ok:${text}`);
        setTimeout(() => setMsg(''), 3000);
    };

    // 만료일까지 남은 일수 (음수 = 만료됨, null = 만료일 없음)
    const daysTo = (iso?: string | null): number | null => {
        if (!iso) return null;
        return Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000);
    };

    const proUsers = users.filter(u => u.tier === 'pro' && u.role !== 'admin');
    const premiumCount = users.filter(u => u.tier === 'premium' && u.role !== 'admin').length;

    const bucket = (u: ProUser): 'expired' | 'd1' | 'd3' | 'normal' | 'none' => {
        const d = daysTo(u.pro_expires_at);
        if (d === null) return 'none';
        if (d < 0) return 'expired';
        if (d <= 1) return 'd1';
        if (d <= 3) return 'd3';
        return 'normal';
    };

    const counts = {
        expired: proUsers.filter(u => bucket(u) === 'expired').length,
        d1:      proUsers.filter(u => bucket(u) === 'd1').length,
        d3:      proUsers.filter(u => bucket(u) === 'd3').length,
        normal:  proUsers.filter(u => bucket(u) === 'normal').length,
        none:    proUsers.filter(u => bucket(u) === 'none').length,
    };

    // 필터 적용
    let filtered = proUsers;
    if (filter === 'expired') filtered = proUsers.filter(u => bucket(u) === 'expired');
    else if (filter === 'd1') filtered = proUsers.filter(u => ['expired', 'd1'].includes(bucket(u)));
    else if (filter === 'd3') filtered = proUsers.filter(u => ['expired', 'd1', 'd3'].includes(bucket(u)));

    // 만료일 오름차순 (null 은 맨 뒤)
    const sorted = [...filtered].sort((a, b) => {
        const da = daysTo(a.pro_expires_at);
        const db = daysTo(b.pro_expires_at);
        if (da === null && db === null) return 0;
        if (da === null) return 1;
        if (db === null) return -1;
        return da - db;
    });

    const fmtExpiry = (iso?: string | null): { label: string; cls: string; badge: string | null; badgeCls: string } => {
        const d = daysTo(iso);
        if (!iso || d === null) return { label: '—', cls: 'text-gray-600', badge: null, badgeCls: '' };
        const dateStr = new Date(iso).toLocaleDateString('ko-KR', { year: '2-digit', month: '2-digit', day: '2-digit' });
        if (d < 0)  return { label: dateStr, cls: 'text-red-400',    badge: `만료 ${Math.abs(d)}일`, badgeCls: 'bg-red-500/20 text-red-400' };
        if (d <= 1) return { label: dateStr, cls: 'text-red-400',    badge: `D-${d}`, badgeCls: 'bg-red-500/20 text-red-400' };
        if (d <= 3) return { label: dateStr, cls: 'text-amber-400',  badge: `D-${d}`, badgeCls: 'bg-amber-500/20 text-amber-400' };
        if (d <= 7) return { label: dateStr, cls: 'text-yellow-300', badge: `D-${d}`, badgeCls: 'bg-yellow-500/15 text-yellow-300' };
        return { label: dateStr, cls: 'text-gray-400', badge: `${d}일 남음`, badgeCls: 'bg-white/5 text-gray-400' };
    };

    const alertStageLabel = (s?: string | null): { text: string; cls: string } => {
        if (!s) return { text: '—', cls: 'text-gray-600' };
        if (s === 'd3')      return { text: 'D-3 알림 발송', cls: 'text-amber-400' };
        if (s === 'd1')      return { text: 'D-1 알림 발송', cls: 'text-red-400' };
        if (s === 'expired') return { text: '만료 알림 발송', cls: 'text-red-500' };
        return { text: s, cls: 'text-gray-400' };
    };

    const handleExtend = async (u: ProUser, days: number) => {
        setExtendingId(u.id);
        try {
            const res = await adminAPI.extendPro(u.id, days, apiToken);
            setUsers(prev => prev.map(x => x.id === u.id ? (res.user as ProUser) : x));
            showMsg(`${u.name} +${days}일 연장 완료`);
        } catch (err: any) {
            showMsg(err?.message || '연장 실패', true);
        }
        setExtendingId(null);
    };

    const handleRevoke = async (u: ProUser) => {
        const ok = window.confirm(
            `정말 "${u.name}" (${u.email}) 님의 Pro 구독을 즉시 만료 처리하시겠습니까?\n\n` +
            `- 대시보드 접근 차단 (재구독 페이지로 자동 이동)\n` +
            `- 로그인은 계속 가능 (환불/재구독 협의용)\n` +
            `- 이력은 보존, 복구는 "+30일 연장" 으로 가능`
        );
        if (!ok) return;

        const note = window.prompt('해제 사유 (감사로그에 기록, 공란 가능):', '') || '';

        setRevokingId(u.id);
        try {
            const res = await adminAPI.revokeSubscription(u.id, note || undefined, apiToken);
            setUsers(prev => prev.map(x => x.id === u.id ? (res.user as ProUser) : x));
            showMsg(`${u.name} 구독 즉시 만료 처리 완료`);
        } catch (err: any) {
            showMsg(err?.message || '해제 실패', true);
        }
        setRevokingId(null);
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center py-16">
                <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    return (
        <div className="space-y-5">
            {/* 통계 카드 */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                <StatCard label="전체 Pro" value={proUsers.length} color="amber" />
                <StatCard label="만료됨" value={counts.expired} color="red" highlight={counts.expired > 0} />
                <StatCard label="D-1 이내" value={counts.d1} color="red" highlight={counts.d1 > 0} />
                <StatCard label="D-3 이내" value={counts.d3} color="amber" highlight={counts.d3 > 0} />
                <StatCard label="일반" value={counts.normal} color="gray" />
            </div>

            <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="text-xs text-gray-500">
                    <i className="fas fa-gem text-purple-400 mr-1" />
                    Ultra Pro <span className="text-purple-400 font-bold">{premiumCount}명</span> (무기한 — 만료 없음)
                </div>
                <div className="flex items-center gap-2 text-xs flex-wrap">
                    {([
                        ['all',     `전체 ${proUsers.length}`],
                        ['d3',      `D-3 이내 ${counts.expired + counts.d1 + counts.d3}`],
                        ['d1',      `D-1 이내 ${counts.expired + counts.d1}`],
                        ['expired', `만료 ${counts.expired}`],
                    ] as const).map(([k, label]) => (
                        <button
                            key={k}
                            onClick={() => setFilter(k)}
                            className={`px-3 py-1 rounded-full border transition-colors ${
                                filter === k
                                    ? 'bg-amber-500/20 border-amber-500/40 text-amber-300'
                                    : 'bg-white/5 border-white/10 text-gray-400 hover:text-white'
                            }`}
                        >
                            {label}
                        </button>
                    ))}
                </div>
            </div>

            {msg && (
                <div className={`px-4 py-2 rounded-lg text-xs ${
                    msg.startsWith('error:')
                        ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                        : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                }`}>
                    {msg.replace(/^(ok|error):/, '')}
                </div>
            )}

            {/* 테이블 */}
            <div className="bg-[#141416] border border-white/[0.06] rounded-xl overflow-hidden">
                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead className="bg-white/[0.03]">
                            <tr>
                                <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">회원</th>
                                <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden md:table-cell">가입일</th>
                                <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">만료일</th>
                                <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden lg:table-cell">알림 상태</th>
                                <th className="text-left text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3 hidden md:table-cell">최근 로그인</th>
                                <th className="text-right text-[10px] font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">연장</th>
                            </tr>
                        </thead>
                        <tbody>
                            {sorted.map(u => {
                                const exp = fmtExpiry(u.pro_expires_at);
                                const stage = alertStageLabel(u.pro_expiry_alert_stage);
                                const b = bucket(u);
                                const rowCls = b === 'expired'
                                    ? 'bg-red-500/[0.04] hover:bg-red-500/[0.08]'
                                    : b === 'd1'
                                    ? 'bg-red-500/[0.02] hover:bg-red-500/[0.05]'
                                    : b === 'd3'
                                    ? 'bg-amber-500/[0.02] hover:bg-amber-500/[0.05]'
                                    : 'hover:bg-white/[0.02]';
                                return (
                                    <tr key={u.id} className={`border-t border-white/[0.04] transition-colors ${rowCls}`}>
                                        <td className="px-4 py-3">
                                            <div className="flex items-center gap-3">
                                                <div className="w-8 h-8 rounded-full bg-amber-500/15 flex items-center justify-center text-xs font-bold text-amber-300 shrink-0">
                                                    {u.name.charAt(0).toUpperCase()}
                                                </div>
                                                <div className="min-w-0">
                                                    <div className="text-sm font-medium text-white truncate">{u.name}</div>
                                                    <div className="text-xs text-gray-500 truncate">{u.email}</div>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-4 py-3 hidden md:table-cell">
                                            <span className="text-xs text-gray-600">
                                                {u.created_at ? new Date(u.created_at).toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' }) : '-'}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3">
                                            <div className="flex items-center gap-2 flex-wrap">
                                                <span className={`text-sm font-bold ${exp.cls}`}>{exp.label}</span>
                                                {exp.badge && (
                                                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${exp.badgeCls}`}>
                                                        {exp.badge}
                                                    </span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-4 py-3 hidden lg:table-cell">
                                            <span className={`text-[11px] ${stage.cls}`}>{stage.text}</span>
                                        </td>
                                        <td className="px-4 py-3 hidden md:table-cell">
                                            <span className="text-xs text-gray-600">
                                                {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' }) : '—'}
                                            </span>
                                        </td>
                                        <td className="px-4 py-3 text-right whitespace-nowrap">
                                            <div className="inline-flex items-center gap-1">
                                                <button
                                                    onClick={() => handleExtend(u, 30)}
                                                    disabled={extendingId === u.id || revokingId === u.id}
                                                    className="px-2.5 py-1 rounded-lg text-[11px] font-bold bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors disabled:opacity-50"
                                                    title="+30일 연장"
                                                >
                                                    {extendingId === u.id ? <i className="fas fa-spinner fa-spin" /> : '+30일'}
                                                </button>
                                                <button
                                                    onClick={() => handleExtend(u, 7)}
                                                    disabled={extendingId === u.id || revokingId === u.id}
                                                    className="px-2 py-1 rounded-lg text-[10px] text-gray-500 hover:text-emerald-400 hover:bg-emerald-500/10 transition-colors disabled:opacity-50"
                                                    title="+7일 연장"
                                                >
                                                    +7d
                                                </button>
                                                {/* 즉시 만료 처리 (관리자 중도 해제) — 만료 아직 안된 유저만 표시 */}
                                                {b !== 'expired' && (
                                                    <button
                                                        onClick={() => handleRevoke(u)}
                                                        disabled={extendingId === u.id || revokingId === u.id}
                                                        className="px-2 py-1 rounded-lg text-[10px] font-bold bg-red-500/10 text-red-400 hover:bg-red-500/25 transition-colors disabled:opacity-50 ml-1 border border-red-500/20"
                                                        title="구독 즉시 만료 처리 (confirm 필요)"
                                                    >
                                                        {revokingId === u.id ? <i className="fas fa-spinner fa-spin" /> : '해제'}
                                                    </button>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                    {sorted.length === 0 && (
                        <div className="text-center py-12 text-gray-500 text-sm">
                            {filter === 'all' ? 'Pro 구독자가 없습니다' : '해당 구간에 대상자 없음'}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

function StatCard({ label, value, color, highlight }: { label: string; value: number; color: 'amber' | 'red' | 'gray'; highlight?: boolean }) {
    const cls = {
        amber: { bg: 'bg-amber-500/10', border: 'border-amber-500/20', text: 'text-amber-400' },
        red:   { bg: 'bg-red-500/10',   border: 'border-red-500/20',   text: 'text-red-400'   },
        gray:  { bg: 'bg-white/[0.03]', border: 'border-white/10',     text: 'text-gray-400'  },
    }[color];
    return (
        <div className={`p-4 rounded-xl border ${cls.bg} ${cls.border} ${highlight ? 'ring-2 ring-red-500/30' : ''}`}>
            <div className="text-[10px] text-gray-500 uppercase tracking-wider font-semibold mb-1">{label}</div>
            <div className={`text-2xl font-black ${cls.text}`}>{value}</div>
        </div>
    );
}
