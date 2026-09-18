import './market-design.css';
export default function ChatbotPage() {
    return (
        <div className="market-workspace space-y-4">
            <header className="dash-page-header market-page-header">
                <h1 className="market-title">Smart Money Bot</h1>
            </header>
            <section className="dash-panel market-panel market-empty-state" role="status">
                <i className="fas fa-comment-dots text-2xl text-[#73b7ff]" aria-hidden="true" />
                <h2 className="dash-section-title">Currently unavailable</h2>
                <p>This feature is under maintenance.</p>
            </section>
        </div>
    );
}
