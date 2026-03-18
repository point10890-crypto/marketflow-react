'use client';

import { useState } from 'react';
import Sidebar from '@/components/layout/Sidebar';
import Header from '@/components/layout/Header';

export default function AdminLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    const [sidebarOpen, setSidebarOpen] = useState(false);

    return (
        <div className="flex h-screen w-full bg-black overflow-hidden">
            <div className="hidden md:flex">
                <Sidebar />
            </div>
            <Sidebar
                mobile
                isOpen={sidebarOpen}
                onClose={() => setSidebarOpen(false)}
            />
            <main className="flex-1 flex flex-col h-full overflow-hidden bg-[#09090b] relative">
                <Header
                    onMenuClick={() => setSidebarOpen(true)}
                />
                <div className="flex-1 overflow-y-auto p-3 md:p-6 pb-20 md:pb-6 scroll-smooth">
                    {children}
                </div>
            </main>
        </div>
    );
}
