/**
 * 수식 계열 게시판 설정 — 수식마켓과 수식 다이소가 같은 화면(목록·등록·구매)을 공유한다.
 *
 * 백엔드 `app/routes/community.py` 의 FORMULA_BOARD_SLUGS / FORMULA_BOARD_FIXED_PRICE 와 짝.
 * 새 수식 게시판을 추가할 때는 여기와 백엔드 두 곳만 고치면 된다.
 */
export interface FormulaBoardConfig {
    slug: string;
    title: string;
    subtitle: string;
    /** 등록 버튼·헤더 라벨 */
    writeLabel: string;
    /** 균일가 게시판이면 원 단위 고정 가격 (입력 불가) */
    fixedPrice: number | null;
    /** tailwind 색 토큰 */
    accentText: string;
    accentBg: string;
    accentBorderHover: string;
    accentShadowHover: string;
    iconClass: string;
    iconGradient: string;
    emptyTitle: string;
    emptyHint: string;
}

export const FORMULA_BOARDS: Record<string, FormulaBoardConfig> = {
    'formula-market': {
        slug: 'formula-market',
        title: '수식 마켓',
        subtitle: '검증된 트레이딩 수식을 만나보세요',
        writeLabel: '수식 등록',
        fixedPrice: null,
        accentText: 'text-yellow-400',
        accentBg: 'bg-yellow-500 hover:bg-yellow-500/85',
        accentBorderHover: 'hover:border-yellow-500/30',
        accentShadowHover: 'hover:shadow-yellow-500/5',
        iconClass: 'fa-square-root-variable',
        iconGradient: 'from-yellow-500/20 to-amber-600/10',
        emptyTitle: '아직 등록된 수식이 없습니다',
        emptyHint: '새로운 수식이 등록되면 여기에 표시됩니다',
    },
    'formula-daiso': {
        slug: 'formula-daiso',
        title: '수식 다이소',
        subtitle: '모든 수식·조건검색식 3만원 균일가',
        writeLabel: '균일가 수식 등록',
        fixedPrice: 30000,
        accentText: 'text-orange-400',
        accentBg: 'bg-orange-500 hover:bg-orange-500/85',
        accentBorderHover: 'hover:border-orange-500/30',
        accentShadowHover: 'hover:shadow-orange-500/5',
        iconClass: 'fa-tags',
        iconGradient: 'from-orange-500/20 to-rose-600/10',
        emptyTitle: '아직 등록된 균일가 수식이 없습니다',
        emptyHint: '3만원 균일가 수식이 등록되면 여기에 표시됩니다',
    },
};

export const FORMULA_BOARD_SLUGS = Object.keys(FORMULA_BOARDS);

export function isFormulaBoardSlug(slug?: string | null): boolean {
    return !!slug && slug in FORMULA_BOARDS;
}

export function getFormulaBoard(slug?: string | null): FormulaBoardConfig | null {
    return slug && FORMULA_BOARDS[slug] ? FORMULA_BOARDS[slug] : null;
}
