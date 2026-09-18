// Shared by the public React pages and their crawlable HTML snapshots.
export const CREATOR_PROFILE = {
    name: '비트맨',
    channelName: '비트맨의 GOODRICH TV',
    channelUrl: 'https://www.youtube.com/@point108xGoodRichTV',
    introduction: 'MarketFlow는 구독자 1만 명 이상을 보유한 유튜브 크리에이터 비트맨이 운영합니다.',
    subscriberAsOf: '2026-09-05',
};

export const CREATOR_ABOUT_JSON_LD = {
    '@context': 'https://schema.org',
    '@type': 'AboutPage',
    name: 'MarketFlow 서비스 및 운영자 소개',
    url: 'https://bit-man.net/about',
    inLanguage: 'ko',
    mainEntity: {
        '@type': 'Person',
        '@id': 'https://bit-man.net/about#creator',
        name: CREATOR_PROFILE.name,
        jobTitle: '유튜브 크리에이터',
        description: CREATOR_PROFILE.introduction,
        url: 'https://bit-man.net/about#creator',
        sameAs: [CREATOR_PROFILE.channelUrl],
    },
};
