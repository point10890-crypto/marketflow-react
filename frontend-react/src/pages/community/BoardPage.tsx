import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { communityAPI, type CommunityBoard, type CommunityPost, type PostListResponse } from '@/lib/api';

function tierBadge(tier: string) {
    if (tier === 'premium') return { text: 'P', cls: 'bg-purple-500/25 text-purple-300' };
    if (tier === 'pro') return { text: 'Pro', cls: 'bg-indigo-500/25 text-indigo-300' };
    return null;
}

function relativeTime(dateStr: string) {
    const now = new Date();
    const date = new Date(dateStr);
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMin < 1) return '방금';
    if (diffMin < 60) return `${diffMin}분 전`;
    if (diffHours < 24) return `${diffHours}시간 전`;
    if (diffDays === 1) return '어제';
    if (diffDays < 7) return `${diffDays}일 전`;
    return date.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' });
}

export default function BoardPage() {
    const { boardSlug } = useParams<{ boardSlug: string }>();
    const { user } = useAuth();
    const navigate = useNavigate();

    const [board, setBoard] = useState<CommunityBoard | null>(null);
    const [posts, setPosts] = useState<CommunityPost[]>([]);
    const [notices, setNotices] = useState<CommunityPost[]>([]);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const fetchPosts = useCallback(async (p: number) => {
        if (!boardSlug) return;
        setLoading(true);
        setError('');
        try {
            const data: PostListResponse = await communityAPI.getPosts(boardSlug, p);
            setPosts(data.posts);
            if (p === 1) setNotices(data.notices || []);
            setTotalPages(data.total_pages);
            setTotal(data.total);
            setPage(data.page);
        } catch (err: any) {
            setError(err.message || '게시글을 불러올 수 없습니다.');
        } finally {
            setLoading(false);
        }
    }, [boardSlug]);

    useEffect(() => {
        if (!boardSlug) return;
        communityAPI.getBoards().then(boards => {
            const found = boards.find(b => b.slug === boardSlug);
            if (found) setBoard(found);
        });
    }, [boardSlug]);

    useEffect(() => { fetchPosts(1); }, [fetchPosts]);

    const canWrite = user && board && board.can_write;

    if (loading && posts.length === 0) {
        return (
            <div className="flex items-center justify-center min-h-[60vh]">
                <div className="w-8 h-8 border-2 border-[#2997ff] border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (error && posts.length === 0) {
        return (
            <div className="p-4 md:p-6">
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">{error}</div>
            </div>
        );
    }

    const renderPostRow = (post: CommunityPost, isNotice = false) => {
        const badge = tierBadge(post.author.tier);
        return (
            <Link
                key={post.id}
                to={`/dashboard/community/post/${post.id}`}
                className={`group flex items-center gap-3 md:gap-4 px-4 md:px-5 py-3.5 md:py-4 transition-colors hover:bg-white/[0.03] ${
                    isNotice ? 'bg-amber-500/[0.04] border-l-2 border-l-amber-400/60' : 'border-l-2 border-l-transparent'
                }`}
            >
                {/* Left: Avatar */}
                <div className="hidden md:flex w-9 h-9 rounded-full bg-white/[0.06] items-center justify-center flex-shrink-0 text-xs font-bold text-gray-400">
                    {post.author.name.charAt(0)}
                </div>

                {/* Center: Content */}
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                        {isNotice && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-bold flex-shrink-0">
                                공지
                            </span>
                        )}
                        <h3 className="text-white text-sm md:text-[15px] font-medium truncate group-hover:text-[#2997ff] transition-colors">
                            {post.title}
                        </h3>
                        {post.comment_count > 0 && (
                            <span className="text-[#2997ff]/70 text-xs font-medium flex-shrink-0">
                                [{post.comment_count}]
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                        <span className="flex items-center gap-1">
                            <span className="font-medium text-gray-400">{post.author.name}</span>
                            {badge && (
                                <span className={`text-[9px] px-1 py-px rounded font-bold ${badge.cls}`}>{badge.text}</span>
                            )}
                        </span>
                        <span className="text-gray-700">·</span>
                        <span>{relativeTime(post.created_at)}</span>
                    </div>
                </div>

                {/* Right: Stats */}
                <div className="hidden sm:flex items-center gap-4 flex-shrink-0 text-xs text-gray-600">
                    <span className="flex items-center gap-1">
                        <i className="far fa-eye" />{post.view_count}
                    </span>
                    <span className="flex items-center gap-1">
                        <i className="far fa-comment" />{post.comment_count}
                    </span>
                </div>
            </Link>
        );
    };

    return (
        <div className="p-4 md:p-6 lg:py-8 lg:px-10">
            {/* Header */}
            <div className="flex items-start md:items-center justify-between gap-4 mb-6">
                <div className="flex items-center gap-3">
                    <button
                        onClick={() => navigate('/dashboard/community')}
                        className="w-8 h-8 rounded-lg bg-white/[0.06] flex items-center justify-center text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
                    >
                        <i className="fas fa-arrow-left text-sm" />
                    </button>
                    <div>
                        <h1 className="text-xl md:text-2xl font-bold text-white">{board?.name || boardSlug}</h1>
                        {board?.description && (
                            <p className="text-gray-500 text-xs md:text-sm mt-0.5">{board.description}</p>
                        )}
                    </div>
                </div>

                {canWrite && (
                    <button
                        onClick={() => navigate(`/dashboard/community/${boardSlug}/write`)}
                        className="bg-[#2997ff] hover:bg-[#2997ff]/85 text-white font-bold text-sm rounded-xl px-5 py-2.5 transition-colors flex items-center gap-2 flex-shrink-0 active:scale-95"
                    >
                        <i className="fas fa-pen text-xs" />
                        <span className="hidden sm:inline">글쓰기</span>
                    </button>
                )}
            </div>

            {/* Stats bar */}
            <div className="flex items-center gap-4 mb-4 px-1 text-xs text-gray-500">
                <span>전체 <strong className="text-gray-300">{total + (notices?.length || 0)}</strong></span>
                {notices.length > 0 && <span>공지 <strong className="text-amber-400">{notices.length}</strong></span>}
            </div>

            {/* Post list */}
            <div className="bg-[#1c1c1e]/80 border border-white/[0.06] rounded-2xl overflow-hidden divide-y divide-white/[0.04]">
                {/* Table header - PC only */}
                <div className="hidden md:flex items-center px-5 py-2.5 text-[11px] text-gray-600 uppercase tracking-wider font-medium bg-white/[0.02]">
                    <span className="flex-1 pl-14">제목</span>
                    <div className="flex items-center gap-4 w-32 justify-end">
                        <span>조회</span>
                        <span>댓글</span>
                    </div>
                </div>

                {/* Notices */}
                {page === 1 && notices.map(post => renderPostRow(post, true))}

                {/* Regular posts */}
                {posts.map(post => renderPostRow(post))}

                {/* Empty */}
                {posts.length === 0 && notices.length === 0 && (
                    <div className="text-center py-16">
                        <i className="far fa-comment-dots text-2xl text-gray-700 mb-3 block" />
                        <p className="text-gray-600 text-sm">아직 게시글이 없습니다.</p>
                        {canWrite && (
                            <button
                                onClick={() => navigate(`/dashboard/community/${boardSlug}/write`)}
                                className="mt-4 text-[#2997ff] text-sm font-medium hover:underline"
                            >
                                첫 글을 작성해 보세요
                            </button>
                        )}
                    </div>
                )}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-center gap-1 mt-6">
                    <button
                        onClick={() => fetchPosts(page - 1)}
                        disabled={page <= 1}
                        className="w-9 h-9 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center"
                    >
                        <i className="fas fa-chevron-left text-xs" />
                    </button>
                    {Array.from({ length: totalPages }, (_, i) => i + 1)
                        .filter(p => p === 1 || p === totalPages || Math.abs(p - page) <= 2)
                        .reduce<(number | string)[]>((acc, p, idx, arr) => {
                            if (idx > 0 && p - (arr[idx - 1] as number) > 1) acc.push('...');
                            acc.push(p);
                            return acc;
                        }, [])
                        .map((item, idx) =>
                            item === '...' ? (
                                <span key={`e-${idx}`} className="px-1 text-gray-700 text-sm">...</span>
                            ) : (
                                <button
                                    key={item}
                                    onClick={() => fetchPosts(item as number)}
                                    className={`w-8 h-8 rounded-lg text-sm font-medium transition-colors ${
                                        item === page
                                            ? 'bg-[#2997ff] text-white'
                                            : 'text-gray-500 hover:text-white hover:bg-white/10'
                                    }`}
                                >
                                    {item}
                                </button>
                            )
                        )}
                    <button
                        onClick={() => fetchPosts(page + 1)}
                        disabled={page >= totalPages}
                        className="w-9 h-9 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors flex items-center justify-center"
                    >
                        <i className="fas fa-chevron-right text-xs" />
                    </button>
                </div>
            )}
        </div>
    );
}
