import { useState, useEffect, useCallback } from 'react';
import { communityAPI, type CommunityComment } from '@/lib/api';
import CommentItem from './CommentItem';

interface CommentSectionProps {
    postId: number;
}

export default function CommentSection({ postId }: CommentSectionProps) {
    const [comments, setComments] = useState<CommunityComment[]>([]);
    const [content, setContent] = useState('');
    const [replyTo, setReplyTo] = useState<number | null>(null);
    const [submitting, setSubmitting] = useState(false);

    const fetchComments = useCallback(async () => {
        try {
            const data = await communityAPI.getComments(postId);
            setComments(data);
        } catch {
            /* silent */
        }
    }, [postId]);

    useEffect(() => {
        fetchComments();
    }, [fetchComments]);

    const topLevel = comments.filter((c) => c.parent_id === null);
    const getReplies = (parentId: number) =>
        comments.filter((c) => c.parent_id === parentId);

    const handleSubmit = async () => {
        const trimmed = content.trim();
        if (!trimmed || submitting) return;
        setSubmitting(true);
        try {
            await communityAPI.createComment(postId, {
                content: trimmed,
                parent_id: replyTo ?? undefined,
            });
            setContent('');
            setReplyTo(null);
            await fetchComments();
        } catch {
            /* silent */
        } finally {
            setSubmitting(false);
        }
    };

    const handleReply = (parentId: number) => {
        setReplyTo(parentId);
        const ta = document.getElementById('comment-input');
        if (ta) ta.focus();
    };

    const replyTarget = replyTo
        ? comments.find((c) => c.id === replyTo)
        : null;

    return (
        <div className="mt-8">
            <h3 className="text-white font-semibold mb-4">
                댓글 {comments.length > 0 && <span className="text-[#2997ff]">{comments.length}</span>}
            </h3>

            {/* Comment input */}
            <div className="mb-6">
                {replyTarget && (
                    <div className="flex items-center gap-2 mb-2 text-xs text-gray-400">
                        <span>@{replyTarget.author.name} 에게 답글</span>
                        <button
                            onClick={() => setReplyTo(null)}
                            className="text-gray-500 hover:text-white"
                        >
                            취소
                        </button>
                    </div>
                )}
                <textarea
                    id="comment-input"
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    placeholder="댓글을 입력하세요..."
                    rows={3}
                    className="w-full bg-white/5 border border-white/10 text-white rounded-xl px-4 py-3 text-sm placeholder-gray-600 resize-none focus:outline-none focus:border-[#2997ff]/50"
                />
                <div className="flex justify-end mt-2">
                    <button
                        onClick={handleSubmit}
                        disabled={!content.trim() || submitting}
                        className="px-4 py-1.5 bg-[#2997ff] text-white text-sm rounded-lg font-medium disabled:opacity-40 hover:bg-[#2997ff]/80 transition-colors"
                    >
                        {submitting ? '등록 중...' : '등록'}
                    </button>
                </div>
            </div>

            {/* Comment list */}
            <div className="space-y-1">
                {topLevel.map((comment) => (
                    <div key={comment.id}>
                        <CommentItem
                            comment={comment}
                            onReply={handleReply}
                            onRefresh={fetchComments}
                        />
                        {getReplies(comment.id).map((reply) => (
                            <CommentItem
                                key={reply.id}
                                comment={reply}
                                isReply
                                onReply={handleReply}
                                onRefresh={fetchComments}
                            />
                        ))}
                    </div>
                ))}
                {comments.length === 0 && (
                    <p className="text-gray-600 text-sm text-center py-8">
                        아직 댓글이 없습니다. 첫 댓글을 남겨보세요.
                    </p>
                )}
            </div>
        </div>
    );
}
