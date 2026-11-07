import { useCallback, useEffect, useRef, useState } from 'react';
import { adminAPI, type AdminUser } from '@/lib/api';
import MemberSubscriptionActions from './MemberSubscriptionActions';

export default function SubscriptionMemberDesk({ apiToken, onBusyChange }: {
    apiToken?: string; onBusyChange: (busy: boolean) => void;
}) {
    const [members, setMembers] = useState<AdminUser[]>([]);
    const [selected, setSelected] = useState<AdminUser | null>(null);
    const [search, setSearch] = useState('');
    const [query, setQuery] = useState('');
    const [filter, setFilter] = useState('');
    const [page, setPage] = useState(1);
    const [pages, setPages] = useState(1);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const sequence = useRef(0);
    const busyRef = useRef(false);
    const load = useCallback(async () => {
        if (busyRef.current) return;
        const id = ++sequence.current;
        setLoading(true); setError('');
        try {
            const result = await adminAPI.getUsers(apiToken, { q: query, subscription_state: filter, page, per_page: 12 });
            if (!Array.isArray(result?.users)) throw new Error('회원 구독 현황을 확인하지 못했습니다.');
            if (id !== sequence.current) return;
            setMembers(result.users); setTotal(result.total ?? result.users.length); setPages(result.total_pages || 1);
        } catch (err) { if (id === sequence.current) setError(err instanceof Error ? err.message : '회원 조회에 실패했습니다.'); }
        finally { if (id === sequence.current) setLoading(false); }
    }, [apiToken, query, filter, page]);
    useEffect(() => { void load(); return () => { sequence.current++; }; }, [load]);
    const changeBusy = (value: boolean) => {
        busyRef.current = value; setBusy(value); onBusyChange(value);
        if (value) { sequence.current++; setLoading(false); }
        else void load();
    };
    const button = 'rounded-lg border border-white/10 px-3 py-2 text-sm disabled:opacity-40 hover:bg-white/10';
    return <section aria-label="회원별 구독 직권 관리" className="rounded-xl border border-white/10 p-4 space-y-4">
        <div><h2 className="font-semibold text-lg text-white">회원별 구독 직권 관리</h2>
            <p className="mt-1 text-sm text-gray-400">만료 회원도 이곳에서 검색해 재승인·연장·철회·삭제할 수 있습니다. 신청 철회와 이용권 만료는 별도 처리입니다.</p></div>
        <form onSubmit={event => { event.preventDefault(); if (!busy) { setPage(1); setQuery(search.trim()); } }} className="flex flex-col sm:flex-row gap-2">
            <input aria-label="구독 회원 검색" placeholder="이름·이메일·회원번호" value={search} disabled={busy} onChange={event => setSearch(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-sm" />
            <select aria-label="구독 상태 필터" value={filter} disabled={busy} onChange={event => { setFilter(event.target.value); setPage(1); }} className="rounded-lg bg-[#242426] border border-white/10 px-3 py-2 text-sm">
                <option value="">전체 구독 상태</option><option value="expired">만료·재구독 필요</option><option value="expiring">3일 이내 만료</option><option value="active">이용 중</option><option value="none">구독 미신청</option>
            </select>
            <button className={button} disabled={busy}>검색</button>
            <button type="button" className={button} disabled={busy || loading} onClick={() => void load()}>회원 목록 갱신</button>
        </form>
        {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
        {loading && <p role="status" className="text-sm text-gray-400">회원 구독 현황 조회 중...</p>}
        <p className="text-xs text-gray-400">검색 결과 {total}명 · {page}/{pages} 페이지</p>
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {members.map(member => <button key={member.id} disabled={busy} onClick={() => setSelected(member)} aria-label={`${member.name} 직권 처리`} className={`rounded-lg border p-3 text-left min-w-0 ${selected?.id === member.id ? 'border-cyan-500/60 bg-cyan-500/5' : 'border-white/10 bg-white/[0.02]'}`}>
                <strong className="block text-sm text-white">{member.name} <span className="font-normal text-gray-500">#{member.id}</span></strong>
                <span className="block break-all text-xs text-gray-400 mt-1">{member.email}</span>
                <span className="block mt-2 text-xs text-amber-300">{member.subscription_lifecycle?.label || (member.status === 'expired' || member.is_pro_expired ? '구독 만료' : member.status === 'approved' ? '이용 중' : '구독 확인 필요')}</span>
                <span className="block mt-1 text-xs text-gray-400">{member.tier === 'premium' ? 'Ultra PRO' : member.tier === 'pro' ? 'PRO' : '무등급'} · AI {member.is_aibain_active ? '이용 중' : '미이용'} · 제갈공명 {member.is_kongming_active ? '이용 중' : '미이용'}</span>
            </button>)}
        </div>
        {!loading && !error && members.length === 0 && <p className="text-sm text-gray-400">조건에 맞는 회원이 없습니다.</p>}
        {pages > 1 && <div className="flex justify-between gap-2"><button disabled={busy || page <= 1} onClick={() => setPage(value => value - 1)} className={button}>이전</button><button disabled={busy || page >= pages} onClick={() => setPage(value => value + 1)} className={button}>다음</button></div>}
        {selected && <div className="space-y-2">
            <button disabled={busy} className={button} onClick={() => setSelected(null)}>회원 관리 닫기</button>
            <MemberSubscriptionActions key={selected.id} user={selected} apiToken={apiToken}
                onBusyChange={changeBusy}
                onUpdated={user => { setSelected(user); setMembers(items => items.map(item => item.id === user.id ? user : item)); }}
                onDeleted={id => { setSelected(null); setMembers(items => items.filter(item => item.id !== id)); changeBusy(false); }} />
        </div>}
    </section>;
}
