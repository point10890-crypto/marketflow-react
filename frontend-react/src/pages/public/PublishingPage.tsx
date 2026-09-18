import { useLocation } from 'react-router-dom';
import { PublicShell } from '@/components/public/PublicShell';
import { PUBLISHING_PAGES } from '@/data/publishing.mjs';
import { useSeo } from '@/lib/seo';

export default function PublishingPage() {
    const { pathname } = useLocation();
    const page = PUBLISHING_PAGES.find(p => p.path === pathname.replace(/\/+$/, ''));
    useSeo({ title: `${page?.title ?? '페이지를 찾을 수 없습니다'} | MarketFlow`,
        path: page?.path, description: page?.description, noindex: !page });
    return <PublicShell section={page?.label.toLowerCase()}>
        <article className="mx-auto max-w-[760px] px-4 pb-6 pt-8 sm:px-6 sm:pt-12">
            <h1 className="text-3xl font-black tracking-tight text-white">{page?.title ?? '페이지를 찾을 수 없습니다'}</h1>
            <p className="mt-3 text-xs text-gray-400">최종 갱신: {page?.updated}</p>
            <div className="pub-policy mt-8" dangerouslySetInnerHTML={{ __html: page?.html ?? '' }} />
        </article>
    </PublicShell>;
}
