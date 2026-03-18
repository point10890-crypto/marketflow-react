import Sidebar from '@/components/layout/Sidebar';
import Header from '@/components/layout/Header';
import DisclaimerBanner from '@/components/ui/DisclaimerBanner';

export default function DashboardLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    return (
        <div className="flex h-screen w-full bg-black overflow-hidden">
            <Sidebar />
            <main className="flex-1 flex flex-col h-full overflow-hidden bg-[#09090b] relative">
                <Header title="Dashboard" />
                <div className="flex-1 overflow-y-auto p-6 scroll-smooth">
                    {children}
                </div>
                <DisclaimerBanner />
            </main>
        </div>
    );
}
