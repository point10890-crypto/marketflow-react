import { Link } from 'react-router-dom';
import type { CommunityPost } from '@/lib/api';

interface PostCardProps {
    post: CommunityPost;
    boardSlug: string;
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

export default function PostCard({ post, boardSlug }: PostCardProps) {
    const isNotice = post.is_notice;

    return (
        <Link
            to={`/dashboard/community/post/${post.id}`}
            className={`block px-4 py-3 border-b border-white/10 hover:bg-white/5 transition-colors ${
                isNotice ? 'border-l-2 border-l-amber-500/60 bg-amber-500/5' : ''
            }`}
        >
            <div className="flex items-center justify-between gap-4">
                {/* Left: title + meta */}
                <div className="min-w-0 flex-1">
                    <p className="text-white font-semibold truncate text-sm">
                        {isNotice && <span className="mr-1">📌</span>}
                        {post.title}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-gray-500">{post.author.name}</span>
                        {tierDot(post.author.tier)}
                        <span className="text-xs text-gray-600">{relativeTime(post.created_at)}</span>
                    </div>
                </div>

                {/* Right: counts */}
                <div className="flex items-center gap-3 shrink-0 text-xs text-gray-500">
                    <span className="flex items-center gap-1">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                            <path d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        </svg>
                        {post.view_count}
                    </span>
                    <span className="flex items-center gap-1">
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                        </svg>
                        {post.comment_count}
                    </span>
                </div>
            </div>
        </Link>
    );
}
