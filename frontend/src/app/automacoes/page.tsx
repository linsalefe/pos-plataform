'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Zap, Search, Send, Loader2, CheckCircle, XCircle, AlertTriangle, Filter } from 'lucide-react';
import AppLayout from '@/components/AppLayout';
import { useAuth } from '@/contexts/auth-context';
import api from '@/lib/api';

interface ExactLead {
  id: number;
  exact_id: number;
  name: string;
  phone1: string | null;
  sub_source: string | null;
  stage: string | null;
  sdr_name: string | null;
  register_date: string | null;
}

interface Stats {
  total: number;
  by_stage: Record<string, number>;
  by_sub_source: Record<string, number>;
}

interface SendResult {
  sent: number;
  failed: number;
  errors: { name: string; error: string }[];
}

const stageColors: Record<string, string> = {
  'Entrada': 'bg-blue-50 text-blue-700',
  'Pré Qualificado': 'bg-purple-50 text-purple-700',
  'Follow 2': 'bg-amber-50 text-amber-700',
  'Follow 3': 'bg-amber-50 text-amber-700',
  'Follow 4': 'bg-amber-50 text-amber-700',
  'Follows 5': 'bg-orange-50 text-orange-700',
  'Follows 6': 'bg-orange-50 text-orange-700',
  'Agendados': 'bg-cyan-50 text-cyan-700',
  'Reagendamento': 'bg-cyan-50 text-cyan-700',
  'Em Negociação': 'bg-indigo-50 text-indigo-700',
  'Contratos Gerados': 'bg-emerald-50 text-emerald-700',
  'Vendidos': 'bg-green-50 text-green-700',
  'Descartado': 'bg-red-50 text-red-700',
  'Sem contato': 'bg-gray-100 text-gray-600',
  'SEM CONTATO': 'bg-gray-100 text-gray-600',
};

export default function AutomacoesPage() {
  const [leads, setLeads] = useState<ExactLead[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [stageFilter, setStageFilter] = useState('');
  const [subSourceFilter, setSubSourceFilter] = useState('');
  const [sdrFilter, setSdrFilter] = useState('');
  const [search, setSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectAll, setSelectAll] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Template
  const [templates, setTemplates] = useState<any[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<any>(null);
  const [templateParams, setTemplateParams] = useState<string[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [channels, setChannels] = useState<any[]>([]);
  const [activeChannelId, setActiveChannelId] = useState<number>(1);

  // Envio
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<SendResult | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  const { user, loading: authLoading } = useAuth();
  const router = useRouter();

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    if (!authLoading && !user) router.push('/login');
  }, [user, authLoading, router]);

  useEffect(() => {
    if (user) {
      loadData();
      loadChannels();
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
      console.error('Erro:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadChannels = async () => {
    try {
      const res = await api.get('/channels');
      setChannels(res.data);
      if (res.data.length > 0) setActiveChannelId(res.data[0].id);
    } catch (err) {
      console.error('Erro:', err);
    }
  };

  const loadTemplates = async () => {
    setLoadingTemplates(true);
    try {
      const res = await api.get(`/channels/${activeChannelId}/templates`);
      setTemplates(res.data);
    } catch (err) {
      console.error('Erro:', err);
    } finally {
      setLoadingTemplates(false);
    }
  };

  const selectTemplate = (t: any) => {
    setSelectedTemplate(t);
    setTemplateParams(new Array(t.parameters.length).fill(''));
  };

  const updateParam = (index: number, value: string) => {
    const p = [...templateParams];
    p[index] = value;
    setTemplateParams(p);
  };

  const getPreview = () => {
    if (!selectedTemplate) return '';
    let text = selectedTemplate.body;
    templateParams.forEach((p, i) => {
      text = text.replace(`{{${i + 1}}}`, p || `[Variável ${i + 1}]`);
    });
    return text;
  };

  const sdrs = [...new Set(leads.map(l => l.sdr_name).filter(Boolean))].sort() as string[];
  const stages = stats ? Object.keys(stats.by_stage).sort() : [];
  const subSources = stats ? Object.keys(stats.by_sub_source).sort() : [];

  const filteredLeads = leads.filter((lead) => {
    const matchSearch = !search || lead.name.toLowerCase().includes(search.toLowerCase()) || (lead.phone1 && lead.phone1.includes(search));
    const matchStage = !stageFilter || lead.stage === stageFilter;
    const matchSubSource = !subSourceFilter || lead.sub_source === subSourceFilter;
    const matchSdr = !sdrFilter || lead.sdr_name === sdrFilter;
    return matchSearch && matchStage && matchSubSource && matchSdr;
  });

  const toggleSelect = (id: number) => {
    const newSet = new Set(selectedIds);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedIds(newSet);
    setSelectAll(false);
  };

  const toggleSelectAll = () => {
    if (selectAll) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredLeads.map(l => l.id)));
    }
    setSelectAll(!selectAll);
  };

  const handleBulkSend = async () => {
    if (!selectedTemplate || selectedIds.size === 0) return;
    setSending(true);
    setSendResult(null);
    setShowConfirm(false);
    try {
      const res = await api.post('/exact-leads/bulk-send-template', {
        template_name: selectedTemplate.name,
        language: selectedTemplate.language,
        channel_id: activeChannelId,
        parameters: templateParams.length > 0 ? templateParams : [],
        lead_ids: Array.from(selectedIds),
      });
      setSendResult(res.data);
    } catch (err) {
      console.error('Erro:', err);
    } finally {
      setSending(false);
    }
  };

  const handleSingleSend = async (lead: ExactLead) => {
    if (!selectedTemplate || !lead.phone1) return;
    setSending(true);
    setSendResult(null);
    try {
      const res = await api.post('/exact-leads/bulk-send-template', {
        template_name: selectedTemplate.name,
        language: selectedTemplate.language,
        channel_id: activeChannelId,
        parameters: templateParams.length > 0 ? templateParams : [],
        lead_ids: [lead.id],
      });
      setSendResult(res.data);
    } catch (err) {
      console.error('Erro:', err);
    } finally {
      setSending(false);
    }
  };

  const formatPhone = (phone: string | null) => {
    if (!phone) return '-';
    return phone.replace(/^55/, '').replace(/(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
  };

  const hasActiveFilters = search || stageFilter || subSourceFilter || sdrFilter;

  if (authLoading) return <div className="min-h-screen flex items-center justify-center bg-[#f8f9fb]"><Loader2 className="w-8 h-8 text-[#2A658F] animate-spin" /></div>;
  if (!user) return null;

  if (loading) {
    return (
      <AppLayout>
        <div className="animate-pulse space-y-6 max-w-7xl mx-auto">
          <div className="space-y-2">
            <div className="h-4 bg-gray-200 rounded w-32" />
            <div className="h-7 bg-gray-200 rounded w-48" />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="h-80 bg-gray-200 rounded-2xl" />
            <div className="lg:col-span-2 h-96 bg-gray-200 rounded-2xl" />
          </div>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="space-y-6 max-w-7xl mx-auto overflow-y-auto h-full pb-6">

        {/* Header */}
        <div className={`transition-all duration-700 ease-out ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'}`}>
          <p className="text-sm text-gray-400 mb-0.5">Envio em massa</p>
          <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight">Automações</h1>
        </div>

        <div className={`grid grid-cols-1 lg:grid-cols-3 gap-6 transition-all duration-700 ease-out delay-100 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>

          {/* ══════════════════════════════════════ */}
          {/* COLUNA ESQUERDA — CONFIG               */}
          {/* ══════════════════════════════════════ */}
          <div className="space-y-4">

            {/* Canal */}
            <div className="bg-white rounded-2xl p-4 border border-gray-100">
              <h3 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2.5">Canal</h3>
              <select
                value={activeChannelId}
                onChange={(e) => { setActiveChannelId(Number(e.target.value)); setTemplates([]); setSelectedTemplate(null); }}
                className="w-full px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] focus:bg-white transition-all cursor-pointer"
              >
                {channels.map(ch => (
                  <option key={ch.id} value={ch.id}>{ch.name}</option>
                ))}
              </select>
            </div>

            {/* Template */}
            <div className="bg-white rounded-2xl p-4 border border-gray-100">
              <h3 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2.5">Template</h3>
              {loadingTemplates ? (
                <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 text-[#2A658F] animate-spin" /></div>
              ) : templates.length === 0 ? (
                <button onClick={loadTemplates} className="w-full py-3 border border-dashed border-gray-200 rounded-xl text-[13px] text-gray-400 hover:border-[#2A658F] hover:text-[#2A658F] hover:bg-[#2A658F]/5 transition-all">
                  Carregar templates
                </button>
              ) : (
                <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
                  {templates.map((t: any) => (
                    <button
                      key={t.name}
                      onClick={() => selectTemplate(t)}
                      className={`w-full text-left px-3 py-2.5 rounded-xl border text-sm transition-all ${
                        selectedTemplate?.name === t.name
                          ? 'border-[#2A658F] bg-[#2A658F]/5 text-[#2A658F]'
                          : 'border-gray-50 text-gray-700 hover:bg-gray-50 hover:border-gray-100'
                      }`}
                    >
                      <p className="font-medium text-[12px]">{t.name.replace(/_/g, ' ')}</p>
                      <p className="text-[10px] text-gray-400 mt-0.5">{t.parameters.length} variáveis</p>
                    </button>
                  ))}
                </div>
              )}

              {selectedTemplate && selectedTemplate.parameters.length > 0 && (
                <div className="mt-4 pt-4 border-t border-gray-100 space-y-3">
                  <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Variáveis</p>
                  {selectedTemplate.parameters.map((p: string, i: number) => (
                    <div key={i}>
                      <label className="text-[11px] text-gray-400 mb-1 block">{p} ({'{{'}{i+1}{'}}'})</label>
                      <input
                        type="text"
                        value={templateParams[i] || ''}
                        onChange={e => updateParam(i, e.target.value)}
                        placeholder={`Valor para ${p}`}
                        className="w-full px-3 py-2 bg-gray-50 border border-gray-100 rounded-lg text-[13px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-[#2A658F] focus:bg-white transition-all"
                      />
                    </div>
                  ))}
                </div>
              )}

              {selectedTemplate && (
                <div className="mt-4 bg-[#eef0f3] rounded-xl p-3 border border-gray-100">
                  <p className="text-[10px] font-semibold text-gray-400 uppercase mb-1.5 tracking-wider">Prévia</p>
                  <p className="text-[12px] text-gray-700 whitespace-pre-wrap leading-relaxed">{getPreview()}</p>
                </div>
              )}
            </div>

            {/* Botão Enviar em massa */}
            {selectedIds.size > 0 && selectedTemplate && (
              <button
                onClick={() => setShowConfirm(true)}
                disabled={sending}
                className="w-full flex items-center justify-center gap-2 py-3 bg-[#2A658F] text-white font-medium rounded-xl hover:bg-[#1f5375] hover:shadow-lg hover:shadow-[#2A658F]/20 active:scale-[0.98] transition-all disabled:opacity-40 disabled:active:scale-100"
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                {sending ? 'Enviando...' : `Enviar para ${selectedIds.size} leads`}
              </button>
            )}

            {/* Resultado */}
            {sendResult && (
              <div className="bg-white rounded-2xl p-4 border border-gray-100 space-y-3">
                <h3 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Resultado</h3>
                <div className="flex gap-4">
                  <div className="flex items-center gap-1.5">
                    <CheckCircle className="w-4 h-4 text-emerald-500" />
                    <span className="text-[13px] font-medium text-emerald-700">{sendResult.sent} enviados</span>
                  </div>
                  {sendResult.failed > 0 && (
                    <div className="flex items-center gap-1.5">
                      <XCircle className="w-4 h-4 text-red-500" />
                      <span className="text-[13px] font-medium text-red-700">{sendResult.failed} falharam</span>
                    </div>
                  )}
                </div>
                {sendResult.errors.length > 0 && (
                  <div className="mt-2 space-y-1 pt-2 border-t border-gray-100">
                    {sendResult.errors.map((e, i) => (
                      <p key={i} className="text-[11px] text-red-500">{e.name}: {e.error}</p>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ══════════════════════════════════════ */}
          {/* COLUNA DIREITA — LISTA DE LEADS        */}
          {/* ══════════════════════════════════════ */}
          <div className="lg:col-span-2 space-y-4">

            {/* Filtros */}
            <div className="bg-white rounded-2xl p-4 border border-gray-100">
              <div className="flex flex-wrap items-center gap-3">
                <div className="relative flex-1 min-w-[180px]">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Buscar lead..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="w-full pl-9 pr-4 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] focus:bg-white transition-all"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Filter className="w-4 h-4 text-gray-400" />
                  <select value={stageFilter} onChange={(e) => setStageFilter(e.target.value)} className="px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] transition-all cursor-pointer">
                    <option value="">Todos estágios</option>
                    {stages.map(s => <option key={s} value={s}>{s} ({stats?.by_stage[s]})</option>)}
                  </select>
                  <select value={subSourceFilter} onChange={(e) => setSubSourceFilter(e.target.value)} className="px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] transition-all cursor-pointer">
                    <option value="">Todos cursos</option>
                    {subSources.map(s => <option key={s} value={s}>{s} ({stats?.by_sub_source[s]})</option>)}
                  </select>
                  <select value={sdrFilter} onChange={(e) => setSdrFilter(e.target.value)} className="px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] transition-all cursor-pointer">
                    <option value="">Todos SDRs</option>
                    {sdrs.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                {hasActiveFilters && (
                  <button
                    onClick={() => { setSearch(''); setStageFilter(''); setSubSourceFilter(''); setSdrFilter(''); }}
                    className="px-3 py-2.5 text-[12px] font-medium text-gray-500 hover:text-red-500 hover:bg-red-50 rounded-xl transition-colors"
                  >
                    Limpar
                  </button>
                )}
              </div>
            </div>

            {/* Tabela */}
            <div className="bg-white rounded-2xl border border-gray-100 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50/50">
                      <th className="px-4 py-3 w-10">
                        <input type="checkbox" checked={selectAll} onChange={toggleSelectAll} className="w-4 h-4 rounded border-gray-300 text-[#2A658F] focus:ring-[#2A658F]" />
                      </th>
                      <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">Nome</th>
                      <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">Telefone</th>
                      <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">Curso</th>
                      <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">Estágio</th>
                      <th className="text-left text-[11px] font-semibold text-gray-400 uppercase tracking-wider px-4 py-3">SDR</th>
                      {selectedTemplate && <th className="px-4 py-3 w-20"></th>}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredLeads.map((lead) => (
                      <tr key={lead.id} className={`border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors ${selectedIds.has(lead.id) ? 'bg-[#2A658F]/[0.03]' : ''}`}>
                        <td className="px-4 py-3">
                          <input
                            type="checkbox"
                            checked={selectedIds.has(lead.id)}
                            onChange={() => toggleSelect(lead.id)}
                            className="w-4 h-4 rounded border-gray-300 text-[#2A658F] focus:ring-[#2A658F]"
                          />
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-[13px] font-medium text-[#27273D]">{lead.name}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-[13px] text-gray-500 tabular-nums">{formatPhone(lead.phone1)}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-[13px] text-gray-500">{lead.sub_source || '-'}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex px-2 py-0.5 rounded-md text-[11px] font-medium ${stageColors[lead.stage || ''] || 'bg-gray-100 text-gray-600'}`}>
                            {lead.stage || '-'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-[13px] text-gray-500">{lead.sdr_name || '-'}</span>
                        </td>
                        {selectedTemplate && (
                          <td className="px-4 py-3">
                            <button
                              onClick={() => handleSingleSend(lead)}
                              disabled={sending || !lead.phone1}
                              className="text-[11px] px-3 py-1.5 bg-[#2A658F] text-white rounded-lg hover:bg-[#1f5375] disabled:opacity-30 transition-all active:scale-95"
                            >
                              Enviar
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {filteredLeads.length === 0 && (
                <div className="text-center py-16 text-gray-400">
                  <Zap className="w-8 h-8 mx-auto mb-2 text-gray-300" />
                  <p className="text-sm">Nenhum lead encontrado</p>
                </div>
              )}
              <div className="px-4 py-3 border-t border-gray-100 flex items-center justify-between">
                <span className="text-[12px] text-gray-400">
                  {filteredLeads.length} leads • {selectedIds.size} selecionados
                </span>
                {hasActiveFilters && (
                  <span className="text-[12px] text-[#2A658F] font-medium">Filtros ativos</span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════ */}
      {/* MODAL CONFIRMAÇÃO                      */}
      {/* ══════════════════════════════════════ */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={() => setShowConfirm(false)}>
          <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-2xl mx-4 border border-gray-100" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-5">
              <div className="w-11 h-11 bg-amber-50 rounded-xl flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-amber-600" />
              </div>
              <div>
                <h2 className="text-[15px] font-semibold text-[#27273D]">Confirmar envio</h2>
                <p className="text-[13px] text-gray-400">Esta ação não pode ser desfeita</p>
              </div>
            </div>
            <div className="bg-gray-50 rounded-xl p-4 mb-5 space-y-2 border border-gray-100">
              <div className="flex justify-between">
                <span className="text-[12px] text-gray-400">Template</span>
                <span className="text-[13px] font-medium text-gray-700">{selectedTemplate?.name.replace(/_/g, ' ')}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[12px] text-gray-400">Leads</span>
                <span className="text-[13px] font-medium text-gray-700">{selectedIds.size}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[12px] text-gray-400">Canal</span>
                <span className="text-[13px] font-medium text-gray-700">{channels.find(c => c.id === activeChannelId)?.name}</span>
              </div>
            </div>
            <div className="flex gap-3">
              <button onClick={() => setShowConfirm(false)} className="flex-1 py-2.5 border border-gray-200 rounded-xl text-[13px] font-medium text-gray-500 hover:bg-gray-50 transition-colors">
                Cancelar
              </button>
              <button onClick={handleBulkSend} className="flex-1 py-2.5 bg-[#2A658F] text-white rounded-xl text-[13px] font-medium hover:bg-[#1f5375] active:scale-[0.98] transition-all">
                Confirmar envio
              </button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  );
}