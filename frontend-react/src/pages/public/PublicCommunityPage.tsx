import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { publicCommunityAPI, PublicBoard, PublicPostSummary } from '@/lib/api';
import { AdSlot, PublicShell } from '@/components/public/PublicShell';

/**
 * 공개 커뮤니티 — 비로그인 열람 (/community, /community/:board).
 * 매일 자동 게시되는 분석 글이 심사 크롤러와 방문자에게 보이는 핵심 영역.
 */

const BOARD_ACCENT: Record<string, { text: string; bar: string; chip: string }> = {
    'notice': { text: 'text-amber-300', bar: 'bg-amber-400', chip: 'border-amber-400/30 bg-amber-500/10 text-amber-300' },
    'lotto-ai': { text: 'text-violet-300', bar: 'bg-violet-400', chip: 'border-violet-400/30 bg-violet-500/10 text-violet-300' },
    'analysis': { text: 'text-sky-300', bar: 'bg-sky-400', chip: 'border-sky-400/30 bg-sky-500/10 text-sky-300' },
    'free-talk': { text: 'text-emerald-300', bar: 'bg-emerald-400', chip: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300' },
};
const DEFAULT_ACCENT = { text: 'text-gray-300', bar: 'bg-gray-400', chip: 'border-white/10 bg-white/[0.04] text-gray-400' };

export function accentFor(slug?: string) {
    return (slug && BOARD_ACCENT[slug]) || DEFAULT_ACCENT;
}

export function formatDate(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    const now = Date.now();
    const diffH = (now - d.getTime()) / 3600000;
    if (diffH < 24) {
        return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString('ko-KR', { year: '2-digit', month: '2-digit', day: '2-digit' });
}

export default function PublicCommunityPage() {
    const { board: boardParam } = useParams();
    const navigate = useNavigate();
    const [boards, setBoards] = useState<PublicBoard[]>([]);
    const [posts, setPosts] = useState<PublicPostSummary[]>([]);
    const [notices, setNotices] = useState<PublicPostSummary[]>([]);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [loading, setLoading] = useState(true);

    const activeSlug = boardParam || boards[0]?.slug;

    useEffect(() => {
        document.title = '커뮤니티 | MarketFlow';
        publicCommunityAPI.getBoards()
            .then(r => setBoards(r.boards || []))
            .catch(() => setBoards([]));
    }, []);

    const loadPosts = useCallback(async (slug: string, p: number) => {
        setLoading(true);
        try {
            const r = await publicCommunityAPI.getPosts(slug, p);
            setPosts(r.posts || []);
            setNotices(p === 1 ? (r.notices || []) : []);
            setTotalPages(Math.max(1, r.total_pages || 1));
        } catch {
            setPosts([]); setNotices([]);
        }
        setLoading(false);
    }, []);

    useEffect(() => {
        if (activeSlug) loadPosts(activeSlug, page);
    }, [activeSlug, page, loadPosts]);

    useEffect(() => { setPage(1); }, [activeSlug]);

    const accent = accentFor(activeSlug);
    const rows = [...notices, ...posts];

    return (
        <PublicShell section="community">
            <div className="mx-auto max-w-4xl px-4 pb-6 pt-8 sm:px-6 sm:pt-12">
                {/* 헤드라인 */}
                <div className="pub-rise">
                    <div className="pub-label">// MARKET INTELLIGENCE FEED</div>
                    <h1 className="mt-2 text-3xl font-black tracking-tight text-white sm:text-4xl">
                        커뮤니티
                    </h1>
                    <p className="mt-2 max-w-[52ch] text-[13px] leading-relaxed text-gray-500 sm:text-sm">
                        AI 가 매일 생성하는 시장 분석과 공지, 회원들의 이야기를 모았습니다.
                        글쓰기와 댓글은 회원에게 열려 있습니다.
                    </p>
                </div>

                {/* 보드 탭 — 모바일 가로 스크롤 */}
                <div className="pub-rise mt-6 flex gap-1.5 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
                     style={{ animationDelay: '60ms' }}>
                    {boards.map(b => {
                        const a = accentFor(b.slug);
                        const active = b.slug === activeSlug;
                        return (
                            <button key={b.slug}
                                    onClick={() => navigate(b.slug === boards[0]?.slug ? '/community' : `/community/${b.slug}`)}
                                    className={`min-h-[44px] shrink-0 rounded-xl border px-4 text-[13px] font-bold transition-colors ${
                                        active ? a.chip : 'border-white/[0.06] bg-transparent text-gray-500 hover:text-gray-300'
                                    }`}>
                                {b.name}
                                <span className="ml-1.5 font-mono text-[10px] opacity-60">{b.post_count}</span>
                            </button>
                        );
                    })}
                </div>

                {/* 글 목록 — 헤어라인 리스트 */}
                <div className="pub-rise mt-4 overflow-hidden rounded-2xl border border-white/[0.06] bg-[#0e0e11]"
                     style={{ animationDelay: '120ms' }}>
                    {loading ? (
                        <div className="grid place-items-center py-20 text-gray-600">
                            <i className="fas fa-spinner fa-spin text-lg" />
                        </div>
                    ) : rows.length === 0 ? (
                        <div className="py-20 text-center text-sm text-gray-600">아직 게시글이 없습니다</div>
                    ) : (
                        rows.map((p, i) => (
                            <div key={`${p.is_notice}-${p.id}`}>
                                {i === Math.min(6, Math.max(0, rows.length - 1)) && rows.length > 4 && (
                                    <AdSlot slot="9524871360" className="border-b border-white/[0.04] px-4 py-2" />
                                )}
                                <Link to={`/community/post/${p.id}`}
                                      className="group relative flex min-h-[56px] items-center gap-3 border-b border-white/[0.04] px-4 py-3.5 transition-colors last:border-b-0 hover:bg-white/[0.025] sm:px-5">
                                    <span className={`absolute inset-y-0 left-0 w-[2px] scale-y-0 transition-transform group-hover:scale-y-100 ${accent.bar}`} />
                                    <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2">
                                            {p.is_notice && (
                                                <span className="shrink-0 rounded border border-amber-400/30 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-black tracking-wider text-amber-300">
                                                    공지
                                                </span>
                                            )}
                                            <span className="truncate text-[14px] font-semibold text-gray-200 transition-colors group-hover:text-white sm:text-[15px]">
                                                {p.title}
                                            </span>
                                            {p.comment_count > 0 && (
                                                <span className={`shrink-0 font-mono text-[11px] ${accent.text}`}>
                                                    [{p.comment_count}]
                                                </span>
                                            )}
                                        </div>
                                        <div className="mt-1 flex items-center gap-2.5 font-mono text-[10.5px] tabular-nums text-gray-600">
                                            <span>{p.author_name}</span>
                                            <span className="text-gray-700">·</span>
                                            <span>{formatDate(p.created_at)}</span>
                                            <span className="text-gray-700">·</span>
                                            <span><i className="far fa-eye mr-1 text-[9px]" />{p.view_count}</span>
                                        </div>
                                    </div>
                                    <i className="fas fa-chevron-right shrink-0 text-[10px] text-gray-700 transition-colors group-hover:text-gray-500" />
                                </Link>
                            </div>
                        ))
                    )}
                </div>

                {/* 페이지네이션 */}
                {totalPages > 1 && (
                    <div className="mt-5 flex items-center justify-center gap-2">
                        <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
                                className="min-h-[44px] rounded-xl border border-white/[0.06] px-4 text-[12px] font-bold text-gray-400 transition-colors hover:text-white disabled:opacity-30">
                            <i className="fas fa-chevron-left mr-1" />이전
                        </button>
                        <span className="font-mono text-[12px] tabular-nums text-gray-500">{page} / {totalPages}</span>
                        <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}
                                className="min-h-[44px] rounded-xl border border-white/[0.06] px-4 text-[12px] font-bold text-gray-400 transition-colors hover:text-white disabled:opacity-30">
                            다음<i className="fas fa-chevron-right ml-1" />
                        </button>
                    </div>
                )}

                {/* 가입 유도 */}
                <JoinBanner />
            </div>
        </PublicShell>
    );
}

export function JoinBanner() {
    const navigate = useNavigate();
    return (
        <div className="pub-rise mt-8 overflow-hidden rounded-2xl border border-amber-500/20 bg-gradient-to-br from-amber-500/[0.07] via-transparent to-transparent p-5 sm:p-6"
             style={{ animationDelay: '180ms' }}>
            <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
                <div>
                    <div className="text-[15px] font-black text-white">
                        매일 아침, AI 시그널을 직접 받아보세요
                    </div>
                    <p className="mt-1 text-[12.5px] leading-relaxed text-gray-500">
                        종가베팅 · VCP · AI 차트 분석 전체 기능과 글쓰기·댓글은 회원 전용입니다.
                    </p>
                </div>
                <button onClick={() => navigate('/signup')}
                        className="min-h-[44px] shrink-0 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 px-5 text-[13px] font-black text-black transition-transform hover:scale-[1.03]">
                    무료로 시작하기 <i className="fas fa-arrow-right ml-1.5" />
                </button>
            </div>
        </div>
    );
}
