import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';

/**
 * 구독 갱신 배너 — 대시보드 전 페이지 상단에 얇게 노출.
 *
 * 노출 조건 (우선순위 순):
 *  1. Pro 베이스 만료 D-7 이내  → 재구독/갱신 유도 (/plan-select?change=1)
 *  2. AI Brain 애드온 만료 D-5 이내 → 애드온 갱신 유도
 * Ultra Pro(premium) 베이스는 무기한이므로 1번 제외. admin 은 항상 숨김.
 * 세션 동안 닫기 가능 (sessionStorage) — 매 방문 리마인드는 유지하되 페이지마다 방해하지 않는다.
 */

const DISMISS_KEY = 'renewal_banner_dismissed';

function daysLeft(iso: string | null | undefined): number | null {
    if (!iso) return null;
    const diff = new Date(iso).getTime() - Date.now();
    if (Number.isNaN(diff)) return null;
    return Math.ceil(diff / 86_400_000);
}

export default function RenewalBanner() {
    const { user } = useAuth();
    const [dismissed, setDismissed] = useState(() => {
        try { return sessionStorage.getItem(DISMISS_KEY) === '1'; } catch { return false; }
    });

    const banner = useMemo(() => {
        if (!user || user.role === 'admin') return null;

        // 1. Pro 베이스 만료 임박 (premium 은 무기한)
        if (user.tier === 'pro' && !user.is_pro_expired) {
            const d = daysLeft(user.pro_expires_at);
            if (d !== null && d >= 0 && d <= 7) {
                return {
                    key: `pro-${d}`,
                    icon: 'fa-hourglass-half',
                    tone: 'border-amber-400/30 bg-amber-500/[0.10] text-amber-100',
                    accent: 'text-amber-300',
                    message: d === 0
                        ? 'Pro 이용 기간이 오늘 만료됩니다.'
                        : `Pro 이용 기간이 ${d}일 뒤 만료됩니다.`,
                    sub: '지금 갱신 신청하면 승인 즉시 30일이 이어집니다.',
                    cta: '갱신 신청',
                    to: '/plan-select?change=1',
                };
            }
        }

        // 2. AI Brain 애드온 만료 임박
        if (user.is_aibain_active) {
            const d = daysLeft(user.aibain_expires_at);
            if (d !== null && d >= 0 && d <= 5) {
                return {
                    key: `aibain-${d}`,
                    icon: 'fa-brain',
                    tone: 'border-cyan-400/30 bg-cyan-500/[0.10] text-cyan-100',
                    accent: 'text-cyan-300',
                    message: d === 0
                        ? 'AI Brain 애드온이 오늘 만료됩니다.'
                        : `AI Brain 애드온이 ${d}일 뒤 만료됩니다.`,
                    sub: '만료되면 알파 스캐너 · TOP 3 · 성과 검증 화면 접근이 중단됩니다.',
                    cta: 'AI Brain 갱신',
                    to: '/dashboard/ai-bain',
                };
            }
        }
        return null;
    }, [user]);

    if (!banner || dismissed) return null;

    const dismiss = () => {
        setDismissed(true);
        try { sessionStorage.setItem(DISMISS_KEY, '1'); } catch { /* 무시 */ }
    };

    return (
        <div role="status" className={`mb-2.5 flex items-center gap-3 rounded-xl border px-3.5 py-2.5 md:mb-3 ${banner.tone}`}>
            <i className={`fas ${banner.icon} shrink-0 ${banner.accent}`} aria-hidden />
            <div className="min-w-0 flex-1 text-[12.5px] leading-5">
                <span className="font-bold">{banner.message}</span>
                <span className="ml-1.5 hidden opacity-70 sm:inline">{banner.sub}</span>
            </div>
            <Link
                to={banner.to}
                className="inline-flex min-h-[34px] shrink-0 items-center rounded-lg bg-white/10 px-3 text-[12px] font-black transition-colors hover:bg-white/20"
            >
                {banner.cta}<i className="fas fa-arrow-right ml-1.5 text-[10px]" aria-hidden />
            </Link>
            <button
                type="button"
                onClick={dismiss}
                aria-label="배너 닫기"
                className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-current opacity-50 transition-opacity hover:opacity-100"
            >
                <i className="fas fa-xmark text-[12px]" aria-hidden />
            </button>
        </div>
    );
}
