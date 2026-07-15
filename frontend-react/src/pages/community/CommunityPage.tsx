import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { communityAPI, type CommunityBoard } from '@/lib/api';

const BOARD_COLORS: Record<string, { bg: string; icon: string; glow: string }> = {
    notice:          { bg: 'from-amber-500/20 to-amber-600/5',   icon: 'text-amber-400',  glow: 'shadow-amber-500/10' },
    'free-talk':     { bg: 'from-blue-500/20 to-blue-600/5',     icon: 'text-blue-400',   glow: 'shadow-blue-500/10' },
    analysis:        { bg: 'from-emerald-500/20 to-emerald-600/5', icon: 'text-emerald-400', glow: 'shadow-emerald-500/10' },
    'trade-journal': { bg: 'from-violet-500/20 to-violet-600/5', icon: 'text-violet-400', glow: 'shadow-violet-500/10' },
    'pro-lounge':    { bg: 'from-indigo-500/20 to-indigo-600/5', icon: 'text-indigo-400', glow: 'shadow-indigo-500/10' },
    'formula-market': { bg: 'from-yellow-500/20 to-yellow-600/5', icon: 'text-yellow-400', glow: 'shadow-yellow-500/10' },
    'lotto-ai':      { bg: 'from-pink-500/20 to-pink-600/5',   icon: 'text-pink-400',   glow: 'shadow-pink-500/10' },
};

const BOARD_ICONS: Record<string, string> = {
    notice: 'fa-bullhorn',
    'free-talk': 'fa-comments',
    analysis: 'fa-chart-line',
    'trade-journal': 'fa-book-open',
    'pro-lounge': 'fa-crown',
    'formula-market': 'fa-calculator',
    'lotto-ai': 'fa-dice',
};

const BOARD_SEEN_STORAGE_KEY = 'marketflow.community.boardSeen.v1';
const NEW_POST_RECENT_WINDOW_MS = 48 * 60 * 60 * 1000;

function getLatestPostStamp(board: CommunityBoard) {
    if (!board.latest_post_at) return 0;
    const stamp = Date.parse(board.latest_post_at);
    return Number.isFinite(stamp) ? stamp : 0;
}

function readBoardSeenStamps(): Record<string, number> {
    try {
        const raw = window.localStorage.getItem(BOARD_SEEN_STORAGE_KEY);
        if (!raw) return {};
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
        return {};
    }
}

function writeBoardSeenStamps(value: Record<string, number>) {
    try {
        window.localStorage.setItem(BOARD_SEEN_STORAGE_KEY, JSON.stringify(value));
    } catch {
        // Storage can be unavailable in private or restricted browser contexts.
    }
}

function hasBoardSeenBaseline() {
    try {
        return window.localStorage.getItem(BOARD_SEEN_STORAGE_KEY) !== null;
    } catch {
        return false;
    }
}

function tierLabel(tier: string) {
    if (tier === 'pro') return { text: 'Pro', cls: 'bg-indigo-500/25 text-indigo-300 border-indigo-500/30' };
    if (tier === 'premium') return { text: 'Premium', cls: 'bg-purple-500/25 text-purple-300 border-purple-500/30' };
    return null;
}

export default function CommunityPage() {
    const { user } = useAuth();
    const navigate = useNavigate();
    const [boards, setBoards] = useState<CommunityBoard[]>([]);
    const [newBoards, setNewBoards] = useState<Record<string, boolean>>({});
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const loadBoards = useCallback(() => {
        setLoading(true);
        setError('');
        return communityAPI.getBoards()
            .then(data => {
                setBoards(data);

                const hasSeenBaseline = hasBoardSeenBaseline();
                const seenStamps = readBoardSeenStamps();
                const nextNewBoards: Record<string, boolean> = {};
                const now = Date.now();

                data.forEach(board => {
                    const latestStamp = getLatestPostStamp(board);
                    if (!latestStamp) return;
                    const seenStamp = Number(seenStamps[board.slug] || 0);
                    const recentlyUpdated = now - latestStamp <= NEW_POST_RECENT_WINDOW_MS;
                    if ((hasSeenBaseline && latestStamp > seenStamp) || (!hasSeenBaseline && recentlyUpdated)) {
                        nextNewBoards[board.slug] = true;
                    } else if (!hasSeenBaseline || !seenStamp) {
                        seenStamps[board.slug] = latestStamp;
                    }
                });

                if (!hasSeenBaseline || Object.keys(nextNewBoards).length > 0) {
                    writeBoardSeenStamps(seenStamps);
                }
                setNewBoards(nextNewBoards);
            })
            .catch(err => setError(err.message || '게시판 목록을 불러올 수 없습니다.'))
            .finally(() => setLoading(false));
    }, []);

    useEffect(() => {
        void loadBoards();
    }, [loadBoards]);

    const canAccess = (board: CommunityBoard) => {
        if (!user) return false;
        return board.can_read !== false;
    };

    const markBoardSeen = (board: CommunityBoard) => {
        const latestStamp = getLatestPostStamp(board);
        if (!latestStamp) return;
        const seenStamps = readBoardSeenStamps();
        seenStamps[board.slug] = latestStamp;
        writeBoardSeenStamps(seenStamps);
        setNewBoards(prev => ({ ...prev, [board.slug]: false }));
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-[60vh]">
                <div className="w-8 h-8 border-2 border-[#2997ff] border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-4 md:p-6">
                <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm">
                    <p>{error}</p>
                    <button
                        type="button"
                        onClick={() => void loadBoards()}
                        className="mt-3 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 font-semibold text-red-200 hover:bg-red-500/20"
                    >
                        다시 시도
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="p-4 md:p-6 lg:py-8 lg:px-10">
            {/* Header */}
            <div className="mb-8">
                <h1 className="text-2xl md:text-3xl font-bold text-white mb-2">커뮤니티</h1>
                <p className="text-gray-500 text-sm md:text-base">투자 인사이트를 공유하고, 함께 성장하는 공간</p>
            </div>

            {/* Board Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 md:gap-4">
                {boards.map(board => {
                    const locked = !canAccess(board);
                    const badge = tierLabel(board.min_tier);
                    const colors = BOARD_COLORS[board.slug] || BOARD_COLORS['free-talk'];
                    const iconClass = BOARD_ICONS[board.slug] || board.icon || 'fa-comments';
                    const isNew = Boolean(newBoards[board.slug]);

                    return (
                        <button
                            key={board.id}
                            onClick={() => {
                                if (locked) return;
                                markBoardSeen(board);
                                navigate(`/dashboard/community/${board.slug}`);
                            }}
                            disabled={locked}
                            className={`group text-left w-full rounded-2xl transition-all duration-200 overflow-hidden ${
                                locked
                                    ? 'opacity-40 cursor-not-allowed'
                                    : 'cursor-pointer hover:scale-[1.02] hover:shadow-lg active:scale-[0.98]'
                            } ${colors.glow}`}
                        >
                            <div className={`relative bg-gradient-to-br ${colors.bg} border border-white/[0.06] rounded-2xl p-5 md:p-6 h-full backdrop-blur-sm`}>
                                {isNew && (
                                    <span
                                        className="community-new-badge absolute right-14 top-6 rounded-full border border-rose-300/60 bg-rose-500 px-2.5 py-1 text-[10px] font-black tracking-[0.18em] text-white shadow-[0_0_18px_rgba(244,63,94,0.45)]"
                                        aria-label={`${board.name} new post`}
                                        title={board.latest_post_title || 'New post'}
                                    >
                                        NEW
                                    </span>
                                )}
                                {/* Icon + Badge row */}
                                <div className="flex items-center justify-between mb-4">
                                    <div className={`w-11 h-11 rounded-xl bg-white/[0.06] flex items-center justify-center ${
                                        locked ? '' : 'group-hover:bg-white/[0.1] transition-colors'
                                    }`}>
                                        {locked ? (
                                            <i className="fas fa-lock text-gray-600 text-sm" />
                                        ) : (
                                            <i className={`fas ${iconClass} ${colors.icon} text-lg`} />
                                        )}
                                    </div>
                                    {badge && (
                                        <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold ${badge.cls}`}>
                                            {badge.text}
                                        </span>
                                    )}
                                </div>

                                {/* Title */}
                                <h3 className={`font-bold text-[15px] md:text-base mb-1 ${
                                    board.slug === 'formula-market' ? 'text-yellow-400' : 'text-white'
                                }`}>{board.name}</h3>
                                <p className="text-gray-500 text-xs md:text-sm leading-relaxed line-clamp-2 mb-4">
                                    {board.description}
                                </p>

                                {/* Footer */}
                                <div className="flex items-center justify-between">
                                    <span className="text-gray-600 text-xs flex items-center gap-1.5">
                                        <i className="far fa-file-alt" />
                                        {board.post_count}개 글
                                    </span>
                                    {!locked && (
                                        <i className="fas fa-chevron-right text-gray-600 text-[10px] group-hover:text-gray-400 transition-colors" />
                                    )}
                                </div>
                            </div>
                        </button>
                    );
                })}
            </div>

            {boards.length === 0 && (
                <div className="text-center text-gray-600 py-20">
                    <i className="fas fa-inbox text-3xl mb-3 block" />
                    아직 게시판이 없습니다.
                </div>
            )}
        </div>
    );
}
