import { useEffect, useState } from 'react';
import DOMPurify from 'dompurify';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { publicCommunityAPI, PublicComment, PublicPostDetail } from '@/lib/api';
import { AdSlot, PublicShell } from '@/components/public/PublicShell';
import { applySeo, summarizeHtml, SITE_ORIGIN } from '@/lib/seo';
import { accentFor, formatDate, JoinBanner } from './PublicCommunityPage';

/** 공개 글 상세 (/community/post/:id) — 에디토리얼 본문 + 읽기전용 댓글. */
export default function PublicPostPage() {
    const { postId } = useParams();
    const navigate = useNavigate();
    const [post, setPost] = useState<PublicPostDetail | null>(null);
    const [comments, setComments] = useState<PublicComment[]>([]);
    const [state, setState] = useState<'loading' | 'ok' | 'missing'>('loading');

    useEffect(() => {
        const id = Number(postId);
        if (!id) { setState('missing'); return; }
        publicCommunityAPI.getPost(id)
            .then(r => {
                setPost(r.post);
                setComments(r.comments || []);
                setState('ok');
                // 게시글 단위 SEO — 제목·요약·canonical·Article 구조화 데이터
                applySeo({
                    title: `${r.post.title} | MarketFlow 커뮤니티`,
                    description: summarizeHtml(r.post.content),
                    path: `/community/post/${id}`,
                    ogType: 'article',
                    jsonLd: {
                        '@context': 'https://schema.org',
                        '@type': 'Article',
                        headline: r.post.title,
                        datePublished: r.post.created_at,
                        author: { '@type': 'Person', name: r.post.author_name },
                        publisher: { '@type': 'Organization', name: 'MarketFlow', url: SITE_ORIGIN },
                        mainEntityOfPage: `${SITE_ORIGIN}/community/post/${id}`,
                        inLanguage: 'ko',
                    },
                });
            })
            .catch(() => {
                setState('missing');
                // 삭제/비공개 글 — 검색엔진이 soft-404 로 색인하지 않게 noindex
                applySeo({ title: '글을 찾을 수 없습니다 | MarketFlow', noindex: true });
            });
    }, [postId]);

    if (state === 'loading') {
        return (
            <PublicShell section="community">
                <div className="grid place-items-center py-32 text-gray-600"><i className="fas fa-spinner fa-spin text-lg" /></div>
            </PublicShell>
        );
    }
    if (state === 'missing' || !post) {
        return (
            <PublicShell section="community">
                <div className="mx-auto max-w-xl px-6 py-28 text-center">
                    <div className="font-mono text-[11px] uppercase tracking-[0.2em] text-gray-600">404 // not found</div>
                    <h1 className="mt-3 text-2xl font-black text-white">글을 찾을 수 없습니다</h1>
                    <p className="mt-2 text-[13px] text-gray-500">삭제되었거나 회원 전용 게시판의 글입니다.</p>
                    <Link to="/community"
                          className="mt-6 inline-block rounded-xl border border-white/10 px-5 py-3 text-[13px] font-bold text-gray-300 transition-colors hover:text-white">
                        <i className="fas fa-arrow-left mr-1.5" />커뮤니티로
                    </Link>
                </div>
            </PublicShell>
        );
    }

    const accent = accentFor(post.board?.slug);

    return (
        <PublicShell section="community">
            <article className="mx-auto max-w-[760px] px-4 pb-6 pt-8 sm:px-6 sm:pt-12">
                {/* 브레드크럼 */}
                <div className="pub-rise font-mono text-[10.5px] uppercase tracking-[0.15em] text-gray-600">
                    <Link to="/community" className="transition-colors hover:text-gray-400">community</Link>
                    <span className="mx-1.5">/</span>
                    <Link to={`/community/${post.board.slug}`} className={`transition-colors hover:opacity-80 ${accent.text}`}>
                        {post.board.name}
                    </Link>
                </div>

                {/* 제목/메타 */}
                <header className="pub-rise mt-3" style={{ animationDelay: '50ms' }}>
                    <h1 className="text-[26px] font-black leading-[1.3] tracking-tight text-white sm:text-[32px]">
                        {post.title}
                    </h1>
                    <div className="mt-3 flex flex-wrap items-center gap-2.5 border-b border-white/[0.06] pb-5 font-mono text-[11px] tabular-nums text-gray-500">
                        <span className="text-gray-400">{post.author_name}</span>
                        <span className="text-gray-700">·</span>
                        <span>{formatDate(post.created_at)}</span>
                        <span className="text-gray-700">·</span>
                        <span><i className="far fa-eye mr-1 text-[9px]" />{post.view_count}</span>
                    </div>
                </header>

                {/* 본문 — 서버 생성 HTML (자체 콘텐츠) */}
                <div className="pub-prose pub-rise mt-6" style={{ animationDelay: '100ms' }}
                     dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(post.content) }} />

                {/* 본문 하단 광고 */}
                <AdSlot slot="3817264905" className="mt-10" />

                {/* 댓글 (읽기 전용) */}
                <section className="mt-10">
                    <div className="pub-label">// COMMENTS ({comments.length})</div>
                    {comments.length === 0 ? (
                        <p className="mt-3 text-[13px] text-gray-600">아직 댓글이 없습니다.</p>
                    ) : (
                        <div className="mt-3 space-y-3">
                            {comments.map(c => (
                                <div key={c.id} className="rounded-xl border border-white/[0.05] bg-[#0e0e11] p-4">
                                    <div className="flex items-center gap-2 font-mono text-[10.5px] tabular-nums text-gray-600">
                                        <span className="text-gray-400">{c.author_name}</span>
                                        <span className="text-gray-700">·</span>
                                        <span>{formatDate(c.created_at)}</span>
                                    </div>
                                    <p className="mt-1.5 whitespace-pre-wrap text-[13.5px] leading-relaxed text-gray-300">
                                        {c.content}
                                    </p>
                                </div>
                            ))}
                        </div>
                    )}
                    <button onClick={() => navigate('/signup')}
                            className="mt-4 flex min-h-[48px] w-full items-center justify-center gap-2 rounded-xl border border-dashed border-white/10 text-[13px] font-semibold text-gray-500 transition-colors hover:border-amber-400/30 hover:text-amber-300">
                        <i className="far fa-comment" /> 댓글을 쓰려면 무료 가입
                    </button>
                </section>

                <JoinBanner />
            </article>
        </PublicShell>
    );
}
