import { KAKAO_SUPPORT_URL } from '@/lib/supportInfo';

type KakaoSupportLinkProps = {
    className?: string;
    label?: string;
};

export default function KakaoSupportLink({
    className = '',
    label = '카카오톡 문의하기',
}: KakaoSupportLinkProps) {
    return (
        <a
            href={KAKAO_SUPPORT_URL}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={label}
            className={`flex w-full items-center justify-center gap-2 rounded-xl border border-[#FEE500]/25 bg-[#FEE500]/10 px-4 py-3 text-sm font-bold text-[#FEE500] transition-all hover:bg-[#FEE500]/20 hover:text-[#FFF7A8] ${className}`}
        >
            <i className="fas fa-comment" />
            <span>{label}</span>
        </a>
    );
}
