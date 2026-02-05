'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Users, ArrowDownLeft, ArrowUpRight, TrendingUp,
  UserPlus, Loader2, MessageSquare, Activity,
} from 'lucide-react';
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

const statusColors: Record<string, { bg: string; text: string; bar: string; dot: string }> = {
  novo: { bg: 'bg-blue-50', text: 'text-blue-700', bar: 'bg-blue-500', dot: 'bg-blue-500' },
  em_contato: { bg: 'bg-amber-50', text: 'text-amber-700', bar: 'bg-amber-500', dot: 'bg-amber-500' },
  qualificado: { bg: 'bg-purple-50', text: 'text-purple-700', bar: 'bg-purple-500', dot: 'bg-purple-500' },
  negociando: { bg: 'bg-cyan-50', text: 'text-cyan-700', bar: 'bg-cyan-500', dot: 'bg-cyan-500' },
  convertido: { bg: 'bg-emerald-50', text: 'text-emerald-700', bar: 'bg-emerald-500', dot: 'bg-emerald-500' },
  perdido: { bg: 'bg-red-50', text: 'text-red-700', bar: 'bg-red-500', dot: 'bg-red-500' },
};

const statCards = [
  { key: 'total_contacts', label: 'Total de contatos', icon: Users, iconBg: 'bg-blue-50', iconColor: 'text-blue-600' },
  { key: 'new_today', label: 'Novos hoje', icon: UserPlus, iconBg: 'bg-emerald-50', iconColor: 'text-emerald-600' },
  { key: 'inbound_today', label: 'Recebidas hoje', icon: ArrowDownLeft, iconBg: 'bg-purple-50', iconColor: 'text-purple-600' },
  { key: 'outbound_today', label: 'Enviadas hoje', icon: ArrowUpRight, iconBg: 'bg-amber-50', iconColor: 'text-amber-600' },
];

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Bom dia';
  if (h < 18) return 'Boa tarde';
  return 'Boa noite';
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);
  const [hoveredBar, setHoveredBar] = useState<number | null>(null);
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
        <div className="animate-pulse space-y-6 max-w-7xl mx-auto">
          <div className="space-y-2">
            <div className="h-4 bg-gray-200 rounded w-32" />
            <div className="h-7 bg-gray-200 rounded w-56" />
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-[120px] bg-gray-200 rounded-2xl" />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 h-[300px] bg-gray-200 rounded-2xl" />
            <div className="h-[300px] bg-gray-200 rounded-2xl" />
          </div>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="space-y-6 max-w-7xl mx-auto overflow-y-auto h-full pb-6">

        {/* ── Header ── */}
        <div className={`transition-all duration-700 ease-out ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'}`}>
          <p className="text-sm text-gray-400 mb-0.5">{getGreeting()},</p>
          <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight">
            {user.name.split(' ')[0]}
          </h1>
        </div>

        {/* ── Stats Cards ── */}
        <div className={`grid grid-cols-2 lg:grid-cols-4 gap-4 transition-all duration-700 ease-out delay-100 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          {statCards.map((card) => {
            const Icon = card.icon;
            const value = stats[card.key as keyof Stats] as number;
            return (
              <div
                key={card.key}
                className="bg-white rounded-2xl p-5 border border-gray-100 hover:border-gray-200 hover:shadow-sm transition-all duration-200 group"
              >
                <div className="flex items-center justify-between mb-4">
                  <div className={`w-10 h-10 ${card.iconBg} rounded-xl flex items-center justify-center group-hover:scale-105 transition-transform duration-200`}>
                    <Icon className={`w-[18px] h-[18px] ${card.iconColor}`} />
                  </div>
                </div>
                <p className="text-2xl font-bold text-[#27273D] tabular-nums">{value}</p>
                <p className="text-[13px] text-gray-400 mt-0.5">{card.label}</p>
              </div>
            );
          })}
        </div>

        {/* ── Gráfico + Funil ── */}
        <div className={`grid grid-cols-1 lg:grid-cols-3 gap-4 transition-all duration-700 ease-out delay-200 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>

          {/* Gráfico de barras */}
          <div className="lg:col-span-2 bg-white rounded-2xl p-6 border border-gray-100">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-[15px] font-semibold text-[#27273D]">Mensagens na semana</h2>
                <p className="text-sm text-gray-400 mt-0.5">
                  <span className="font-semibold text-[#27273D]">{stats.messages_week}</span> nos últimos 7 dias
                </p>
              </div>
              <div className="w-9 h-9 bg-[#2A658F]/8 rounded-lg flex items-center justify-center">
                <TrendingUp className="w-4 h-4 text-[#2A658F]" />
              </div>
            </div>

            <div className="flex items-end justify-between gap-2 h-48">
              {stats.daily_messages.map((day, i) => {
                const pct = (day.count / maxDailyCount) * 100;
                const isHovered = hoveredBar === i;
                const isToday = i === stats.daily_messages.length - 1;

                return (
                  <div
                    key={i}
                    className="flex-1 flex flex-col items-center gap-2 cursor-default"
                    onMouseEnter={() => setHoveredBar(i)}
                    onMouseLeave={() => setHoveredBar(null)}
                  >
                    {/* Tooltip valor */}
                    <span className={`text-xs font-semibold tabular-nums transition-all duration-200 ${
                      isHovered ? 'text-[#2A658F]' : 'text-gray-400'
                    }`}>
                      {day.count}
                    </span>

                    {/* Barra */}
                    <div className="w-full bg-gray-50 rounded-lg overflow-hidden relative" style={{ height: '130px' }}>
                      <div
                        className={`w-full rounded-lg transition-all duration-500 ease-out ${
                          isToday
                            ? 'bg-[#2A658F]'
                            : isHovered
                              ? 'bg-[#2A658F]/70'
                              : 'bg-[#2A658F]/25'
                        }`}
                        style={{
                          height: `${Math.max(pct, day.count > 0 ? 6 : 2)}%`,
                          marginTop: `${100 - Math.max(pct, day.count > 0 ? 6 : 2)}%`,
                        }}
                      />
                    </div>

                    {/* Label dia */}
                    <span className={`text-[11px] font-medium transition-colors duration-200 ${
                      isToday ? 'text-[#2A658F]' : 'text-gray-400'
                    }`}>
                      {day.day}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Funil de leads */}
          <div className="bg-white rounded-2xl p-6 border border-gray-100">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-[15px] font-semibold text-[#27273D]">Funil de leads</h2>
                <p className="text-sm text-gray-400 mt-0.5">
                  <span className="font-semibold text-[#27273D]">{stats.total_contacts}</span> contatos
                </p>
              </div>
              <div className="w-9 h-9 bg-purple-50 rounded-lg flex items-center justify-center">
                <Activity className="w-4 h-4 text-purple-600" />
              </div>
            </div>

            <div className="space-y-3.5">
              {Object.entries(statusLabels).map(([key, label]) => {
                const count = stats.status_counts[key] || 0;
                const pct = stats.total_contacts > 0 ? (count / stats.total_contacts) * 100 : 0;
                const colors = statusColors[key];
                return (
                  <div key={key}>
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${colors.dot}`} />
                        <span className="text-[13px] text-gray-600">{label}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] text-gray-400 tabular-nums">
                          {pct.toFixed(0)}%
                        </span>
                        <span className={`text-[11px] font-semibold px-1.5 py-0.5 rounded-md ${colors.bg} ${colors.text} tabular-nums`}>
                          {count}
                        </span>
                      </div>
                    </div>
                    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
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

        {/* ── Resumo rodapé ── */}
        <div className={`grid grid-cols-2 lg:grid-cols-4 gap-4 transition-all duration-700 ease-out delay-300 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          {[
            { label: 'Mensagens hoje', value: stats.messages_today, icon: MessageSquare, color: 'text-[#2A658F]', bg: 'bg-[#2A658F]/8' },
            { label: 'Convertidos', value: stats.status_counts['convertido'] || 0, icon: Users, color: 'text-emerald-600', bg: 'bg-emerald-50' },
            { label: 'Negociando', value: stats.status_counts['negociando'] || 0, icon: TrendingUp, color: 'text-amber-600', bg: 'bg-amber-50' },
            { label: 'Qualificados', value: stats.status_counts['qualificado'] || 0, icon: Activity, color: 'text-purple-600', bg: 'bg-purple-50' },
          ].map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.label} className="bg-white rounded-2xl p-4 border border-gray-100 flex items-center gap-4">
                <div className={`w-10 h-10 ${item.bg} rounded-xl flex items-center justify-center flex-shrink-0`}>
                  <Icon className={`w-[18px] h-[18px] ${item.color}`} />
                </div>
                <div>
                  <p className={`text-xl font-bold tabular-nums ${item.color}`}>{item.value}</p>
                  <p className="text-[12px] text-gray-400">{item.label}</p>
                </div>
              </div>
            );
          })}
        </div>

      </div>
    </AppLayout>
  );
}