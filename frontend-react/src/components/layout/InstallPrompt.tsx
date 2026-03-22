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
        // Check if already installed (standalone mode)
        if (window.matchMedia('(display-mode: standalone)').matches) return;

        // Check if dismissed recently (24h cooldown instead of 7d for better conversion)
        const dismissed = localStorage.getItem('install-dismissed');
        if (dismissed && Date.now() - Number(dismissed) < 24 * 60 * 60 * 1000) return;

        // iOS detection
        const ua = navigator.userAgent;
        const ios = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
        setIsIOS(ios);

        // Check globally captured prompt
        const captured = (window as any).__pwaInstallPrompt;
        if (captured) {
            setDeferredPrompt(captured as BeforeInstallPromptEvent);
            (window as any).__pwaInstallPrompt = null;
        }

        // Listen for future install prompt
        const handler = (e: Event) => {
            e.preventDefault();
            setDeferredPrompt(e as BeforeInstallPromptEvent);
        };
        window.addEventListener('beforeinstallprompt', handler);

        // Always show banner after 3 seconds for first-time users
        // (works regardless of beforeinstallprompt timing)
        const timer = setTimeout(() => setShowBanner(true), 3000);

        return () => {
            clearTimeout(timer);
            window.removeEventListener('beforeinstallprompt', handler);
        };
    }, []);

    const [showDesktopGuide, setShowDesktopGuide] = useState(false);

    const handleInstall = async () => {
        if (deferredPrompt) {
            await deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            if (outcome === 'accepted') {
                setShowBanner(false);
            }
            setDeferredPrompt(null);
        } else {
            // No native prompt available — show manual guide
            setShowDesktopGuide(true);
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
                <div className="fixed bottom-[5.5rem] md:bottom-6 left-3 right-3 z-[60] animate-slide-up">
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
        <>
            <div className="fixed bottom-[5.5rem] md:bottom-6 left-3 right-3 z-[60]" style={{ animation: 'slide-up 0.3s ease-out' }}>
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
            </div>

            {/* Desktop install guide (when native prompt unavailable) */}
            {showDesktopGuide && (
                <div className="fixed inset-0 z-[70] bg-black/80 backdrop-blur-sm flex items-center justify-center" onClick={() => setShowDesktopGuide(false)}>
                    <div className="bg-[#1a1a2e] border border-white/10 rounded-2xl p-6 w-full max-w-sm mx-4" onClick={e => e.stopPropagation()}>
                        <h3 className="text-lg font-bold text-white mb-4 text-center">Chrome에서 앱 설치</h3>
                        <div className="space-y-4">
                            <div className="flex items-start gap-3">
                                <span className="w-8 h-8 rounded-full bg-blue-500/20 text-blue-400 flex items-center justify-center text-sm font-bold shrink-0">1</span>
                                <p className="text-sm text-gray-300">주소창 오른쪽의 <i className="fas fa-download text-blue-400 mx-1" /> 설치 아이콘 클릭</p>
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
                        <button onClick={() => setShowDesktopGuide(false)} className="w-full mt-5 py-3 bg-white/10 text-white font-semibold rounded-xl active:scale-[0.98] transition-transform">
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
            `}</style>
        </>
    );
}
