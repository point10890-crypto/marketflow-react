import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { communityAPI, API_BASE, type CommunityPost, type CommunityComment } from '@/lib/api';
import DOMPurify from 'dompurify';
import FormulaPurchaseSection from './FormulaPurchaseSection';

function tierBadge(tier: string) {
    if (tier === 'premium') return { text: 'P', cls: 'bg-purple-500/25 text-purple-300' };
    if (tier === 'pro') return { text: 'Pro', cls: 'bg-indigo-500/25 text-indigo-300' };
    return null;
}

function formatDate(dateStr: string) {
    const d = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMin < 1) return '방금 전';
    if (diffMin < 60) return `${diffMin}분 전`;
    if (diffHours < 24) return `${diffHours}시간 전`;
    if (diffDays < 7) return `${diffDays}일 전`;
    return d.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })
        + ' ' + d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
}

// ── Comment Section ──

function CommentSection({ postId }: { postId: number }) {
    const { user } = useAuth();
    const [comments, setComments] = useState<CommunityComment[]>([]);
    const [content, setContent] = useState('');
    const [editingId, setEditingId] = useState<number | null>(null);
    const [editContent, setEditContent] = useState('');
    const [submitting, setSubmitting] = useState(false);

    const fetchComments = useCallback(() => {
        communityAPI.getComments(postId).then(setComments).catch(() => {});
    }, [postId]);

    useEffect(() => { fetchComments(); }, [fetchComments]);

    const handleSubmit = async () => {
        if (!content.trim() || submitting) return;
        setSubmitting(true);
        try {
            await communityAPI.createComment(postId, { content: content.trim() });
            setContent('');
            fetchComments();
        } catch { /* ignore */ }
        setSubmitting(false);
    };

    const handleUpdate = async (commentId: number) => {
        if (!editContent.trim() || submitting) return;
        setSubmitting(true);
        try {
            await communityAPI.updateComment(commentId, { content: editContent.trim() });
            setEditingId(null);
            setEditContent('');
            fetchComments();
        } catch { /* ignore */ }
        setSubmitting(false);
    };

    const handleDelete = async (commentId: number) => {
        if (!confirm('댓글을 삭제하시겠습니까?')) return;
        try {
            await communityAPI.deleteComment(commentId);
            fetchComments();
        } catch { /* ignore */ }
    };

    return (
        <div className="mt-6 md:mt-8">
            {/* Comment header */}
            <div className="flex items-center gap-2 mb-4 px-1">
                <i className="far fa-comment text-gray-500 text-sm" />
                <span className="text-white font-bold text-sm">댓글</span>
                {comments.length > 0 && (
                    <span className="text-[#2997ff] text-sm font-medium">{comments.length}</span>
                )}
            </div>

            {/* Write comment - top */}
            {user && (
                <div className="bg-white/[0.03] border border-white/[0.06] rounded-2xl p-3 md:p-4 mb-4">
                    <textarea
                        value={content}
                        onChange={e => setContent(e.target.value)}
                        placeholder="댓글을 입력하세요..."
                        className="w-full bg-transparent text-white text-sm placeholder-gray-600 focus:outline-none resize-none leading-relaxed"
                        rows={2}
                        onKeyDown={e => {
                            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit();
                        }}
                    />
                    <div className="flex items-center justify-between mt-2 pt-2 border-t border-white/[0.04]">
                        <span className="text-gray-700 text-xs">Ctrl+Enter로 등록</span>
                        <button
                            onClick={handleSubmit}
                            disabled={!content.trim() || submitting}
                            className="bg-[#2997ff] hover:bg-[#2997ff]/85 text-white font-bold text-xs rounded-lg px-4 py-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed active:scale-95"
                        >
                            등록
                        </button>
                    </div>
                </div>
            )}

            {/* Comment list */}
            <div className="space-y-0 divide-y divide-white/[0.04]">
                {comments.map(c => {
                    const badge = tierBadge(c.author.tier);
                    const isEditing = editingId === c.id;

                    return (
                        <div key={c.id} className="py-4 first:pt-0">
                            <div className="flex items-center gap-2 mb-2">
                                <div className="w-7 h-7 rounded-full bg-white/[0.06] flex items-center justify-center text-[11px] font-bold text-gray-400 flex-shrink-0">
                                    {c.author.name.charAt(0)}
                                </div>
                                <span className="text-white text-sm font-medium">{c.author.name}</span>
                                {badge && (
                                    <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${badge.cls}`}>{badge.text}</span>
                                )}
                                <span className="text-gray-600 text-xs ml-auto">{formatDate(c.created_at)}</span>
                            </div>

                            {isEditing ? (
                                <div className="ml-9">
                                    <textarea
                                        value={editContent}
                                        onChange={e => setEditContent(e.target.value)}
                                        className="w-full bg-white/5 border border-white/10 text-white text-sm rounded-xl px-3 py-2.5 focus:border-[#2997ff] focus:outline-none resize-none"
                                        rows={3}
                                    />
                                    <div className="flex gap-2 mt-2">
                                        <button onClick={() => handleUpdate(c.id)} disabled={submitting}
                                            className="text-xs bg-[#2997ff] text-white font-bold rounded-lg px-3 py-1.5 disabled:opacity-50">
                                            수정
                                        </button>
                                        <button onClick={() => { setEditingId(null); setEditContent(''); }}
                                            className="text-xs text-gray-400 hover:text-white px-3 py-1.5">
                                            취소
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <div className="ml-9">
                                    <p className="text-gray-300 text-sm whitespace-pre-wrap leading-relaxed">{c.content}</p>
                                    {user && (user.id === c.author.id || user.role === 'admin') && (
                                        <div className="flex gap-3 mt-2">
                                            <button onClick={() => { setEditingId(c.id); setEditContent(c.content); }}
                                                className="text-xs text-gray-600 hover:text-gray-300 transition-colors">수정</button>
                                            <button onClick={() => handleDelete(c.id)}
                                                className="text-xs text-gray-600 hover:text-red-400 transition-colors">삭제</button>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    );
                })}

                {comments.length === 0 && (
                    <p className="text-gray-700 text-sm text-center py-8">첫 댓글을 남겨보세요.</p>
                )}
            </div>
        </div>
    );
}

// ── Post Detail Page ──

export default function PostDetailPage() {
    const { postId } = useParams<{ postId: string }>();
    const { user } = useAuth();
    const navigate = useNavigate();

    const [post, setPost] = useState<CommunityPost | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        if (!postId) return;
        communityAPI.getPost(Number(postId))
            .then(data => setPost(data.post))
            .catch(err => setError(err.message || '게시글을 불러올 수 없습니다.'))
            .finally(() => setLoading(false));
    }, [postId]);

    const handleDelete = async () => {
        if (!post || !confirm('게시글을 삭제하시겠습니까?')) return;
        try {
            await communityAPI.deletePost(post.id);
            navigate(post.board ? `/dashboard/community/${post.board.slug}` : '/dashboard/community');
        } catch { alert('삭제에 실패했습니다.'); }
    };

    const handleToggleNotice = async () => {
        if (!post) return;
        try {
            const result = await communityAPI.toggleNotice(post.id);
            setPost(prev => prev ? { ...prev, is_notice: result.is_notice } : null);
        } catch { alert('공지 설정에 실패했습니다.'); }
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-[60vh]">
                <div className="w-8 h-8 border-2 border-[#2997ff] border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (error || !post) {
        return (
            <div className="p-4 md:p-6">
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">
                    {error || '게시글을 찾을 수 없습니다.'}
                </div>
            </div>
        );
    }

    const badge = tierBadge(post.author.tier);
    const canEdit = post.is_mine || user?.role === 'admin';
    const isAdmin = user?.role === 'admin';
    const isFormulaPost = post.board?.slug === 'formula-market';

    return (
        <div className="p-4 md:p-6 lg:py-8 lg:px-10">
            {/* Back nav */}
            <div className="mb-5">
                {post.board ? (
                    <Link
                        to={`/dashboard/community/${post.board.slug}`}
                        className="inline-flex items-center gap-2 text-gray-500 hover:text-white transition-colors text-sm group"
                    >
                        <i className="fas fa-arrow-left text-xs group-hover:-translate-x-0.5 transition-transform" />
                        {post.board.name}
                    </Link>
                ) : (
                    <button onClick={() => navigate(-1)}
                        className="text-gray-500 hover:text-white transition-colors text-sm flex items-center gap-2">
                        <i className="fas fa-arrow-left text-xs" />뒤로
                    </button>
                )}
            </div>

            {/* Post card */}
            <article className="bg-[#1c1c1e]/80 border border-white/[0.06] rounded-2xl overflow-hidden">
                {/* Header */}
                <div className="px-5 md:px-7 pt-5 md:pt-7 pb-5 border-b border-white/[0.04]">
                    {/* Notice */}
                    {post.is_notice && (
                        <span className="inline-block bg-amber-500/15 text-amber-400 text-[10px] px-2 py-0.5 rounded-full font-bold mb-3">
                            <i className="fas fa-thumbtack mr-1" />공지
                        </span>
                    )}

                    {/* Title */}
                    <h1 className="text-lg md:text-xl font-bold text-white mb-4 leading-snug">{post.title}</h1>

                    {/* Author info */}
                    <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-full bg-white/[0.06] flex items-center justify-center text-sm font-bold text-gray-400">
                            {post.author.name.charAt(0)}
                        </div>
                        <div className="flex-1">
                            <div className="flex items-center gap-1.5">
                                <span className="text-white text-sm font-medium">{post.author.name}</span>
                                {badge && (
                                    <span className={`text-[9px] px-1.5 py-0.5 rounded font-bold ${badge.cls}`}>{badge.text}</span>
                                )}
                            </div>
                            <div className="flex items-center gap-2 text-xs text-gray-600 mt-0.5">
                                <span>{formatDate(post.created_at)}</span>
                                <span className="text-gray-700">·</span>
                                <span>조회 {post.view_count}</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Content */}
                <div className="px-5 md:px-7 py-6 md:py-8">
                    <div
                        className="prose prose-invert prose-sm max-w-none text-gray-300 leading-relaxed
                            prose-headings:text-white prose-a:text-[#2997ff] prose-strong:text-white
                            prose-code:text-pink-400 prose-code:bg-white/5 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded
                            prose-pre:bg-white/5 prose-pre:border prose-pre:border-white/10 prose-pre:rounded-xl
                            prose-img:rounded-xl prose-img:border prose-img:border-white/10 prose-img:max-w-full"
                        dangerouslySetInnerHTML={{
                            __html: (() => {
                                let html = DOMPurify.sanitize(post.content || '', {
                                    ADD_TAGS: ['img'],
                                    ADD_ATTR: ['target', 'rel', 'src', 'alt', 'href'],
                                });
                                // 배포 환경: 상대 경로 이미지를 API 서버 절대 경로로 변환
                                if (API_BASE) {
                                    html = html.replace(/src="\/api\//g, `src="${API_BASE}/api/`);
                                }
                                return html;
                            })(),
                        }}
                    />
                </div>

                {/* Formula Purchase Section */}
                {isFormulaPost && <FormulaPurchaseSection post={post} />}

                {/* Actions */}
                {(canEdit || isAdmin) && (
                    <div className="flex items-center gap-1 px-5 md:px-7 py-3 border-t border-white/[0.04] bg-white/[0.01]">
                        {canEdit && (
                            <>
                                <button onClick={() => navigate(`/dashboard/community/post/${post.id}/edit`)}
                                    className="text-xs text-gray-500 hover:text-white transition-colors flex items-center gap-1.5 px-3 py-2 rounded-lg hover:bg-white/[0.05]">
                                    <i className="fas fa-pen text-[10px]" />수정
                                </button>
                                <button onClick={handleDelete}
                                    className="text-xs text-gray-500 hover:text-red-400 transition-colors flex items-center gap-1.5 px-3 py-2 rounded-lg hover:bg-white/[0.05]">
                                    <i className="fas fa-trash text-[10px]" />삭제
                                </button>
                            </>
                        )}
                        {isAdmin && (
                            <button onClick={handleToggleNotice}
                                className="text-xs text-gray-500 hover:text-amber-400 transition-colors flex items-center gap-1.5 px-3 py-2 rounded-lg hover:bg-white/[0.05] ml-auto">
                                <i className="fas fa-thumbtack text-[10px]" />
                                {post.is_notice ? '공지 해제' : '공지 고정'}
                            </button>
                        )}
                    </div>
                )}
            </article>

            {/* Comments */}
            <CommentSection postId={post.id} />
        </div>
    );
}
