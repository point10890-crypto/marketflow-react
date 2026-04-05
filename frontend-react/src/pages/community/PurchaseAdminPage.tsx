import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchAuthAPI, putAuthAPI, deleteAuthAPI } from '@/lib/api';

interface PurchaseItem {
    id: number;
    post_id: number;
    user_id: number;
    buyer_name: string;
    status: string;
    user_name: string | null;
    post_title: string | null;
    post_price: string | null;
    created_at: string;
    approved_at: string | null;
}

interface PurchaseListResponse {
    purchases: PurchaseItem[];
    total: number;
    page: number;
    per_page: number;
    total_pages: number;
}

function formatKoreanDate(dateStr: string | null) {
    if (!dateStr) return '-';
    const d = new Date(dateStr);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const h = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    return `${y}년${m}월${day}일 ${h}시${min}분${s}초`;
}

function formatPrice(price?: string | null) {
    if (!price) return '-';
    const num = parseInt(price.replace(/[^0-9]/g, ''), 10);
    if (isNaN(num)) return price;
    return `${num.toLocaleString()} 원`;
}

function statusLabel(status: string) {
    if (status === 'approved') return { text: '승인', cls: 'text-green-400' };
    if (status === 'rejected') return { text: '거절', cls: 'text-red-400' };
    return { text: '대기', cls: 'text-yellow-400' };
}

export default function PurchaseAdminPage() {
    const navigate = useNavigate();
    const [purchases, setPurchases] = useState<PurchaseItem[]>([]);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [statusFilter, setStatusFilter] = useState('');
    const [search, setSearch] = useState('');

    const fetchData = useCallback(async (p: number) => {
        setLoading(true);
        try {
            const params = new URLSearchParams({ page: String(p) });
            if (statusFilter) params.set('status', statusFilter);
            if (search.trim()) params.set('search', search.trim());
            const data = await fetchAuthAPI<PurchaseListResponse>(`/api/community/purchases?${params}`);
            setPurchases(data.purchases);
            setPage(data.page);
            setTotalPages(data.total_pages);
            setTotal(data.total);
        } catch {
            /* ignore */
        } finally {
            setLoading(false);
        }
    }, [statusFilter, search]);

    useEffect(() => { fetchData(1); }, [fetchData]);

    const handleStatusChange = async (purchaseId: number, newStatus: string) => {
        // Optimistic update — 즉시 UI 반영
        setPurchases(prev => prev.map(p =>
            p.id === purchaseId ? { ...p, status: newStatus } : p
        ));
        try {
            await putAuthAPI(`/api/community/purchases/${purchaseId}`, { status: newStatus });
            fetchData(page);
        } catch {
            // Rollback on failure
            fetchData(page);
            alert('상태 변경에 실패했습니다.');
        }
    };

    const handleDelete = async (purchaseId: number) => {
        if (!confirm('이 구매 내역을 삭제하시겠습니까?')) return;
        // Optimistic update — 즉시 UI에서 제거
        setPurchases(prev => prev.filter(p => p.id !== purchaseId));
        setTotal(prev => prev - 1);
        try {
            await deleteAuthAPI(`/api/community/purchases/${purchaseId}`);
        } catch {
            fetchData(page);
            alert('삭제에 실패했습니다.');
        }
    };

    return (
        <div className="p-4 md:p-6 lg:py-8 lg:px-10">
            {/* Header */}
            <div className="flex items-center gap-3 mb-6">
                <button
                    onClick={() => navigate('/dashboard/community/formula-market')}
                    className="w-8 h-8 rounded-lg bg-white/[0.06] flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
                >
                    <i className="fas fa-arrow-left text-sm" />
                </button>
                <h1 className="text-xl md:text-2xl font-bold text-yellow-400">구매 신청 내역</h1>
                <span className="text-gray-500 text-sm ml-2">총 {total}건</span>
            </div>

            {/* Filters */}
            <div className="bg-[#1c1c1e]/80 border border-white/[0.06] rounded-2xl p-4 md:p-5 mb-5 flex flex-col sm:flex-row gap-3">
                <select
                    value={statusFilter}
                    onChange={e => setStatusFilter(e.target.value)}
                    className="bg-white/[0.06] border border-white/10 text-gray-300 text-sm rounded-lg px-3 py-2.5 focus:outline-none focus:border-yellow-500/50 sm:w-32"
                >
                    <option value="">전체</option>
                    <option value="pending">대기</option>
                    <option value="approved">승인</option>
                    <option value="rejected">거절</option>
                </select>
                <div className="flex-1 flex items-center gap-2">
                    <input
                        type="text"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && fetchData(1)}
                        placeholder="입금자명을 입력하세요."
                        className="flex-1 bg-transparent text-white placeholder-gray-600 focus:outline-none text-sm"
                    />
                    <button onClick={() => fetchData(1)} className="text-gray-400 hover:text-yellow-400 transition-colors">
                        <i className="fas fa-search" />
                    </button>
                </div>
            </div>

            {/* Table */}
            <div className="bg-[#1c1c1e]/80 border border-white/[0.06] rounded-2xl overflow-hidden">
                {loading ? (
                    <div className="flex items-center justify-center py-20">
                        <div className="w-8 h-8 border-2 border-[#2997ff] border-t-transparent rounded-full animate-spin" />
                    </div>
                ) : (
                    <>
                        {/* Desktop Table */}
                        <div className="hidden md:block overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-white/[0.06] bg-white/[0.03]">
                                        <th className="px-4 py-3.5 text-center font-bold text-gray-300 w-[20%]">식이름</th>
                                        <th className="px-3 py-3.5 text-center font-bold text-gray-300 w-[7%]">아이디</th>
                                        <th className="px-3 py-3.5 text-center font-bold text-gray-300 w-[16%]">요청일</th>
                                        <th className="px-3 py-3.5 text-center font-bold text-gray-300 w-[7%]">입금자명</th>
                                        <th className="px-3 py-3.5 text-center font-bold text-gray-300 w-[9%]">금액</th>
                                        <th className="px-3 py-3.5 text-center font-bold text-gray-300 w-[7%]">요청상태</th>
                                        <th className="px-3 py-3.5 text-center font-bold text-gray-300 w-[16%]">승인일</th>
                                        <th className="px-3 py-3.5 text-center font-bold text-gray-300 w-[18%]">비고</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-white/[0.04]">
                                    {purchases.map(p => {
                                        const st = statusLabel(p.status);
                                        return (
                                            <tr key={p.id} className="hover:bg-white/[0.02] transition-colors">
                                                <td className="px-4 py-3.5 text-gray-300 text-center">{p.post_title || '-'}</td>
                                                <td className="px-3 py-3.5 text-gray-400 text-center text-xs">{p.user_name || '-'}</td>
                                                <td className="px-3 py-3.5 text-gray-400 text-center text-xs">{formatKoreanDate(p.created_at)}</td>
                                                <td className="px-3 py-3.5 text-gray-300 text-center">{p.buyer_name}</td>
                                                <td className="px-3 py-3.5 text-gray-300 text-center text-xs">{formatPrice(p.post_price)}</td>
                                                <td className={`px-3 py-3.5 text-center font-bold text-xs ${st.cls}`}>{st.text}</td>
                                                <td className="px-3 py-3.5 text-gray-400 text-center text-xs">{formatKoreanDate(p.approved_at)}</td>
                                                <td className="px-3 py-3.5 text-center">
                                                    <div className="flex items-center justify-center gap-1.5">
                                                        {p.status === 'pending' ? (
                                                            <button
                                                                onClick={() => handleStatusChange(p.id, 'approved')}
                                                                className="bg-yellow-500 hover:bg-yellow-500/85 text-black text-[11px] font-bold px-2.5 py-1.5 rounded-lg transition-colors"
                                                            >
                                                                승인
                                                            </button>
                                                        ) : p.status === 'approved' ? (
                                                            <button
                                                                onClick={() => handleStatusChange(p.id, 'rejected')}
                                                                className="bg-yellow-500/80 hover:bg-yellow-500/60 text-black text-[11px] font-bold px-2 py-1.5 rounded-lg transition-colors leading-tight"
                                                            >
                                                                승인취소
                                                            </button>
                                                        ) : (
                                                            <button
                                                                onClick={() => handleStatusChange(p.id, 'approved')}
                                                                className="bg-white/10 hover:bg-white/15 text-gray-400 text-[11px] font-bold px-2.5 py-1.5 rounded-lg transition-colors"
                                                            >
                                                                재승인
                                                            </button>
                                                        )}
                                                        <button
                                                            onClick={() => handleDelete(p.id)}
                                                            className="bg-red-500/20 hover:bg-red-500/40 text-red-400 text-[11px] font-bold px-2 py-1.5 rounded-lg transition-colors"
                                                        >
                                                            삭제
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>

                        {/* Mobile Cards */}
                        <div className="md:hidden divide-y divide-white/[0.04]">
                            {purchases.map(p => {
                                const st = statusLabel(p.status);
                                return (
                                    <div key={p.id} className="px-4 py-4 space-y-2">
                                        <div className="flex items-start justify-between">
                                            <h3 className="text-white text-sm font-medium flex-1 mr-3">{p.post_title || '-'}</h3>
                                            <span className={`text-xs font-bold ${st.cls}`}>{st.text}</span>
                                        </div>
                                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                                            <span>입금자: <strong className="text-gray-300">{p.buyer_name}</strong></span>
                                            <span>ID: <strong className="text-gray-300">{p.user_name}</strong></span>
                                            <span>금액: <strong className="text-yellow-400">{formatPrice(p.post_price)}</strong></span>
                                        </div>
                                        <div className="flex items-center justify-between">
                                            <span className="text-gray-600 text-[11px]">{formatKoreanDate(p.created_at)}</span>
                                            <div className="flex items-center gap-2">
                                                {p.status === 'pending' ? (
                                                    <button
                                                        onClick={() => handleStatusChange(p.id, 'approved')}
                                                        className="bg-yellow-500 text-black text-xs font-bold px-3 py-1.5 rounded-lg"
                                                    >
                                                        승인
                                                    </button>
                                                ) : p.status === 'approved' ? (
                                                    <button
                                                        onClick={() => handleStatusChange(p.id, 'rejected')}
                                                        className="bg-yellow-500/80 text-black text-xs font-bold px-2.5 py-1.5 rounded-lg"
                                                    >
                                                        승인취소
                                                    </button>
                                                ) : (
                                                    <button
                                                        onClick={() => handleStatusChange(p.id, 'approved')}
                                                        className="bg-white/10 text-gray-400 text-xs font-bold px-3 py-1.5 rounded-lg"
                                                    >
                                                        재승인
                                                    </button>
                                                )}
                                                <button
                                                    onClick={() => handleDelete(p.id)}
                                                    className="bg-red-500/20 text-red-400 text-xs font-bold px-2.5 py-1.5 rounded-lg"
                                                >
                                                    삭제
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>

                        {/* Empty */}
                        {purchases.length === 0 && (
                            <div className="text-center py-16">
                                <i className="fas fa-inbox text-2xl text-gray-700 mb-3 block" />
                                <p className="text-gray-600 text-sm">구매 신청 내역이 없습니다.</p>
                            </div>
                        )}
                    </>
                )}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-center gap-3 mt-6">
                    <button
                        onClick={() => fetchData(page - 1)}
                        disabled={page <= 1}
                        className="w-9 h-9 rounded-lg border border-white/10 text-gray-400 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center"
                    >
                        <i className="fas fa-chevron-left text-xs" />
                    </button>
                    <span className="text-gray-300 text-sm font-medium">
                        {page} / {totalPages}
                    </span>
                    <button
                        onClick={() => fetchData(page + 1)}
                        disabled={page >= totalPages}
                        className="w-9 h-9 rounded-lg border border-white/10 text-gray-400 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center"
                    >
                        <i className="fas fa-chevron-right text-xs" />
                    </button>
                </div>
            )}
        </div>
    );
}
