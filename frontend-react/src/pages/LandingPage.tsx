import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

export default function LandingPage() {
    const navigate = useNavigate();
    const [animState, setAnimState] = useState<'idle' | 'ripple' | 'exit'>('idle');
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        // Entrance animation
        const t = setTimeout(() => setMounted(true), 50);
        return () => clearTimeout(t);
    }, []);

    const handleEnter = () => {
        if (animState !== 'idle') return;
        setAnimState('ripple');
        setTimeout(() => setAnimState('exit'), 400);
        setTimeout(() => navigate('/dashboard'), 900);
    };

    return (
        <div
            className={`landing-root ${mounted ? 'landing-in' : ''} ${animState === 'exit' ? 'landing-exit' : ''}`}
        >
            {/* Ambient grid */}
            <div className="landing-grid" aria-hidden />

            {/* Glow orbs */}
            <div className="landing-orb landing-orb-1" aria-hidden />
            <div className="landing-orb landing-orb-2" aria-hidden />

            {/* Content */}
            <div className="landing-content">
                {/* Logo */}
                <div className="landing-logo">
                    <div className="landing-logo-icon">
                        <span>B</span>
                    </div>
                    <span className="landing-logo-text">BitMan</span>
                </div>

                {/* Headline */}
                <div className="landing-headline">
                    <h1>
                        AI 마켓<br />
                        <span className="landing-headline-accent">인사이트</span>
                    </h1>
                    <p className="landing-subtitle">
                        KR · US · Crypto<br />실시간 시장 분석 대시보드
                    </p>
                </div>

                {/* Stats row */}
                <div className="landing-stats">
                    {[
                        { label: 'KR VCP', value: 'LIVE' },
                        { label: 'US Market', value: 'LIVE' },
                        { label: 'Crypto', value: 'LIVE' },
                    ].map((s) => (
                        <div key={s.label} className="landing-stat">
                            <span className="landing-stat-dot" />
                            <span className="landing-stat-label">{s.label}</span>
                        </div>
                    ))}
                </div>

                {/* CTA Button */}
                <button
                    className={`landing-cta ${animState === 'ripple' ? 'landing-cta-ripple' : ''}`}
                    onClick={handleEnter}
                    aria-label="대시보드 열기"
                >
                    <span className="landing-cta-text">대시보드 보기</span>
                    <span className="landing-cta-arrow">
                        <i className="fas fa-arrow-right" />
                    </span>
                    <span className="landing-cta-ripple-bg" />
                </button>

                <p className="landing-hint">마켓 서머리 · VCP · 종가베팅</p>
            </div>

            {/* Exit overlay */}
            <div className={`landing-exit-overlay ${animState === 'exit' ? 'landing-exit-overlay-active' : ''}`} aria-hidden />
        </div>
    );
}
