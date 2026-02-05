'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { GraduationCap, Search, RefreshCw, Loader2, Phone, Filter } from 'lucide-react';
import AppLayout from '@/components/AppLayout';
import { useAuth } from '@/contexts/auth-context';
import api from '@/lib/api';

interface ExactLead {
  id: number;
  exact_id: number;
  name: string;
  phone1: string | null;
  phone2: string | null;
  source: string | null;
  sub_source: string | null;
  stage: string | null;
  funnel_id: number | null;
  sdr_name: string | null;
  register_date: string | null;
  update_date: string | null;
  synced_at: string | null;
}

interface Stats {
  total: number;
  by_stage: Record<string, number>;
  by_sub_source: Record<string, number>;
}

const stageColors: Record<string, string> = {
  'Entrada': 'bg-blue-100 text-blue-700',
  'Pré Qualificado': 'bg-purple-100 text-purple-700',
  'Follow 2': 'bg-amber-100 text-amber-700',
  'Follow 3': 'bg-amber-100 text-amber-700',
  'Follow 4': 'bg-amber-100 text-amber-700',
  'Follows 5': 'bg-orange-100 text-orange-700',
  'Follows 6': 'bg-orange-100 text-orange-700',
  ' Follows 7': 'bg-orange-100 text-orange-700',
  'Follows 8': 'bg-orange-100 text-orange-700',
  ' Follows 9': 'bg-red-100 text-red-700',
  'Agendados': 'bg-cyan-100 text-cyan-700',
  'Reagendamento': 'bg-cyan-100 text-cyan-700',
  'Em Negociação': 'bg-indigo-100 text-indigo-700',
  'Contratos Gerados': 'bg-emerald-100 text-emerald-700',
  'Vendidos': 'bg-green-100 text-green-700',
  'Descartado': 'bg-red-100 text-red-700',
  'Sem contato': 'bg-gray-100 text-gray-700',
  'SEM CONTATO': 'bg-gray-100 text-gray-700',
};

export default function LeadsPosPage() {
  const [leads, setLeads] = useState<ExactLead[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [search, setSearch] = useState('');
  const [stageFilter, setStageFilter] = useState('');
  const [subSourceFilter, setSubSourceFilter] = useState('');
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !user) router.push('/login');
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      loadData();
    }
  }, [user]);

  const loadData = async () => {
    try {
      const [leadsRes, statsRes] = await Promise.all([
        api.get('/exact-leads'),
        api.get('/exact-leads/stats'),
      ]);
      setLeads(leadsRes.data);
      setStats(statsRes.data);
    } catch (err) {
      console.error('Erro ao carregar leads:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    try {
      await api.post('/exact-leads/sync');
      await loadData();
    } catch (err) {
      console.error('Erro ao sincronizar:', err);
    } finally {
      setSyncing(false);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatPhone = (phone: string | null) => {
    if (!phone) return '-';
    return phone.replace(/^55/, '').replace(/(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
  };

  const filteredLeads = leads.filter((lead) => {
    const matchSearch =
      !search ||
      lead.name.toLowerCase().includes(search.toLowerCase()) ||
      (lead.phone1 && lead.phone1.includes(search));
    const matchStage = !stageFilter || lead.stage === stageFilter;
    const matchSubSource = !subSourceFilter || lead.sub_source === subSourceFilter;
    return matchSearch && matchStage && matchSubSource;
  });

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#f8f9fb]">
        <Loader2 className="w-8 h-8 text-[#2A658F] animate-spin" />
      </div>
    );
  }

  if (!user) return null;

  if (loading) {
    return (
      <AppLayout>
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-gray-200 rounded-lg w-48" />
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 bg-gray-200 rounded-2xl" />
            ))}
          </div>
          <div className="h-96 bg-gray-200 rounded-2xl" />
        </div>
      </AppLayout>
    );
  }

  const stages = stats ? Object.keys(stats.by_stage).sort() : [];
  const subSources = stats ? Object.keys(stats.by_sub_source).sort() : [];

  return (
    <AppLayout>
      <div className="space-y-6 max-w-7xl mx-auto overflow-y-auto h-full pb-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <GraduationCap className="w-4 h-4 text-[#2A658F]" />
              <p className="text-sm font-medium text-[#2A658F]">Exact Spotter</p>
            </div>
            <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight">Leads Pós-Graduação</h1>
          </div>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-2 px-4 py-2.5 bg-[#2A658F] text-white rounded-xl text-sm font-medium hover:bg-[#1e4f6e] transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? 'Sincronizando...' : 'Sincronizar'}
          </button>
        </div>

        {/* Stats Cards */}
        {stats && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white rounded-2xl p-5 border border-gray-100">
              <p className="text-2xl font-semibold text-[#27273D]">{stats.total}</p>
              <p className="text-sm text-gray-500">Total de leads</p>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-gray-100">
              <p className="text-2xl font-semibold text-green-600">{stats.by_stage['Vendidos'] || 0}</p>
              <p className="text-sm text-gray-500">Vendidos</p>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-gray-100">
              <p className="text-2xl font-semibold text-emerald-600">{stats.by_stage['Contratos Gerados'] || 0}</p>
              <p className="text-sm text-gray-500">Contratos gerados</p>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-gray-100">
              <p className="text-2xl font-semibold text-red-600">{stats.by_stage['Descartado'] || 0}</p>
              <p className="text-sm text-gray-500">Descartados</p>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className="bg-white rounded-2xl p-4 border border-gray-100 flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Buscar por nome ou telefone..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#2A658F]/20 focus:border-[#2A658F]"
            />
          </div>
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-400" />
            <select
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value)}
              className="px-3 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#2A658F]/20 bg-white"
            >
              <option value="">Todos os estágios</option>
              {stages.map((s) => (
                <option key={s} value={s}>{s} ({stats?.by_stage[s]})</option>
              ))}
            </select>
            <select
              value={subSourceFilter}
              onChange={(e) => setSubSourceFilter(e.target.value)}
              className="px-3 py-2.5 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#2A658F]/20 bg-white"
            >
              <option value="">Todos os cursos</option>
              {subSources.map((s) => (
                <option key={s} value={s}>{s} ({stats?.by_sub_source[s]})</option>
              ))}
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3.5">Nome</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3.5">Telefone</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3.5">Curso</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3.5">Estágio</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3.5">SDR</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-5 py-3.5">Data</th>
                </tr>
              </thead>
              <tbody>
                {filteredLeads.map((lead) => (
                  <tr key={lead.id} className="border-b border-gray-50 hover:bg-gray-50/50 transition-colors">
                    <td className="px-5 py-3.5">
                      <p className="text-sm font-medium text-[#27273D]">{lead.name}</p>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1.5">
                        <Phone className="w-3.5 h-3.5 text-gray-400" />
                        <span className="text-sm text-gray-600">{formatPhone(lead.phone1)}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="text-sm text-gray-600">{lead.sub_source || '-'}</span>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className={`inline-flex px-2.5 py-1 rounded-full text-xs font-medium ${stageColors[lead.stage || ''] || 'bg-gray-100 text-gray-700'}`}>
                        {lead.stage || '-'}
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="text-sm text-gray-600">{lead.sdr_name || '-'}</span>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="text-sm text-gray-500">{formatDate(lead.register_date)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filteredLeads.length === 0 && (
            <div className="text-center py-12 text-gray-400">
              <GraduationCap className="w-10 h-10 mx-auto mb-2 opacity-50" />
              <p className="text-sm">Nenhum lead encontrado</p>
            </div>
          )}
          <div className="px-5 py-3 border-t border-gray-100 text-sm text-gray-500">
            {filteredLeads.length} de {leads.length} leads
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
