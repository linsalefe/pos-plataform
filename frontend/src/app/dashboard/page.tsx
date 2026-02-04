'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Users, ArrowDownLeft, ArrowUpRight, TrendingUp, UserPlus, Sparkles, Loader2 } from 'lucide-react';
import AppLayout from '@/components/AppLayout';
import { useAuth } from '@/contexts/auth-context';
import api from '@/lib/api';

interface Stats {
  total_contacts: number;
  new_today: number;
  messages_today: number;
  inbound_today: number;
  outbound_today: number;
  messages_week: number;
  status_counts: Record<string, number>;
  daily_messages: { date: string; day: string; count: number }[];
}

const statusLabels: Record<string, string> = {
  novo: 'Novos',
  em_contato: 'Em contato',
  qualificado: 'Qualificados',
  negociando: 'Negociando',
  convertido: 'Convertidos',
  perdido: 'Perdidos',
};

const statusColors: Record<string, { bg: string; text: string; bar: string }> = {
  novo: { bg: 'bg-blue-50', text: 'text-blue-700', bar: 'bg-blue-500' },
  em_contato: { bg: 'bg-amber-50', text: 'text-amber-700', bar: 'bg-amber-500' },
  qualificado: { bg: 'bg-purple-50', text: 'text-purple-700', bar: 'bg-purple-500' },
  negociando: { bg: 'bg-cyan-50', text: 'text-cyan-700', bar: 'bg-cyan-500' },
  convertido: { bg: 'bg-emerald-50', text: 'text-emerald-700', bar: 'bg-emerald-500' },
  perdido: { bg: 'bg-red-50', text: 'text-red-700', bar: 'bg-red-500' },
};

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  useEffect(() => { setMounted(true); }, []);
  useEffect(() => { if (!authLoading && !user) router.push('/login'); }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      loadStats();
      const interval = setInterval(loadStats, 30000);
      return () => clearInterval(interval);
    }
  }, [user]);

  const loadStats = async () => {
    try {
      const res = await api.get('/dashboard/stats');
      setStats(res.data);
    } catch (err) {
      console.error('Erro ao carregar stats:', err);
    } finally {
      setLoading(false);
    }
  };

  const maxDailyCount = stats ? Math.max(...stats.daily_messages.map(d => d.count), 1) : 1;

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#f8f9fb]">
        <Loader2 className="w-8 h-8 text-[#2A658F] animate-spin" />
      </div>
    );
  }

  if (!user) return null;

  if (loading || !stats) {
    return (
      <AppLayout>
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-gray-200 rounded-lg w-48" />
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-32 bg-gray-200 rounded-2xl" />
            ))}
          </div>
          <div className="h-72 bg-gray-200 rounded-2xl" />
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="space-y-6 max-w-7xl mx-auto overflow-y-auto h-full pb-6">
        {/* Header */}
        <div className={`transition-all duration-700 ease-out ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'}`}>
          <div className="flex items-center gap-2 mb-1">
            <Sparkles className="w-4 h-4 text-[#2A658F]" />
            <p className="text-sm font-medium text-[#2A658F]">Visão geral</p>
          </div>
          <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight">Dashboard</h1>
        </div>

        {/* Stats Cards */}
        <div className={`grid grid-cols-2 lg:grid-cols-4 gap-4 transition-all duration-700 ease-out delay-100 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <div className="bg-white rounded-2xl p-5 border border-gray-100 hover:shadow-md transition-shadow">
            <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center mb-3">
              <Users className="w-5 h-5 text-blue-600" />
            </div>
            <p className="text-2xl font-semibold text-[#27273D]">{stats.total_contacts}</p>
            <p className="text-sm text-gray-500">Total de contatos</p>
          </div>

          <div className="bg-white rounded-2xl p-5 border border-gray-100 hover:shadow-md transition-shadow">
            <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center mb-3">
              <UserPlus className="w-5 h-5 text-emerald-600" />
            </div>
            <p className="text-2xl font-semibold text-[#27273D]">{stats.new_today}</p>
            <p className="text-sm text-gray-500">Novos hoje</p>
          </div>

          <div className="bg-white rounded-2xl p-5 border border-gray-100 hover:shadow-md transition-shadow">
            <div className="w-10 h-10 bg-purple-50 rounded-xl flex items-center justify-center mb-3">
              <ArrowDownLeft className="w-5 h-5 text-purple-600" />
            </div>
            <p className="text-2xl font-semibold text-[#27273D]">{stats.inbound_today}</p>
            <p className="text-sm text-gray-500">Recebidas hoje</p>
          </div>

          <div className="bg-white rounded-2xl p-5 border border-gray-100 hover:shadow-md transition-shadow">
            <div className="w-10 h-10 bg-amber-50 rounded-xl flex items-center justify-center mb-3">
              <ArrowUpRight className="w-5 h-5 text-amber-600" />
            </div>
            <p className="text-2xl font-semibold text-[#27273D]">{stats.outbound_today}</p>
            <p className="text-sm text-gray-500">Enviadas hoje</p>
          </div>
        </div>

        <div className={`grid grid-cols-1 lg:grid-cols-3 gap-4 transition-all duration-700 ease-out delay-200 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          {/* Gráfico de barras */}
          <div className="lg:col-span-2 bg-white rounded-2xl p-6 border border-gray-100">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-base font-semibold text-[#27273D]">Mensagens na semana</h2>
                <p className="text-sm text-gray-500">{stats.messages_week} mensagens nos últimos 7 dias</p>
              </div>
              <div className="w-10 h-10 bg-[#2A658F]/10 rounded-xl flex items-center justify-center">
                <TrendingUp className="w-5 h-5 text-[#2A658F]" />
              </div>
            </div>
            <div className="flex items-end justify-between gap-3 h-44">
              {stats.daily_messages.map((day, i) => (
                <div key={i} className="flex-1 flex flex-col items-center gap-2">
                  <span className="text-xs font-medium text-gray-500">{day.count}</span>
                  <div className="w-full bg-gray-100 rounded-lg overflow-hidden" style={{ height: '120px' }}>
                    <div
                      className="w-full bg-gradient-to-t from-[#2A658F] to-[#4d9fd4] rounded-lg transition-all duration-700 ease-out"
                      style={{
                        height: `${(day.count / maxDailyCount) * 100}%`,
                        marginTop: `${100 - (day.count / maxDailyCount) * 100}%`,
                      }}
                    />
                  </div>
                  <span className="text-xs text-gray-400">{day.date}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Funil de leads */}
          <div className="bg-white rounded-2xl p-6 border border-gray-100">
            <h2 className="text-base font-semibold text-[#27273D] mb-1">Funil de leads</h2>
            <p className="text-sm text-gray-500 mb-5">{stats.total_contacts} contatos</p>
            <div className="space-y-3">
              {Object.entries(statusLabels).map(([key, label]) => {
                const count = stats.status_counts[key] || 0;
                const pct = stats.total_contacts > 0 ? (count / stats.total_contacts) * 100 : 0;
                const colors = statusColors[key];
                return (
                  <div key={key}>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-sm text-gray-600">{label}</span>
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${colors.bg} ${colors.text}`}>
                        {count}
                      </span>
                    </div>
                    <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full ${colors.bar} rounded-full transition-all duration-700 ease-out`}
                        style={{ width: `${Math.max(pct, count > 0 ? 4 : 0)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Resumo rápido */}
        <div className={`bg-white rounded-2xl p-6 border border-gray-100 transition-all duration-700 ease-out delay-300 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <h2 className="text-base font-semibold text-[#27273D] mb-4">Resumo</h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="text-center">
              <p className="text-3xl font-bold text-[#2A658F]">{stats.messages_today}</p>
              <p className="text-sm text-gray-500 mt-1">Mensagens hoje</p>
            </div>
            <div className="text-center">
              <p className="text-3xl font-bold text-emerald-600">{stats.status_counts['convertido'] || 0}</p>
              <p className="text-sm text-gray-500 mt-1">Convertidos</p>
            </div>
            <div className="text-center">
              <p className="text-3xl font-bold text-amber-600">{stats.status_counts['negociando'] || 0}</p>
              <p className="text-sm text-gray-500 mt-1">Negociando</p>
            </div>
            <div className="text-center">
              <p className="text-3xl font-bold text-purple-600">{stats.status_counts['qualificado'] || 0}</p>
              <p className="text-sm text-gray-500 mt-1">Qualificados</p>
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
