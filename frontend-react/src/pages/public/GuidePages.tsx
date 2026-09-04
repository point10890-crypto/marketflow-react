import { Link, useParams } from 'react-router-dom';
import { AdSlot, PublicShell } from '@/components/public/PublicShell';
import { GUIDES, findGuide } from '@/data/guides.mjs';
import { CREATOR_PROFILE } from '@/data/creator.mjs';
import { useSeo, SITE_ORIGIN } from '@/lib/seo';
import { JoinBanner } from './PublicCommunityPage';

/**
 * 인사이트 가이드 (공개) — /guide, /guide/:slug.
 *
 * 저장소 내장 오리지널 교육 콘텐츠 존. 백엔드 API 와 무관하게 항상 렌더되므로
 * AdSense 심사·검색 크롤러에게 고유 콘텐츠를 보장하는 핵심 영역이다.
 * 본문은 scripts/prerender-seo.mjs 가 같은 데이터로 정적 프리렌더한다.
 */

const CATEGORY_TONE: Record<string, string> = {
    '차트 분석': 'border-sky-400/30 bg-sky-500/10 text-sky-300',
    '수급 분석': 'border-emerald-400/30 bg-emerald-500/10 text-emerald-300',
    '시장 분석': 'border-amber-400/30 bg-amber-500/10 text-amber-300',
    '전략 개념': 'border-[#ff6b57]/30 bg-[#ff6b57]/10 text-[#ff9b89]',
    '리스크 관리': 'border-rose-400/30 bg-rose-500/10 text-rose-300',
    '기업 분석': 'border-violet-400/30 bg-violet-500/10 text-violet-300',
    'AI 활용': 'border-cyan-400/30 bg-cyan-500/10 text-cyan-300',
};

function categoryChip(category: string) {
    return CATEGORY_TONE[category] || 'border-white/10 bg-white/[0.04] text-gray-400';
}

export function GuideListPage() {
    useSeo({
        title: '인사이트 가이드 — 시장 분석 교육 콘텐츠 | MarketFlow',
        description: 'VCP 패턴, 수급 분석, 시장 레짐, 종가베팅 체크리스트, 포지션 사이징, 공시 읽기, AI 신호 활용까지 — MarketFlow 팀이 쓴 시장 분석 교육 가이드 모음입니다.',
        path: '/guide',
        jsonLd: {
            '@context': 'https://schema.org',
            '@type': 'CollectionPage',
            name: 'MarketFlow 인사이트 가이드',
            url: `${SITE_ORIGIN}/guide`,
            inLanguage: 'ko',
            hasPart: GUIDES.map((g) => ({
                '@type': 'Article',
                headline: g.title,
                url: `${SITE_ORIGIN}/guide/${g.slug}`,
            })),
        },
    });

    return (
        <PublicShell section="guide">
            <div className="mx-auto max-w-4xl px-4 pb-6 pt-8 sm:px-6 sm:pt-12">
                <div className="pub-rise">
                    <div className="pub-label">// MARKET INSIGHT GUIDES</div>
                    <h1 className="mt-2 text-3xl font-black tracking-tight text-white sm:text-4xl">
                        인사이트 가이드
                    </h1>
                    <p className="mt-2 max-w-[56ch] text-[13px] leading-relaxed text-gray-500 sm:text-sm">
                        차트·수급·공시·리스크 관리까지, MarketFlow 팀이 서비스에 녹인 분석 원리를
                        누구나 읽을 수 있게 정리했습니다. 모든 글은 교육 목적이며 투자 권유가 아닙니다.
                    </p>
                    <p className="mt-3 max-w-[64ch] text-[13px] leading-relaxed text-gray-400">
                        {CREATOR_PROFILE.introduction}{' '}
                        <Link to="/about#creator" className="text-[#ff9b89] underline underline-offset-4">
                            운영자 소개와 채널 보기
                        </Link>
                    </p>
                </div>

                <div className="pub-rise mt-6 grid gap-3 sm:grid-cols-2" style={{ animationDelay: '80ms' }}>
                    {GUIDES.map((g) => (
                        <Link
                            key={g.slug}
                            to={`/guide/${g.slug}`}
                            className="group flex flex-col rounded-2xl border border-white/[0.07] bg-[#0e0e11] p-5 transition-all hover:-translate-y-0.5 hover:border-white/20"
                        >
                            <div className="flex items-center justify-between gap-2">
                                <span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold ${categoryChip(g.category)}`}>
                                    {g.category}
                                </span>
                                <span className="font-mono text-[10px] tabular-nums text-gray-600">{g.readMinutes}분 읽기</span>
                            </div>
                            <h2 className="mt-3 text-[15px] font-black leading-snug text-gray-100 transition-colors group-hover:text-white">
                                {g.title}
                            </h2>
                            <p className="mt-2 flex-1 text-[12.5px] leading-6 text-gray-500">{g.description}</p>
                            <div className="mt-3 flex items-center justify-between border-t border-white/[0.05] pt-3">
                                <span className="font-mono text-[10px] tabular-nums text-gray-600">{g.date}</span>
                                <span className="text-[11px] font-bold text-gray-500 transition-colors group-hover:text-[#ff9b89]">
                                    읽어보기<i className="fas fa-arrow-right ml-1.5 text-[9px]" aria-hidden />
                                </span>
                            </div>
                        </Link>
                    ))}
                </div>

                <JoinBanner />
            </div>
        </PublicShell>
    );
}

export function GuideArticlePage() {
    const { slug } = useParams();
    const guide = slug ? findGuide(slug) : null;

    // 데이터가 저장소 내장이라 로딩 상태가 없다 — 훅 한 번으로 존재/404 분기 처리.
    useSeo(guide ? {
        title: `${guide.title} | MarketFlow 가이드`,
        description: guide.description,
        path: `/guide/${guide.slug}`,
        ogType: 'article',
        jsonLd: [
            {
                '@context': 'https://schema.org',
                '@type': 'Article',
                headline: guide.title,
                description: guide.description,
                datePublished: guide.date,
                author: { '@type': 'Organization', name: 'MarketFlow 리서치', url: `${SITE_ORIGIN}/about#creator` },
                publisher: { '@type': 'Organization', name: 'MarketFlow', url: SITE_ORIGIN },
                mainEntityOfPage: `${SITE_ORIGIN}/guide/${guide.slug}`,
                inLanguage: 'ko',
            },
            {
                '@context': 'https://schema.org',
                '@type': 'BreadcrumbList',
                itemListElement: [
                    { '@type': 'ListItem', position: 1, name: '홈', item: SITE_ORIGIN },
                    { '@type': 'ListItem', position: 2, name: '인사이트 가이드', item: `${SITE_ORIGIN}/guide` },
                    { '@type': 'ListItem', position: 3, name: guide.title, item: `${SITE_ORIGIN}/guide/${guide.slug}` },
                ],
            },
        ],
    } : { title: '가이드를 찾을 수 없습니다 | MarketFlow', noindex: true });

    if (!guide) {
        return (
            <PublicShell section="guide">
                <div className="mx-auto max-w-xl px-6 py-28 text-center">
                    <div className="font-mono text-[11px] uppercase tracking-[0.2em] text-gray-600">404 // not found</div>
                    <h1 className="mt-3 text-2xl font-black text-white">가이드를 찾을 수 없습니다</h1>
                    <p className="mt-2 text-[13px] text-gray-500">삭제되었거나 주소가 잘못되었습니다.</p>
                    <Link to="/guide"
                          className="mt-6 inline-block rounded-xl border border-white/10 px-5 py-3 text-[13px] font-bold text-gray-300 transition-colors hover:text-white">
                        <i className="fas fa-arrow-left mr-1.5" />가이드 목록으로
                    </Link>
                </div>
            </PublicShell>
        );
    }

    const related = GUIDES.filter((g) => g.slug !== guide.slug).slice(0, 3);

    return (
        <PublicShell section="guide">
            <article className="mx-auto max-w-[760px] px-4 pb-6 pt-8 sm:px-6 sm:pt-12">
                {/* 브레드크럼 */}
                <div className="pub-rise font-mono text-[10.5px] uppercase tracking-[0.15em] text-gray-600">
                    <Link to="/guide" className="transition-colors hover:text-gray-400">guide</Link>
                    <span className="mx-1.5">/</span>
                    <span className="text-gray-500">{guide.category}</span>
                </div>

                <header className="pub-rise mt-3" style={{ animationDelay: '50ms' }}>
                    <h1 className="text-[26px] font-black leading-[1.3] tracking-tight text-white sm:text-[32px]">
                        {guide.title}
                    </h1>
                    <div className="mt-3 flex flex-wrap items-center gap-2.5 border-b border-white/[0.06] pb-5 font-mono text-[11px] tabular-nums text-gray-500">
                        <Link to="/about#creator" className="text-gray-400 underline underline-offset-4 hover:text-white">
                            MarketFlow 리서치
                        </Link>
                        <span className="text-gray-700">·</span>
                        <span>{guide.date}</span>
                        <span className="text-gray-700">·</span>
                        <span>{guide.readMinutes}분 읽기</span>
                        <span className={`ml-1 rounded-full border px-2 py-0.5 text-[10px] font-bold ${categoryChip(guide.category)}`}>
                            {guide.category}
                        </span>
                    </div>
                    <p className="mt-3 text-[12px] leading-6 text-gray-400">
                        <Link to="/about#creator" className="underline underline-offset-4 hover:text-white">
                            운영자: {CREATOR_PROFILE.name} · {CREATOR_PROFILE.channelName}
                        </Link>
                    </p>
                </header>

                {/* 본문 — 저장소 내장 신뢰 HTML */}
                <div className="pub-prose pub-rise mt-6" style={{ animationDelay: '100ms' }}
                     dangerouslySetInnerHTML={{ __html: guide.html }} />

                {/* 면책 — 모든 가이드 공통 */}
                <p className="mt-8 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4 text-[11.5px] leading-5 text-gray-500">
                    이 글은 투자 교육을 위한 일반 정보이며 특정 종목의 매수·매도 권유나 투자 자문이
                    아닙니다. 언급된 지표와 체크리스트는 분석 도구일 뿐 수익을 보장하지 않으며,
                    투자의 최종 판단과 책임은 투자자 본인에게 있습니다.
                </p>

                {/* 본문 하단 광고 */}
                <AdSlot slot="3817264905" className="mt-8" />

                {/* 관련 가이드 */}
                <section className="mt-10">
                    <div className="pub-label">// MORE GUIDES</div>
                    <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
                        {related.map((g) => (
                            <Link key={g.slug} to={`/guide/${g.slug}`}
                                  className="group rounded-xl border border-white/[0.06] bg-[#0e0e11] p-3.5 transition-colors hover:border-white/20">
                                <span className={`rounded-full border px-2 py-0.5 text-[9px] font-bold ${categoryChip(g.category)}`}>
                                    {g.category}
                                </span>
                                <div className="mt-2 text-[12.5px] font-bold leading-snug text-gray-300 transition-colors group-hover:text-white">
                                    {g.title}
                                </div>
                            </Link>
                        ))}
                    </div>
                </section>

                <JoinBanner />
            </article>
        </PublicShell>
    );
}
