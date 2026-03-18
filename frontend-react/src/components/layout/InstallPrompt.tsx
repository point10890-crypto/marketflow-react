import { useState, useEffect } from 'react';

interface BeforeInstallPromptEvent extends Event {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

export default function InstallPrompt() {
    const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
    const [showBanner, setShowBanner] = useState(false);
    const [isIOS, setIsIOS] = useState(false);
    const [showIOSGuide, setShowIOSGuide] = useState(false);

    useEffect(() => {
        // Check if already installed
        if (window.matchMedia('(display-mode: standalone)').matches) return;

        // Check if dismissed recently
        const dismissed = localStorage.getItem('install-dismissed');
        if (dismissed && Date.now() - Number(dismissed) < 7 * 24 * 60 * 60 * 1000) return;

        // iOS detection
        const ua = navigator.userAgent;
        const ios = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
        setIsIOS(ios);

        if (ios) {
            // Show iOS guide after 3 seconds
            const timer = setTimeout(() => setShowBanner(true), 3000);
            return () => clearTimeout(timer);
        }

        // Android/Desktop: listen for install prompt
        const handler = (e: Event) => {
            e.preventDefault();
            setDeferredPrompt(e as BeforeInstallPromptEvent);
            setTimeout(() => setShowBanner(true), 2000);
        };
        window.addEventListener('beforeinstallprompt', handler);
        return () => window.removeEventListener('beforeinstallprompt', handler);
    }, []);

    const handleInstall = async () => {
        if (deferredPrompt) {
            await deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            if (outcome === 'accepted') {
                setShowBanner(false);
            }
            setDeferredPrompt(null);
        }
    };

    const handleDismiss = () => {
        setShowBanner(false);
        setShowIOSGuide(false);
        localStorage.setItem('install-dismissed', String(Date.now()));
    };

    if (!showBanner) return null;

    // iOS guide
    if (isIOS) {
        return (
            <>
                {/* Banner */}
                <div className="fixed bottom-20 left-3 right-3 z-[60] animate-slide-up">
                    <div className="bg-[#1a1a2e] border border-white/10 rounded-2xl p-4 shadow-2xl shadow-black/50">
                        <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2.5">
                                <div className="w-10 h-10 bg-gradient-to-br from-yellow-300 via-amber-500 to-yellow-600 rounded-xl flex items-center justify-center text-white font-extrabold text-sm">B</div>
                                <div>
                                    <p className="text-sm font-bold text-white">BitMan 앱 설치</p>
                                    <p className="text-[10px] text-gray-400">홈 화면에 추가하세요</p>
                                </div>
                            </div>
                            <button onClick={handleDismiss} className="text-gray-500 hover:text-white p-1">
                                <i className="fas fa-times text-sm" />
                            </button>
                        </div>
                        <button
                            onClick={() => setShowIOSGuide(true)}
                            className="w-full py-2.5 bg-gradient-to-r from-amber-500 to-yellow-500 text-black font-bold text-sm rounded-xl active:scale-[0.98] transition-transform"
                        >
                            설치 방법 보기
                        </button>
                    </div>
                </div>

                {/* iOS Guide Overlay */}
                {showIOSGuide && (
                    <div className="fixed inset-0 z-[70] bg-black/80 backdrop-blur-sm flex items-end justify-center" onClick={handleDismiss}>
                        <div className="bg-[#1a1a2e] border-t border-white/10 rounded-t-3xl p-6 w-full max-w-md animate-slide-up" onClick={e => e.stopPropagation()}>
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
                            <button onClick={handleDismiss} className="w-full mt-5 py-3 bg-white/10 text-white font-semibold rounded-xl active:scale-[0.98] transition-transform">
                                확인
                            </button>
                        </div>
                    </div>
                )}

                <style>{`
                    @keyframes slide-up {
                        from { transform: translateY(100%); opacity: 0; }
                        to { transform: translateY(0); opacity: 1; }
                    }
                    .animate-slide-up { animation: slide-up 0.3s ease-out; }
                `}</style>
            </>
        );
    }

    // Android/Desktop install banner
    return (
        <div className="fixed bottom-20 left-3 right-3 z-[60]" style={{ animation: 'slide-up 0.3s ease-out' }}>
            <div className="bg-[#1a1a2e] border border-white/10 rounded-2xl p-4 shadow-2xl shadow-black/50">
                <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2.5">
                        <div className="w-10 h-10 bg-gradient-to-br from-yellow-300 via-amber-500 to-yellow-600 rounded-xl flex items-center justify-center text-white font-extrabold text-sm">B</div>
                        <div>
                            <p className="text-sm font-bold text-white">BitMan 앱 설치</p>
                            <p className="text-[10px] text-gray-400">빠른 접속 + 오프라인 지원</p>
                        </div>
                    </div>
                    <button onClick={handleDismiss} className="text-gray-500 hover:text-white p-1">
                        <i className="fas fa-times text-sm" />
                    </button>
                </div>
                <button
                    onClick={handleInstall}
                    className="w-full py-2.5 bg-gradient-to-r from-amber-500 to-yellow-500 text-black font-bold text-sm rounded-xl active:scale-[0.98] transition-transform"
                >
                    앱 설치하기
                </button>
            </div>
            <style>{`
                @keyframes slide-up {
                    from { transform: translateY(100%); opacity: 0; }
                    to { transform: translateY(0); opacity: 1; }
                }
            `}</style>
        </div>
    );
}
