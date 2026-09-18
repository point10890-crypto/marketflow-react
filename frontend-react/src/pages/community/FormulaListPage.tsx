import './community-design.css';
import { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { communityAPI, type CommunityPost, type PostListResponse } from '@/lib/api';
import { FORMULA_BOARDS, type FormulaBoardConfig } from '@/lib/formulaBoards';

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

function FormulaCard({ post, board }: { post: CommunityPost; board: FormulaBoardConfig }) {
    const preview = stripHtml(post.content);
    const priceText = board.fixedPrice != null ? board.fixedPrice.toLocaleString() : formatPrice(post.price);

    return (
        <Link
            to={`/dashboard/community/post/${post.id}`}
            className={`group relative dash-panel bg-[#15191e] border border-[#30363f] rounded-xl p-5 md:p-6 transition-all duration-200 ${board.accentBorderHover} flex flex-col`}
        >
            {/* Notice badge */}
            {post.is_notice && (
                <span className="absolute top-3 right-3 bg-amber-500/15 text-amber-400 text-[10px] font-bold px-2 py-0.5 rounded-full">
                    공지
                </span>
            )}

            {/* Icon badge */}
            <div className={`w-11 h-11 rounded-xl bg-gradient-to-br ${board.iconGradient} flex items-center justify-center mb-4`}>
                <i className={`fas ${board.iconClass} ${board.accentText} text-base`} />
            </div>

            {/* Title */}
            <h3 className="text-white font-semibold text-[15px] leading-snug line-clamp-2 mb-2 group-hover:opacity-90 transition-opacity">
                {post.title}
            </h3>

            {/* Preview */}
            {preview && (
                <p className="text-[#a6afbb] text-xs leading-relaxed line-clamp-2 mb-4 flex-1">
                    {preview}
                </p>
            )}
            {!preview && <div className="flex-1" />}

            {/* Divider */}
            <div className="border-t border-white/[0.05] pt-3 mt-auto">
                {/* Price + Date */}
                <div className="flex items-center justify-between mb-3">
                    <span className={`${board.accentText} font-bold text-base`}>
                        {priceText}
                        <span className="opacity-60 text-xs font-normal ml-0.5">원</span>
                        {board.fixedPrice != null && (
                            <span className="ml-1.5 rounded-full bg-white/[0.08] px-1.5 py-0.5 text-[9px] font-bold text-gray-300 align-middle">균일가</span>
                        )}
                    </span>
                    <span className="text-[#a6afbb] text-[11px]">
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

export default function FormulaListPage({ boardSlug = 'formula-market' }: { boardSlug?: string }) {
    const { user } = useAuth();
    const navigate = useNavigate();
    const board = FORMULA_BOARDS[boardSlug] ?? FORMULA_BOARDS['formula-market'];
    const basePath = `/dashboard/community/${board.slug}`;

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
            const data: PostListResponse = await communityAPI.getPosts(board.slug, p);
            setPosts([...(data.notices || []), ...data.posts]);
            setTotal(data.total);
            setTotalPages(data.total_pages);
            setPage(data.page);
        } catch (err: any) {
            setError(err.message || '목록을 불러올 수 없습니다.');
        } finally {
            setLoading(false);
        }
    }, [board.slug]);

    useEffect(() => { fetchPosts(1); }, [fetchPosts]);

    const handleSearch = () => {
        if (!searchQuery.trim()) {
            fetchPosts(1);
            return;
        }
        communityAPI.search(searchQuery, board.slug, 1)
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
                <div className="w-8 h-8 border-2 border-current border-t-transparent rounded-full animate-spin opacity-70" />
            </div>
        );
    }

    return (
        <div className="community-workspace p-4 md:p-6 lg:py-6 lg:px-8">
            {/* Header */}
            <div className="dash-page-header flex flex-wrap items-center justify-between gap-3 mb-6">
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => navigate('/dashboard/community')}
                        aria-label="커뮤니티로 돌아가기"
                        className="w-8 h-8 rounded-lg bg-white/[0.06] flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
                    >
                        <i className="fas fa-arrow-left text-sm" />
                    </button>
                    <div>
                        <div className="flex items-center gap-2.5">
                            <h1 className={`text-xl md:text-2xl font-bold ${board.accentText}`}>{board.title}</h1>
                            {board.fixedPrice != null && (
                                <span className={`bg-white/[0.06] ${board.accentText} text-[11px] font-black px-2 py-0.5 rounded-full`}>
                                    {board.fixedPrice.toLocaleString()}원 균일가
                                </span>
                            )}
                            {total > 0 && (
                                <span className={`bg-white/[0.06] ${board.accentText} text-[11px] font-bold px-2 py-0.5 rounded-full`}>
                                    {total}개
                                </span>
                            )}
                        </div>
                        <p className="text-[#a6afbb] text-xs mt-0.5 hidden sm:block">{board.subtitle}</p>
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
                            onClick={() => navigate(`${basePath}/write`)}
                            className={`${board.accentBg} text-black font-bold text-sm rounded-xl px-5 py-2.5 transition-colors flex items-center gap-2 flex-shrink-0 `}
                        >
                            <i className="fas fa-pen text-xs" />
                            <span className="hidden sm:inline">{board.writeLabel}</span>
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
            <div className="dash-toolbar dash-panel bg-[#15191e] border border-[#30363f] rounded-xl p-4 md:p-5 mb-5">
                <div className="flex items-center gap-3">
                    <i className="fas fa-search text-[#a6afbb] text-sm" />
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
                        className="text-gray-400 hover:text-white transition-colors text-sm"
                    >
                        검색
                    </button>
                </div>
            </div>

            {/* Card Grid */}
            {posts.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {posts.map(post => (
                        <FormulaCard key={post.id} post={post} board={board} />
                    ))}
                </div>
            ) : (
                <div className="dash-panel bg-[#15191e] border border-[#30363f] rounded-xl text-center py-20">
                    <div className={`w-16 h-16 rounded-2xl bg-gradient-to-br ${board.iconGradient} flex items-center justify-center mx-auto mb-4`}>
                        <i className={`fas ${board.iconClass} text-2xl text-[#a6afbb]`} />
                    </div>
                    <p className="text-[#a6afbb] text-sm mb-1">{board.emptyTitle}</p>
                    <p className="text-[#a6afbb] text-xs">{board.emptyHint}</p>
                    {isAdmin && (
                        <button
                            onClick={() => navigate(`${basePath}/write`)}
                            className={`mt-5 ${board.accentText} text-sm font-medium hover:underline`}
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
