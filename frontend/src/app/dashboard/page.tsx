import DashboardClient from './DashboardClient';

// ── 클라이언트 데이터 fetch (SSR 없이 — Cloudflare static export 호환)
export default function DashboardPage() {
    return <DashboardClient initialData={{ briefing: null, krGate: null, cryptoDom: null }} />;
}
