import { useState } from 'react';
import { communityAPI, type CommunityComment } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';

interface CommentItemProps {
    comment: CommunityComment;
    isReply?: boolean;
    onReply: (parentId: number) => void;
    onRefresh: () => void;
}

function relativeTime(dateStr: string): string {
    const now = new Date();
    const date = new Date(dateStr);
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return '방금';
    if (diffMin < 60) return `${diffMin}분 전`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}시간 전`;
    const diffDay = Math.floor(diffHr / 24);
    if (diffDay < 7) return `${diffDay}일 전`;
    return date.toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' });
}

function tierDot(tier: string) {
    const color =
        tier === 'pro' ? 'bg-indigo-500' :
        tier === 'premium' ? 'bg-purple-500' :
        'bg-gray-500';
    return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}

export default function CommentItem({ comment, isReply, onReply, onRefresh }: CommentItemProps) {
    const { user, isAdmin } = useAuth();
    const [editing, setEditing] = useState(false);
    const [editContent, setEditContent] = useState(comment.content);

    const isMine = user && (Number(user.id) === comment.author.id);
    const canManage = isMine || isAdmin();

    if (comment.is_hidden) {
        return (
            <div className={`py-3 px-4 ${isReply ? 'ml-8' : ''}`}>
                <p className="text-gray-600 text-sm italic">삭제된 댓글입니다</p>
            </div>
        );
    }

    const handleSave = async () => {
        const trimmed = editContent.trim();
        if (!trimmed) return;
        try {
            await communityAPI.updateComment(comment.id, { content: trimmed });
            setEditing(false);
            onRefresh();
        } catch {
            /* silent */
        }
    };

    const handleDelete = async () => {
        if (!confirm('댓글을 삭제하시겠습니까?')) return;
        try {
            await communityAPI.deleteComment(comment.id);
            onRefresh();
        } catch {
            /* silent */
        }
    };

    return (
        <div className={`py-3 px-4 ${isReply ? 'ml-8 border-l border-white/5' : ''}`}>
            {/* Header */}
            <div className="flex items-center gap-2 mb-1">
                <span className={`font-medium ${isReply ? 'text-xs' : 'text-sm'} text-white`}>
                    {comment.author.name}
                </span>
                {tierDot(comment.author.tier)}
                <span className="text-xs text-gray-600">{relativeTime(comment.created_at)}</span>
            </div>

            {/* Content */}
            {editing ? (
                <div className="mt-1">
                    <textarea
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        rows={3}
                        className="w-full bg-white/5 border border-white/10 text-white rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:border-[#2997ff]/50"
                    />
                    <div className="flex gap-2 mt-1">
                        <button
                            onClick={handleSave}
                            className="text-xs text-[#2997ff] hover:underline"
                        >
                            저장
                        </button>
                        <button
                            onClick={() => { setEditing(false); setEditContent(comment.content); }}
                            className="text-xs text-gray-500 hover:text-white"
                        >
                            취소
                        </button>
                    </div>
                </div>
            ) : (
                <p className={`text-gray-300 whitespace-pre-wrap ${isReply ? 'text-xs' : 'text-sm'}`}>
                    {comment.content}
                </p>
            )}

            {/* Actions */}
            {!editing && (
                <div className="flex items-center gap-3 mt-1.5">
                    <button
                        onClick={() => onReply(comment.id)}
                        className="text-xs text-gray-500 hover:text-[#2997ff] transition-colors"
                    >
                        답글
                    </button>
                    {canManage && (
                        <>
                            <button
                                onClick={() => setEditing(true)}
                                className="text-xs text-gray-500 hover:text-white transition-colors"
                            >
                                수정
                            </button>
                            <button
                                onClick={handleDelete}
                                className="text-xs text-gray-500 hover:text-red-400 transition-colors"
                            >
                                삭제
                            </button>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
