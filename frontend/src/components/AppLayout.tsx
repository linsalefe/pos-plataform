'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/contexts/auth-context';
import Sidebar from './Sidebar';
import Webphone from './Webphone';

export default function AppLayout({ children, fullWidth = false }: { children: React.ReactNode; fullWidth?: boolean }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.push('/login');
  }, [user, loading, router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#f8f9fb]">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-7 h-7 text-[#2A658F] animate-spin" />
          <p className="text-sm text-gray-400 animate-pulse">Carregando...</p>
        </div>
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="flex h-screen bg-[#f8f9fb] overflow-hidden">
      <Sidebar />
      <main className={`flex-1 flex flex-col overflow-hidden transition-all duration-200 ${fullWidth ? '' : 'p-6'}`}>
        {children}
      </main>
      <Webphone />
    </div>
  );
}