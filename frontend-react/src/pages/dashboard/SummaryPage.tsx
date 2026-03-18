import DashboardClient from './DashboardClient';

export default function SummaryPage() {
    return <DashboardClient initialData={{ briefing: null, krGate: null, cryptoDom: null }} />;
}
