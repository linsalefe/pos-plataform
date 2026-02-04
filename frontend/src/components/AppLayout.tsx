'use client';

import Sidebar from './Sidebar';

export default function AppLayout({ children, fullWidth = false }: { children: React.ReactNode; fullWidth?: boolean }) {
  return (
    <div className="flex h-screen bg-[#f8f9fb] overflow-hidden">
      <Sidebar />
      <main className={`flex-1 overflow-hidden ${fullWidth ? '' : 'p-6'}`}>
        {children}
      </main>
    </div>
  );
}
