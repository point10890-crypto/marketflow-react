import { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { communityAPI, type CommunityPost, type PostListResponse } from '@/lib/api';

function formatKoreanDate(dateStr: string) {
    const d = new Date(dateStr);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const h = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    return `${y}년${m}월${day}일 ${h}시${min}분${s}초`;
}

function formatPrice(price?: string) {
    if (!price) return '-';
    const num = parseInt(price.replace(/[^0-9]/g, ''), 10);
    if (isNaN(num)) return price;
    return num.toLocaleString();
}

export default function FormulaListPage() {
    const { user } = useAuth();
    const navigate = useNavigate();

    const [posts, setPosts] = useState<CommunityPost[]>([]);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [searchQuery, setSearchQuery] = useState('');

    const isAdmin = user?.role === 'admin';

    const fetchPosts = useCallback(async (p: number) => {
        setLoading(true);
        setError('');
        try {
            const data: PostListResponse = await communityAPI.getPosts('formula-market', p);
            setPosts([...(data.notices || []), ...data.posts]);
            setTotalPages(data.total_pages);
            setPage(data.page);
        } catch (err: any) {
            setError(err.message || '목록을 불러올 수 없습니다.');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { fetchPosts(1); }, [fetchPosts]);

    const handleSearch = () => {
        if (!searchQuery.trim()) {
            fetchPosts(1);
            return;
        }
        communityAPI.search(searchQuery, 'formula-market', 1)
            .then(data => {
                setPosts(data.posts);
                setTotalPages(data.total_pages);
                setPage(1);
            })
            .catch(() => {});
    };

    const filteredPosts = posts;

    if (loading && posts.length === 0) {
        return (
            <div className="flex items-center justify-center min-h-[60vh]">
                <div className="w-8 h-8 border-2 border-[#2997ff] border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    return (
        <div className="p-4 md:p-6 lg:py-8 lg:px-10">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => navigate('/dashboard/community')}
                        className="w-8 h-8 rounded-lg bg-white/[0.06] flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
                    >
                        <i className="fas fa-arrow-left text-sm" />
                    </button>
                    <h1 className="text-xl md:text-2xl font-bold text-yellow-400">수식 목록</h1>
                </div>

                {isAdmin && (
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => navigate('/dashboard/community/formula-market/purchases')}
                            className="bg-white/[0.06] hover:bg-white/10 text-gray-300 font-bold text-sm rounded-xl px-4 py-2.5 transition-colors flex items-center gap-2 flex-shrink-0 border border-white/10"
                        >
                            <i className="fas fa-receipt text-xs" />
                            <span className="hidden sm:inline">구매 내역</span>
                        </button>
                        <button
                            onClick={() => navigate('/dashboard/community/formula-market/write')}
                            className="bg-yellow-500 hover:bg-yellow-500/85 text-black font-bold text-sm rounded-xl px-5 py-2.5 transition-colors flex items-center gap-2 flex-shrink-0 active:scale-95"
                        >
                            <i className="fas fa-pen text-xs" />
                            <span className="hidden sm:inline">수식 등록</span>
                        </button>
                    </div>
                )}
            </div>

            {error && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 text-red-400 text-sm mb-4">
                    {error}
                </div>
            )}

            {/* Search */}
            <div className="bg-[#1c1c1e]/80 border border-white/[0.06] rounded-2xl p-4 md:p-5 mb-5">
                <div className="flex items-center gap-3">
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleSearch()}
                        placeholder="제목을 입력하세요."
                        className="flex-1 bg-transparent text-white placeholder-gray-600 focus:outline-none text-sm"
                    />
                    <button
                        onClick={handleSearch}
                        className="text-gray-400 hover:text-yellow-400 transition-colors"
                    >
                        <i className="fas fa-search" />
                    </button>
                </div>
            </div>

            {/* Table */}
            <div className="bg-[#1c1c1e]/80 border border-white/[0.06] rounded-2xl overflow-hidden">
                {/* Desktop Table */}
                <div className="hidden md:block overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-white/[0.06] bg-white/[0.03]">
                                <th className="px-5 py-3.5 text-center font-bold text-gray-300 w-[40%]">수식명</th>
                                <th className="px-4 py-3.5 text-center font-bold text-gray-300 w-[12%]">금액</th>
                                <th className="px-4 py-3.5 text-center font-bold text-gray-300 w-[20%]">등록일</th>
                                <th className="px-4 py-3.5 text-center font-bold text-gray-300 w-[6%]">상태</th>
                                <th className="px-4 py-3.5 text-center font-bold text-gray-300 w-[22%]">비고</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/[0.04]">
                            {filteredPosts.map(post => (
                                <tr key={post.id} className="hover:bg-white/[0.02] transition-colors">
                                    <td className="px-5 py-3.5 text-center">
                                        <Link
                                            to={`/dashboard/community/post/${post.id}`}
                                            className="text-[#2997ff] hover:text-[#2997ff]/80 underline transition-colors"
                                        >
                                            {post.title}
                                        </Link>
                                    </td>
                                    <td className="px-4 py-3.5 text-center text-gray-300">
                                        {formatPrice(post.price)}
                                    </td>
                                    <td className="px-4 py-3.5 text-center text-gray-400 text-xs">
                                        {formatKoreanDate(post.created_at)}
                                    </td>
                                    <td className="px-4 py-3.5 text-center text-gray-500">-</td>
                                    <td className="px-4 py-3.5 text-gray-400 text-xs">
                                        구매하시려면 제목을 클릭해 상세내용 확인 후 진행해주세요.
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                {/* Mobile Cards */}
                <div className="md:hidden divide-y divide-white/[0.04]">
                    {filteredPosts.map(post => (
                        <Link
                            key={post.id}
                            to={`/dashboard/community/post/${post.id}`}
                            className="block px-4 py-4 hover:bg-white/[0.03] transition-colors"
                        >
                            <h3 className="text-[#2997ff] text-sm font-medium mb-2 underline">{post.title}</h3>
                            <div className="flex items-center gap-4 text-xs text-gray-500">
                                <span className="text-yellow-400 font-bold">
                                    {formatPrice(post.price)}원
                                </span>
                                <span>{formatKoreanDate(post.created_at)}</span>
                            </div>
                        </Link>
                    ))}
                </div>

                {/* Empty */}
                {filteredPosts.length === 0 && (
                    <div className="text-center py-16">
                        <i className="fas fa-calculator text-2xl text-gray-700 mb-3 block" />
                        <p className="text-gray-600 text-sm">등록된 수식이 없습니다.</p>
                        {isAdmin && (
                            <button
                                onClick={() => navigate('/dashboard/community/formula-market/write')}
                                className="mt-4 text-yellow-400 text-sm font-medium hover:underline"
                            >
                                첫 수식을 등록해 보세요
                            </button>
                        )}
                    </div>
                )}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-center gap-3 mt-6">
                    <button
                        onClick={() => fetchPosts(page - 1)}
                        disabled={page <= 1}
                        className="w-9 h-9 rounded-lg border border-white/10 text-gray-400 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center"
                    >
                        <i className="fas fa-chevron-left text-xs" />
                    </button>
                    <span className="text-gray-300 text-sm font-medium">
                        {page} / {totalPages}
                    </span>
                    <button
                        onClick={() => fetchPosts(page + 1)}
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
