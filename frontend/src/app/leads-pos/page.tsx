'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { GraduationCap, Search, RefreshCw, Loader2, Phone, Filter, X, Mail, Briefcase, MapPin, Clock, ExternalLink, MessageCircle, TrendingUp, FileCheck, XCircle as XCircleIcon, Users } from 'lucide-react';
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

interface LeadDetails {
  lead: {
    id: number; name: string; phone1: string | null; phone2: string | null;
    stage: string | null; source: string | null; sub_source: string | null;
    sdr: string | null; register_date: string | null; update_date: string | null;
    description: string | null; city: string | null; state: string | null;
    public_link: string | null;
  };
  persons: { name: string | null; email: string | null; job_title: string | null; phone1: string | null; }[];
  qualifications: { origin_stage: string | null; stage: string | null; score: number | null; qualification_date: string | null; meeting_date: string | null; user_action: string | null; }[];
}

const stageColors: Record<string, string> = {
  'Entrada': 'bg-blue-50 text-blue-700',
  'Pré Qualificado': 'bg-purple-50 text-purple-700',
  'Follow 2': 'bg-amber-50 text-amber-700',
  'Follow 3': 'bg-amber-50 text-amber-700',
  'Follow 4': 'bg-amber-50 text-amber-700',
  'Follows 5': 'bg-orange-50 text-orange-700',
  'Follows 6': 'bg-orange-50 text-orange-700',
  ' Follows 7': 'bg-orange-50 text-orange-700',
  'Follows 8': 'bg-orange-50 text-orange-700',
  ' Follows 9': 'bg-red-50 text-red-700',
  'Agendados': 'bg-cyan-50 text-cyan-700',
  'Reagendamento': 'bg-cyan-50 text-cyan-700',
  'Em Negociação': 'bg-indigo-50 text-indigo-700',
  'Contratos Gerados': 'bg-emerald-50 text-emerald-700',
  'Vendidos': 'bg-green-50 text-green-700',
  'Descartado': 'bg-red-50 text-red-700',
  'Sem contato': 'bg-gray-100 text-gray-600',
  'SEM CONTATO': 'bg-gray-100 text-gray-600',
};

export default function LeadsPosPage() {
  const [leads, setLeads] = useState<ExactLead[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [search, setSearch] = useState('');
  const [stageFilter, setStageFilter] = useState('');
  const [subSourceFilter, setSubSourceFilter] = useState('');
  const [selectedLead, setSelectedLead] = useState<ExactLead | null>(null);
  const [leadDetails, setLeadDetails] = useState<LeadDetails | null>(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [mounted, setMounted] = useState(false);
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  useEffect(() => { setMounted(true); }, []);

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

  const openLeadPopup = async (lead: ExactLead) => {
    setSelectedLead(lead);
    setLeadDetails(null);
    setLoadingDetails(true);
    try {
      const res = await api.get('/exact-leads/' + lead.exact_id + '/details');
      setLeadDetails(res.data);
    } catch (err) {
      console.error('Erro ao carregar detalhes:', err);
    } finally {
      setLoadingDetails(false);
    }
  };

  const closeLeadPopup = () => {
    setSelectedLead(null);
    setLeadDetails(null);
  };

  const formatQualDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
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

  const getInitials = (name: string) => name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
  const getAvatarColor = (name: string) => {
    const c = ['from-blue-500 to-blue-600','from-purple-500 to-purple-600','from-emerald-500 to-emerald-600','from-orange-500 to-orange-600','from-pink-500 to-pink-600','from-cyan-500 to-cyan-600'];
    return c[name.charCodeAt(0) % c.length];
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
        <div className="animate-pulse space-y-6 max-w-7xl mx-auto">
          <div className="space-y-2">
            <div className="h-4 bg-gray-200 rounded w-32" />
            <div className="h-7 bg-gray-200 rounded w-56" />
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-[100px] bg-gray-200 rounded-2xl" />
            ))}
          </div>
          <div className="h-16 bg-gray-200 rounded-2xl" />
          <div className="h-96 bg-gray-200 rounded-2xl" />
        </div>
      </AppLayout>
    );
  }

  const stages = stats ? Object.keys(stats.by_stage).sort() : [];
  const subSources = stats ? Object.keys(stats.by_sub_source).sort() : [];
  const hasActiveFilters = search || stageFilter || subSourceFilter;

  return (
    <AppLayout>
      <div className="space-y-6 max-w-7xl mx-auto overflow-y-auto h-full pb-6">

        {/* Header */}
        <div className={`flex items-center justify-between transition-all duration-700 ease-out ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'}`}>
          <div>
            <p className="text-sm text-gray-400 mb-0.5">Exact Spotter</p>
            <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight">Leads Pós-Graduação</h1>
          </div>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-2 px-4 py-2.5 bg-[#2A658F] text-white rounded-xl text-[13px] font-medium hover:bg-[#1f5375] hover:shadow-lg hover:shadow-[#2A658F]/20 active:scale-[0.98] transition-all disabled:opacity-50 disabled:active:scale-100"
          >
            <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? 'Sincronizando...' : 'Sincronizar'}
          </button>
        </div>

        {/* Stats Cards */}
        {stats && (
          <div className={`grid grid-cols-2 lg:grid-cols-4 gap-4 transition-all duration-700 ease-out delay-100 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
            <div className="bg-white rounded-2xl p-5 border border-gray-100 flex items-center gap-4 hover:border-gray-200 hover:shadow-sm transition-all group">
              <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center group-hover:scale-105 transition-transform">
                <Users className="w-[18px] h-[18px] text-blue-600" />
              </div>
              <div>
                <p className="text-2xl font-bold text-[#27273D] tabular-nums">{stats.total}</p>
                <p className="text-[12px] text-gray-400">Total de leads</p>
              </div>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-gray-100 flex items-center gap-4 hover:border-gray-200 hover:shadow-sm transition-all group">
              <div className="w-10 h-10 bg-green-50 rounded-xl flex items-center justify-center group-hover:scale-105 transition-transform">
                <TrendingUp className="w-[18px] h-[18px] text-green-600" />
              </div>
              <div>
                <p className="text-2xl font-bold text-green-600 tabular-nums">{stats.by_stage['Vendidos'] || 0}</p>
                <p className="text-[12px] text-gray-400">Vendidos</p>
              </div>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-gray-100 flex items-center gap-4 hover:border-gray-200 hover:shadow-sm transition-all group">
              <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center group-hover:scale-105 transition-transform">
                <FileCheck className="w-[18px] h-[18px] text-emerald-600" />
              </div>
              <div>
                <p className="text-2xl font-bold text-emerald-600 tabular-nums">{stats.by_stage['Contratos Gerados'] || 0}</p>
                <p className="text-[12px] text-gray-400">Contratos</p>
              </div>
            </div>
            <div className="bg-white rounded-2xl p-5 border border-gray-100 flex items-center gap-4 hover:border-gray-200 hover:shadow-sm transition-all group">
              <div className="w-10 h-10 bg-red-50 rounded-xl flex items-center justify-center group-hover:scale-105 transition-transform">
                <XCircleIcon className="w-[18px] h-[18px] text-red-500" />
              </div>
              <div>
                <p className="text-2xl font-bold text-red-500 tabular-nums">{stats.by_stage['Descartado'] || 0}</p>
                <p className="text-[12px] text-gray-400">Descartados</p>
              </div>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className={`bg-white rounded-2xl p-4 border border-gray-100 transition-all duration-700 ease-out delay-150 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Buscar por nome ou telefone..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] focus:bg-white transition-all"
              />
            </div>
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-gray-400" />
              <select
                value={stageFilter}
                onChange={(e) => setStageFilter(e.target.value)}
                className="px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] transition-all appearance-none cursor-pointer"
              >
                <option value="">Todos os estágios</option>
                {stages.map((s) => (
                  <option key={s} value={s}>{s} ({stats?.by_stage[s]})</option>
                ))}
              </select>
              <select
                value={subSourceFilter}
                onChange={(e) => setSubSourceFilter(e.target.value)}
                className="px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] transition-all appearance-none cursor-pointer"
              >
                <option value="">Todos os cursos</option>
                {subSources.map((s) => (
                  <option key={s} value={s}>{s} ({stats?.by_sub_source[s]})</option>
                ))}
              </select>
              {hasActiveFilters && (
                <button
                  onClick={() => { setSearch(''); setStageFilter(''); setSubSourceFilter(''); }}
                  className="px-3 py-2.5 text-[12px] font-medium text-gray-500 hover:text-red-500 hover:bg-red-50 rounded-xl transition-colors"
                >
                  Limpar filtros
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Table */}
        <div className={`bg-white rounded-2xl border border-gray-100 overflow-hidden transition-all duration-700 ease-out delay-200 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-5 py-3">Nome</th>
                  <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-5 py-3">Telefone</th>
                  <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-5 py-3">Curso</th>
                  <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-5 py-3">Estágio</th>
                  <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-5 py-3">SDR</th>
                  <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-5 py-3">Data</th>
                </tr>
              </thead>
              <tbody>
                {filteredLeads.map((lead) => (
                  <tr key={lead.id} onClick={() => openLeadPopup(lead)} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors cursor-pointer group">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${getAvatarColor(lead.name)} flex items-center justify-center text-white text-[10px] font-semibold flex-shrink-0 opacity-80 group-hover:opacity-100 transition-opacity`}>
                          {getInitials(lead.name)}
                        </div>
                        <p className="text-[13px] font-medium text-[#27273D] group-hover:text-[#2A658F] transition-colors">{lead.name}</p>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-1.5">
                        <Phone className="w-3 h-3 text-gray-400" />
                        <span className="text-[13px] text-gray-500 tabular-nums">{formatPhone(lead.phone1)}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="text-[13px] text-gray-500">{lead.sub_source || '-'}</span>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className={`inline-flex px-2 py-0.5 rounded-md text-[11px] font-medium ${stageColors[lead.stage || ''] || 'bg-gray-100 text-gray-600'}`}>
                        {lead.stage || '-'}
                      </span>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="text-[13px] text-gray-500">{lead.sdr_name || '-'}</span>
                    </td>
                    <td className="px-5 py-3.5">
                      <span className="text-[13px] text-gray-400 tabular-nums">{formatDate(lead.register_date)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filteredLeads.length === 0 && (
            <div className="text-center py-16 text-gray-400">
              <GraduationCap className="w-10 h-10 mx-auto mb-3 text-gray-300" />
              <p className="text-sm">Nenhum lead encontrado</p>
            </div>
          )}
          <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-between">
            <span className="text-[12px] text-gray-400">
              {filteredLeads.length} de {leads.length} leads
            </span>
            {hasActiveFilters && (
              <span className="text-[12px] text-[#2A658F] font-medium">Filtros ativos</span>
            )}
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════ */}
      {/* MODAL DETALHES DO LEAD                 */}
      {/* ══════════════════════════════════════ */}
      {selectedLead && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={closeLeadPopup}>
          <div className="bg-white rounded-2xl w-full max-w-3xl shadow-2xl mx-4 max-h-[85vh] overflow-hidden flex flex-col border border-gray-100" onClick={e => e.stopPropagation()}>
            {/* Header */}
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-3">
                <div className={`w-11 h-11 rounded-xl bg-gradient-to-br ${getAvatarColor(selectedLead.name)} flex items-center justify-center text-white text-xs font-bold shadow-sm`}>
                  {getInitials(selectedLead.name)}
                </div>
                <div>
                  <h2 className="text-[15px] font-semibold text-[#27273D]">{selectedLead.name}</h2>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className={`inline-flex px-2 py-0.5 rounded-md text-[11px] font-medium ${stageColors[selectedLead.stage || ''] || 'bg-gray-100 text-gray-600'}`}>
                      {selectedLead.stage || '-'}
                    </span>
                    <span className="text-[12px] text-gray-400">{selectedLead.sub_source || '-'}</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {leadDetails?.lead?.public_link && (
                  <a href={leadDetails.lead.public_link} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 px-3 py-2 text-[12px] font-medium text-[#2A658F] bg-[#2A658F]/8 rounded-xl hover:bg-[#2A658F]/15 transition-colors">
                    <ExternalLink className="w-3.5 h-3.5" /> Exact
                  </a>
                )}
                <button onClick={closeLeadPopup} className="p-2 hover:bg-gray-100 rounded-xl transition-colors">
                  <X className="w-5 h-5 text-gray-400" />
                </button>
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-6">
              {loadingDetails ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="w-8 h-8 text-[#2A658F] animate-spin" />
                </div>
              ) : leadDetails ? (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* Coluna esquerda */}
                  <div className="space-y-5">
                    {/* Contato */}
                    <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
                      <h3 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-3">Contato</h3>
                      <div className="space-y-2.5">
                        <div className="flex items-center gap-2.5">
                          <Phone className="w-4 h-4 text-gray-400" />
                          <span className="text-[13px] text-gray-700">{formatPhone(selectedLead.phone1)}</span>
                        </div>
                        {leadDetails.persons[0]?.email && (
                          <div className="flex items-center gap-2.5">
                            <Mail className="w-4 h-4 text-gray-400" />
                            <span className="text-[13px] text-gray-700">{leadDetails.persons[0].email}</span>
                          </div>
                        )}
                        {leadDetails.persons[0]?.job_title && (
                          <div className="flex items-center gap-2.5">
                            <Briefcase className="w-4 h-4 text-gray-400" />
                            <span className="text-[13px] text-gray-700">{leadDetails.persons[0].job_title}</span>
                          </div>
                        )}
                        {(leadDetails.lead.city || leadDetails.lead.state) && (
                          <div className="flex items-center gap-2.5">
                            <MapPin className="w-4 h-4 text-gray-400" />
                            <span className="text-[13px] text-gray-700">{[leadDetails.lead.city, leadDetails.lead.state].filter(Boolean).join(', ')}</span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Info do Lead */}
                    <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
                      <h3 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-3">Informações</h3>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <p className="text-[11px] text-gray-400 mb-0.5">Fonte</p>
                          <p className="text-[13px] font-medium text-gray-700">{selectedLead.source || '-'}</p>
                        </div>
                        <div>
                          <p className="text-[11px] text-gray-400 mb-0.5">Curso</p>
                          <p className="text-[13px] font-medium text-gray-700">{selectedLead.sub_source || '-'}</p>
                        </div>
                        <div>
                          <p className="text-[11px] text-gray-400 mb-0.5">SDR</p>
                          <p className="text-[13px] font-medium text-gray-700">{selectedLead.sdr_name || '-'}</p>
                        </div>
                        <div>
                          <p className="text-[11px] text-gray-400 mb-0.5">Cadastro</p>
                          <p className="text-[13px] font-medium text-gray-700 tabular-nums">{formatDate(selectedLead.register_date)}</p>
                        </div>
                      </div>
                      {leadDetails.lead.description && (
                        <div className="mt-3 pt-3 border-t border-gray-200">
                          <p className="text-[11px] text-gray-400 mb-1">Descrição</p>
                          <p className="text-[13px] text-gray-700 leading-relaxed">{leadDetails.lead.description}</p>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Coluna direita - Histórico */}
                  <div>
                    <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
                      <h3 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-3">Histórico de Qualificação</h3>
                      {leadDetails.qualifications.length > 0 ? (
                        <div className="space-y-3">
                          {leadDetails.qualifications.map((q, i) => (
                            <div key={i} className="relative pl-6 pb-3 border-l-2 border-gray-200 last:border-l-0 last:pb-0">
                              <div className="absolute left-[-5px] top-1.5 w-2 h-2 rounded-full bg-[#2A658F]" />
                              <div className="bg-white rounded-xl p-3 border border-gray-100">
                                <div className="flex items-center gap-2 mb-1">
                                  <span className="text-[12px] font-medium text-gray-800">
                                    {q.origin_stage || '?'} → {q.stage || '?'}
                                  </span>
                                </div>
                                <div className="flex items-center gap-1.5 text-[11px] text-gray-400">
                                  <Clock className="w-3 h-3" />
                                  <span className="tabular-nums">{formatQualDate(q.qualification_date)}</span>
                                </div>
                                {q.user_action && (
                                  <p className="text-[12px] text-gray-500 mt-1.5">{q.user_action}</p>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-[13px] text-gray-400 text-center py-6">Sem histórico de qualificação</p>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-center text-gray-400 py-8">Erro ao carregar detalhes</p>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-gray-100 flex-shrink-0">
              <button
                onClick={() => { closeLeadPopup(); window.location.href = '/conversations'; }}
                className="w-full flex items-center justify-center gap-2 py-3 bg-[#2A658F] text-white font-medium rounded-xl hover:bg-[#1f5375] hover:shadow-lg hover:shadow-[#2A658F]/20 active:scale-[0.98] transition-all"
              >
                <MessageCircle className="w-4 h-4" />
                Iniciar conversa WhatsApp
              </button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  );
}