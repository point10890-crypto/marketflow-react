import { useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { communityAPI, type CommunityPost, API_BASE } from '@/lib/api';

export default function FormulaPurchaseSection({ post }: { post: CommunityPost }) {
    const { user } = useAuth();
    const isAdmin = user?.role === 'admin';
    const purchaseStatus = post.purchase_status;

    const priceNum = post.price ? parseInt(post.price.replace(/[^0-9]/g, ''), 10) : 0;
    const formattedPrice = priceNum ? priceNum.toLocaleString() : '0';

    // Admin always sees info section
    if (isAdmin) {
        return (
            <div className="border-t border-white/[0.06]">
                <FormulaInfoTable price={formattedPrice} fileName={post.file_name} />
                {post.file_url && (
                    <div className="px-5 md:px-7 py-5">
                        <DownloadButton postId={post.id} fileName={post.file_name} />
                    </div>
                )}
            </div>
        );
    }

    // Approved: show formula info + download
    if (purchaseStatus === 'approved') {
        return (
            <div className="border-t border-white/[0.06]">
                <FormulaInfoTable price={formattedPrice} fileName={post.file_name} />
                <div className="px-5 md:px-7 py-5 space-y-3">
                    <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4 text-green-400 text-sm flex items-center gap-2">
                        <i className="fas fa-check-circle" />구매가 승인되었습니다.
                    </div>
                    {post.file_url && <DownloadButton postId={post.id} fileName={post.file_name} />}
                </div>
            </div>
        );
    }

    // Pending: show waiting message
    if (purchaseStatus === 'pending') {
        return (
            <div className="border-t border-white/[0.06]">
                <FormulaInfoTable price={formattedPrice} />
                <div className="px-5 md:px-7 py-5">
                    <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-4 text-yellow-400 text-sm flex items-center gap-2">
                        <i className="fas fa-clock" />구매신청이 접수되었습니다. 입금 확인 후 승인됩니다.
                    </div>
                </div>
            </div>
        );
    }

    // Rejected: show rejected + allow re-purchase
    if (purchaseStatus === 'rejected') {
        return (
            <div className="border-t border-white/[0.06]">
                <FormulaInfoTable price={formattedPrice} />
                <div className="px-5 md:px-7 py-5 space-y-3">
                    <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm flex items-center gap-2">
                        <i className="fas fa-times-circle" />구매신청이 반려되었습니다.
                    </div>
                    <PurchaseForm postId={post.id} formattedPrice={formattedPrice} />
                </div>
            </div>
        );
    }

    // No purchase: show purchase form
    return (
        <div className="border-t border-white/[0.06]">
            <FormulaInfoTable price={formattedPrice} />
            <PurchaseForm postId={post.id} formattedPrice={formattedPrice} />
        </div>
    );
}

// ── Sub-components ──

function FormulaInfoTable({ price, fileName }: { price: string; fileName?: string }) {
    return (
        <>
            <div className="flex items-center border-b border-white/[0.06]">
                <span className="w-28 md:w-36 px-5 md:px-7 py-4 text-sm font-bold text-gray-400 bg-white/[0.02] flex-shrink-0">
                    가격
                </span>
                <span className="px-5 md:px-7 py-4 text-white font-bold text-sm">
                    {price} 원
                </span>
            </div>
            {fileName && (
                <div className="flex items-center border-b border-white/[0.06]">
                    <span className="w-28 md:w-36 px-5 md:px-7 py-4 text-sm font-bold text-gray-400 bg-white/[0.02] flex-shrink-0">
                        식파일
                    </span>
                    <span className="px-5 md:px-7 py-4 text-gray-300 text-sm">
                        {fileName}
                    </span>
                </div>
            )}
        </>
    );
}

function DownloadButton({ postId, fileName }: { postId: number; fileName?: string }) {
    const handleDownload = async () => {
        try {
            const { getToken } = await import('@/lib/auth');
            const token = getToken();
            const res = await fetch(`${API_BASE}/api/community/posts/${postId}/download`, {
                headers: token ? { Authorization: `Bearer ${token}` } : {},
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                alert(err.error || '다운로드에 실패했습니다.');
                return;
            }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = fileName || 'formula_file';
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        } catch {
            alert('다운로드에 실패했습니다.');
        }
    };

    return (
        <button
            onClick={handleDownload}
            className="w-full bg-yellow-500 hover:bg-yellow-500/90 text-black font-bold text-base rounded-xl py-4 transition-colors active:scale-[0.99] flex items-center justify-center gap-2"
        >
            <i className="fas fa-download" />
            식파일 다운로드
        </button>
    );
}

function PurchaseForm({ postId, formattedPrice }: { postId: number; formattedPrice: string }) {
    const { user } = useAuth();
    const [buyerName, setBuyerName] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const [result, setResult] = useState<'success' | 'error' | ''>('');
    const [errorMsg, setErrorMsg] = useState('');

    const handlePurchase = async () => {
        if (!buyerName.trim()) {
            setErrorMsg('입금자명을 입력하세요.');
            setResult('error');
            return;
        }
        setSubmitting(true);
        setResult('');
        setErrorMsg('');
        try {
            await communityAPI.createPurchase(postId, buyerName.trim());
            setResult('success');
            setBuyerName('');
        } catch (err: any) {
            setErrorMsg(err.message || '구매신청에 실패했습니다.');
            setResult('error');
        } finally {
            setSubmitting(false);
        }
    };

    if (!user) return null;

    return (
        <div className="px-5 md:px-7 py-5 md:py-6 space-y-3">
            <p className="text-red-400 text-xs md:text-sm">
                *입력하신 입금자명과 다르게 입금하시면 승인이 늦어질 수 있습니다.
            </p>
            <p className="text-xs md:text-sm">
                <span className="text-red-400">*계좌정보 </span>
                <span className="text-yellow-400 font-bold">국민은행 2259-02-04-057670 이종민</span>
            </p>
            <p className="text-xs md:text-sm">
                <span className="text-red-400">*카카오톡 </span>
                <a href="https://open.kakao.com/o/sJVLbWUe" target="_blank" rel="noopener noreferrer"
                    className="text-[#2997ff] hover:underline">
                    https://open.kakao.com/o/sJVLbWUe
                </a>
            </p>

            <div className="mt-4 space-y-3">
                <input
                    type="text"
                    value={buyerName}
                    onChange={e => setBuyerName(e.target.value)}
                    placeholder="입금자명을 입력하세요."
                    className="w-full bg-white/[0.04] border border-white/10 text-white text-sm rounded-xl px-4 py-3 placeholder-gray-600 focus:outline-none focus:border-[#2997ff]/50 transition-colors"
                    onKeyDown={e => e.key === 'Enter' && handlePurchase()}
                />

                {result === 'success' && (
                    <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-3 text-green-400 text-sm flex items-center gap-2">
                        <i className="fas fa-check-circle" />구매신청이 완료되었습니다. 입금 확인 후 승인됩니다.
                    </div>
                )}
                {result === 'error' && (
                    <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-3 text-red-400 text-sm flex items-center gap-2">
                        <i className="fas fa-exclamation-circle" />{errorMsg}
                    </div>
                )}

                <button
                    onClick={handlePurchase}
                    disabled={submitting}
                    className="w-full bg-yellow-500 hover:bg-yellow-500/90 text-black font-bold text-base rounded-xl py-4 transition-colors disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.99]"
                >
                    {submitting ? '신청 중...' : '구매신청'}
                </button>
            </div>
        </div>
    );
}
