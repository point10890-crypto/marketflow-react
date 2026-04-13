import { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { communityAPI, type CommunityPost, type PostListResponse } from '@/lib/api';

function formatPrice(price?: string) {
    if (!price) return '-';
    const num = parseInt(price.replace(/[^0-9]/g, ''), 10);
    if (isNaN(num)) return price;
    return num.toLocaleString();
}

function formatShortDate(dateStr: string) {
    const d = new Date(dateStr);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}.${m}.${day}`;
}

function stripHtml(html?: string) {
    if (!html) return '';
    const text = html.replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim();
    return text.length > 60 ? text.slice(0, 60) + '...' : text;
}

function FormulaCard({ post }: { post: CommunityPost }) {
    const preview = stripHtml(post.content);

    return (
        <Link
            to={`/dashboard/community/post/${post.id}`}
            className="group relative bg-[#1c1c1e]/80 border border-white/[0.06] rounded-2xl p-5 md:p-6 transition-all duration-200 hover:border-yellow-500/30 hover:shadow-lg hover:shadow-yellow-500/5 hover:-translate-y-0.5 flex flex-col"
        >
            {/* Notice badge */}
            {post.is_notice && (
                <span className="absolute top-3 right-3 bg-amber-500/15 text-amber-400 text-[10px] font-bold px-2 py-0.5 rounded-full">
                    공지
                </span>
            )}

            {/* Icon badge */}
            <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-yellow-500/20 to-amber-600/10 flex items-center justify-center mb-4">
                <i className="fas fa-square-root-variable text-yellow-400 text-base" />
            </div>

            {/* Title */}
            <h3 className="text-white font-semibold text-[15px] leading-snug line-clamp-2 mb-2 group-hover:text-yellow-300 transition-colors">
                {post.title}
            </h3>

            {/* Preview */}
            {preview && (
                <p className="text-gray-500 text-xs leading-relaxed line-clamp-2 mb-4 flex-1">
                    {preview}
                </p>
            )}
            {!preview && <div className="flex-1" />}

            {/* Divider */}
            <div className="border-t border-white/[0.05] pt-3 mt-auto">
                {/* Price + Date */}
                <div className="flex items-center justify-between mb-3">
                    <span className="text-yellow-400 font-bold text-base">
                        {formatPrice(post.price)}
                        <span className="text-yellow-400/60 text-xs font-normal ml-0.5">원</span>
                    </span>
                    <span className="text-gray-600 text-[11px]">
                        {formatShortDate(post.created_at)}
                    </span>
                </div>

                {/* CTA */}
                <span className="text-[#2997ff] text-sm font-medium group-hover:text-[#2997ff]/80 transition-colors flex items-center gap-1">
                    상세보기
                    <i className="fas fa-arrow-right text-[10px] transition-transform group-hover:translate-x-0.5" />
                </span>
            </div>
        </Link>
    );
}

export default function FormulaListPage() {
    const { user } = useAuth();
    const navigate = useNavigate();

    const [posts, setPosts] = useState<CommunityPost[]>([]);
    const [total, setTotal] = useState(0);
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
            setTotal(data.total);
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
                setTotal(data.total);
                setTotalPages(data.total_pages);
                setPage(1);
            })
            .catch(() => {});
    };

    if (loading && posts.length === 0) {
        return (
            <div className="flex items-center justify-center min-h-[60vh]">
                <div className="w-8 h-8 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin" />
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
                    <div>
                        <div className="flex items-center gap-2.5">
                            <h1 className="text-xl md:text-2xl font-bold text-yellow-400">수식 마켓</h1>
                            {total > 0 && (
                                <span className="bg-yellow-500/10 text-yellow-400 text-[11px] font-bold px-2 py-0.5 rounded-full">
                                    {total}개
                                </span>
                            )}
                        </div>
                        <p className="text-gray-500 text-xs mt-0.5 hidden sm:block">검증된 트레이딩 수식을 만나보세요</p>
                    </div>
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
                    <i className="fas fa-search text-gray-600 text-sm" />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleSearch()}
                        placeholder="수식을 검색하세요..."
                        className="flex-1 bg-transparent text-white placeholder-gray-600 focus:outline-none text-sm"
                    />
                    <button
                        onClick={handleSearch}
                        className="text-gray-400 hover:text-yellow-400 transition-colors text-sm"
                    >
                        검색
                    </button>
                </div>
            </div>

            {/* Card Grid */}
            {posts.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {posts.map(post => (
                        <FormulaCard key={post.id} post={post} />
                    ))}
                </div>
            ) : (
                <div className="bg-[#1c1c1e]/80 border border-white/[0.06] rounded-2xl text-center py-20">
                    <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-yellow-500/10 to-amber-600/5 flex items-center justify-center mx-auto mb-4">
                        <i className="fas fa-calculator text-2xl text-gray-600" />
                    </div>
                    <p className="text-gray-500 text-sm mb-1">아직 등록된 수식이 없습니다</p>
                    <p className="text-gray-600 text-xs">새로운 수식이 등록되면 여기에 표시됩니다</p>
                    {isAdmin && (
                        <button
                            onClick={() => navigate('/dashboard/community/formula-market/write')}
                            className="mt-5 text-yellow-400 text-sm font-medium hover:underline"
                        >
                            첫 수식을 등록해 보세요
                        </button>
                    )}
                </div>
            )}

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
