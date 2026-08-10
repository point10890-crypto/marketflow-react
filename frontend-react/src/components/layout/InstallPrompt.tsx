import { useState, useEffect } from 'react';
import { usePWAInstall } from '@/hooks/usePWAInstall';
import { safeGetItem, safeSetItem } from '@/lib/safeStorage';

export default function InstallPrompt() {
    const { canInstall, isInstalled, isIOS, install } = usePWAInstall();
    const [showBanner, setShowBanner] = useState(false);
    const [showGuide, setShowGuide] = useState(false);

    useEffect(() => {
        if (isInstalled) return;

        const dismissed = safeGetItem('local', 'install-dismissed');
        if (dismissed && Date.now() - Number(dismissed) < 24 * 60 * 60 * 1000) return;

        const timer = setTimeout(() => setShowBanner(true), 3000);
        return () => clearTimeout(timer);
    }, [isInstalled]);

    const handleInstall = async () => {
        const result = await install();
        if (result === 'accepted') {
            setShowBanner(false);
        } else if (result === 'manual') {
            setShowGuide(true);
        }
    };

    const handleDismiss = () => {
        setShowBanner(false);
        setShowGuide(false);
        safeSetItem('local', 'install-dismissed', String(Date.now()));
    };

    if (!showBanner || isInstalled) return null;
    if (!canInstall && !showBanner) return null;

    return (
        <>
            {/* Banner */}
            <div className="fixed bottom-[5.5rem] md:bottom-6 left-3 right-3 z-[60]" style={{ animation: 'pwa-slide-up 0.3s ease-out' }}>
                <div className="bg-[#1a1a2e] border border-white/10 rounded-2xl p-4 shadow-2xl shadow-black/50">
                    <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2.5">
                            <div className="w-10 h-10 bg-gradient-to-br from-yellow-300 via-amber-500 to-yellow-600 rounded-xl flex items-center justify-center text-white font-extrabold text-sm">B</div>
                            <div>
                                <p className="text-sm font-bold text-white">BitMan 앱 설치</p>
                                <p className="text-[10px] text-gray-400">{isIOS ? '홈 화면에 추가하세요' : '빠른 접속 + 오프라인 지원'}</p>
                            </div>
                        </div>
                        <button onClick={handleDismiss} className="text-gray-500 hover:text-white p-1">
                            <i className="fas fa-times text-sm" />
                        </button>
                    </div>
                    <button
                        onClick={isIOS ? () => setShowGuide(true) : handleInstall}
                        className="w-full py-2.5 bg-gradient-to-r from-amber-500 to-yellow-500 text-black font-bold text-sm rounded-xl active:scale-[0.98] transition-transform"
                    >
                        {isIOS ? '설치 방법 보기' : '앱 설치하기'}
                    </button>
                </div>
            </div>

            {/* Guide overlay */}
            {showGuide && <InstallGuide isIOS={isIOS} onClose={handleDismiss} />}

            <style>{`
                @keyframes pwa-slide-up {
                    from { transform: translateY(100%); opacity: 0; }
                    to { transform: translateY(0); opacity: 1; }
                }
            `}</style>
        </>
    );
}

export function InstallGuide({ isIOS, onClose }: { isIOS: boolean; onClose: () => void }) {
    if (isIOS) {
        return (
            <div className="fixed inset-0 z-[70] bg-black/80 backdrop-blur-sm flex items-end justify-center" onClick={onClose}>
                <div className="bg-[#1a1a2e] border-t border-white/10 rounded-t-3xl p-6 w-full max-w-md" style={{ animation: 'pwa-slide-up 0.3s ease-out' }} onClick={e => e.stopPropagation()}>
                    <div className="w-10 h-1 bg-gray-600 rounded-full mx-auto mb-5" />
                    <h3 className="text-lg font-bold text-white mb-4 text-center">홈 화면에 추가하기</h3>
                    <div className="space-y-4">
                        <div className="flex items-center gap-3">
                            <span className="w-8 h-8 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-sm font-bold">1</span>
                            <p className="text-sm text-gray-300">하단 <i className="fas fa-share-from-square text-blue-400 mx-1" /> 공유 버튼 탭</p>
                        </div>
                        <div className="flex items-center gap-3">
                            <span className="w-8 h-8 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-sm font-bold">2</span>
                            <p className="text-sm text-gray-300"><i className="fas fa-plus-square text-blue-400 mx-1" /> "홈 화면에 추가" 선택</p>
                        </div>
                        <div className="flex items-center gap-3">
                            <span className="w-8 h-8 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-sm font-bold">3</span>
                            <p className="text-sm text-gray-300">우측 상단 "추가" 탭</p>
                        </div>
                    </div>
                    <button onClick={onClose} className="w-full mt-5 py-3 bg-white/10 text-white font-semibold rounded-xl active:scale-[0.98] transition-transform">확인</button>
                </div>
            </div>
        );
    }

    return (
        <div className="fixed inset-0 z-[70] bg-black/80 backdrop-blur-sm flex items-center justify-center" onClick={onClose}>
            <div className="bg-[#1a1a2e] border border-white/10 rounded-2xl p-6 w-full max-w-sm mx-4" onClick={e => e.stopPropagation()}>
                <h3 className="text-lg font-bold text-white mb-4 text-center">앱 설치 방법</h3>
                <div className="space-y-4">
                    <div className="flex items-start gap-3">
                        <span className="w-8 h-8 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-sm font-bold shrink-0">1</span>
                        <p className="text-sm text-gray-300">Chrome 주소창 오른쪽의 <i className="fas fa-download text-blue-400 mx-1" /> 설치 아이콘 클릭</p>
                    </div>
                    <div className="flex items-start gap-3">
                        <span className="w-8 h-8 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-sm font-bold shrink-0">2</span>
                        <p className="text-sm text-gray-300">또는 <i className="fas fa-ellipsis-vertical text-blue-400 mx-1" /> 메뉴 → "앱 설치" 선택</p>
                    </div>
                    <div className="flex items-start gap-3">
                        <span className="w-8 h-8 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-sm font-bold shrink-0">3</span>
                        <p className="text-sm text-gray-300">"설치" 버튼을 누르면 바탕화면에 앱 추가</p>
                    </div>
                </div>
                <button onClick={onClose} className="w-full mt-5 py-3 bg-white/10 text-white font-semibold rounded-xl active:scale-[0.98] transition-transform">확인</button>
            </div>
        </div>
    );
}
