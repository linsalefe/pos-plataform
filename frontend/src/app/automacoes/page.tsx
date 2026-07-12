'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Zap, Search, Send, Loader2, CheckCircle, XCircle, AlertTriangle, Filter, Calendar, Clock, X, Trash2, Power, Lock, MessageSquare } from 'lucide-react';
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
  funnel_id: number | null;
  register_date: string | null;
}

interface Stats {
  total: number;
  by_stage: Record<string, number>;
  by_sub_source: Record<string, number>;
  by_funnel?: Record<string, number>;
}

interface SendResult {
  sent: number;
  failed: number;
  errors: { name: string; error: string }[];
}

interface CourseAlias {
  id: number;
  alias: string;
  full_name: string;
  short_name: string;
}

interface ParamMapping {
  type: string;
  value: string;
}

interface AutoWelcomeConfig {
  enabled: boolean;
  channel_id: number | null;
  template_name: string | null;
  template_language: string | null;
  funnel_ids: number[];
  updated_by_name: string | null;
  updated_at: string | null;
}

interface AutoWelcomePreview {
  target_funnels: number[];
  pending_count: number;
  sample: { exact_id: number; name: string; funnel_id: number }[];
}

// Template da boas-vindas automática: o backend BLOQUEIA o envio em massa/agendamento dele
// (HTTP 400). Ele só sai pelo fluxo automático ou pelo reenvio individual do lead.
const WELCOME_TEMPLATE = 'nat_boasvindas';

const MAPPING_OPTIONS = [
  { value: 'lead_name', label: 'Nome do Lead (1º nome)' },
  { value: 'lead_full_name', label: 'Nome completo do Lead' },
  { value: 'lead_course', label: 'Curso (automático)' },
  { value: 'sdr_name', label: 'Nome do SDR' },
  { value: 'fixed_text', label: 'Texto fixo' },
];

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
  const [funnelFilter, setFunnelFilter] = useState('');           // '' = todos
  const [funnels, setFunnels] = useState<{ id: number; name: string }[]>([]);
  const [search, setSearch] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectAll, setSelectAll] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [courseAliases, setCourseAliases] = useState<CourseAlias[]>([]);

  // Template
  const [templates, setTemplates] = useState<any[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<any>(null);
  const [paramMappings, setParamMappings] = useState<ParamMapping[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [channels, setChannels] = useState<any[]>([]);
  const [activeChannelId, setActiveChannelId] = useState<number>(1);

  // Envio
  const [sending, setSending] = useState(false);
  const [sendResult, setSendResult] = useState<SendResult | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [scheduleAt, setScheduleAt] = useState('');
  const [scheduling, setScheduling] = useState(false);
  const [showSchedules, setShowSchedules] = useState(false);
  const [schedules, setSchedules] = useState<any[]>([]);

  // Boas-vindas automática
  const [awCfg, setAwCfg] = useState<AutoWelcomeConfig | null>(null);
  const [awChannelId, setAwChannelId] = useState<number | ''>('');
  const [awTemplateName, setAwTemplateName] = useState('');
  const [awLang, setAwLang] = useState('pt_BR');
  const [awFunnels, setAwFunnels] = useState('');
  const [awTemplates, setAwTemplates] = useState<any[]>([]);
  const [awSaving, setAwSaving] = useState(false);
  const [awPreview, setAwPreview] = useState<AutoWelcomePreview | null>(null);
  const [awConfirm, setAwConfirm] = useState(false);
  const [awMsg, setAwMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

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
      loadCourseAliases();
      loadFunnels();
      loadAwConfig();
    }
  }, [user]);

  // ─── Boas-vindas automática ───────────────────────────────────────────────
  const loadAwConfig = async () => {
    try {
      const res = await api.get('/auto-welcome/config');
      const cfg: AutoWelcomeConfig = res.data;
      setAwCfg(cfg);
      setAwChannelId(cfg.channel_id ?? '');
      setAwTemplateName(cfg.template_name || WELCOME_TEMPLATE);
      setAwLang(cfg.template_language || 'pt_BR');
      setAwFunnels((cfg.funnel_ids || []).join(','));
      if (cfg.channel_id) loadAwTemplates(cfg.channel_id);
    } catch (err) {
      console.error('Erro ao carregar config de boas-vindas:', err);
    }
  };

  const loadAwTemplates = async (channelId: number) => {
    try {
      const res = await api.get(`/channels/${channelId}/templates?status=APPROVED`);
      setAwTemplates(res.data);
    } catch (err) {
      console.error('Erro ao carregar templates do canal:', err);
    }
  };

  const awFunnelIds = (): number[] =>
    awFunnels.split(',').map(s => parseInt(s.trim(), 10)).filter(n => !isNaN(n));

  const awPayload = (enabled: boolean) => ({
    enabled,
    channel_id: awChannelId === '' ? null : Number(awChannelId),
    template_name: awTemplateName || null,
    template_language: awLang || 'pt_BR',
    funnel_ids: awFunnelIds(),
    updated_by_name: user?.name,
  });

  const awApplyResponse = (data: any) => {
    setAwCfg(data);
    setAwChannelId(data.channel_id ?? '');
    setAwTemplateName(data.template_name || '');
    setAwLang(data.template_language || 'pt_BR');
    setAwFunnels((data.funnel_ids || []).join(','));
  };

  /** Salva canal/template/funis SEM mexer no liga-desliga. */
  const awSave = async () => {
    if (!awCfg) return;
    setAwSaving(true);
    setAwMsg(null);
    try {
      const res = await api.put('/auto-welcome/config', awPayload(awCfg.enabled));
      awApplyResponse(res.data);
      setAwMsg({ type: 'ok', text: 'Configuração salva.' });
    } catch (err: any) {
      setAwMsg({ type: 'err', text: err?.response?.data?.detail || 'Erro ao salvar configuração.' });
    } finally {
      setAwSaving(false);
    }
  };

  /** Clique no switch. Ligar exige confirmação; desligar é imediato (botão de pânico). */
  const awToggle = async () => {
    if (!awCfg) return;
    setAwMsg(null);
    if (awCfg.enabled) {
      setAwSaving(true);
      try {
        const res = await api.put('/auto-welcome/config', awPayload(false));
        awApplyResponse(res.data);
        setAwMsg({ type: 'ok', text: 'Automação desligada. Nenhum lead recebe boas-vindas.' });
      } catch (err: any) {
        setAwMsg({ type: 'err', text: err?.response?.data?.detail || 'Erro ao desligar.' });
      } finally {
        setAwSaving(false);
      }
      return;
    }
    // Vai LIGAR: buscar o preview e confirmar antes.
    try {
      const res = await api.get('/auto-welcome/preview');
      setAwPreview(res.data);
      setAwConfirm(true);
    } catch (err: any) {
      setAwMsg({ type: 'err', text: err?.response?.data?.detail || 'Erro ao carregar prévia.' });
    }
  };

  const awEnable = async () => {
    setAwSaving(true);
    setAwMsg(null);
    try {
      const res = await api.put('/auto-welcome/config', awPayload(true));
      awApplyResponse(res.data);
      setAwConfirm(false);
      const cortados = res.data.leads_cortados_na_ativacao ?? 0;
      setAwMsg({
        type: 'ok',
        text: `Automação ligada. ${cortados} leads antigos foram marcados como "não recebem".`,
      });
    } catch (err: any) {
      setAwConfirm(false);
      setAwMsg({ type: 'err', text: err?.response?.data?.detail || 'Erro ao ligar a automação.' });
    } finally {
      setAwSaving(false);
    }
  };

  /** Templates que o backend recusa no envio em massa/agendamento. */
  const isBlockedTemplate = (name: string) => {
    const n = (name || '').trim().toLowerCase();
    return n === WELCOME_TEMPLATE || n === (awCfg?.template_name || '').trim().toLowerCase();
  };

  const loadFunnels = async () => {
    try {
      const res = await api.get('/exact-leads/funnels');
      setFunnels(res.data);
    } catch (err) {
      console.error('Erro ao carregar funis:', err);
    }
  };

  const funnelName = (id: number | null) =>
    funnels.find(f => f.id === id)?.name || (id != null ? `Funil ${id}` : '-');

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

  const loadCourseAliases = async () => {
    try {
      const res = await api.get('/course-aliases');
      setCourseAliases(res.data);
    } catch (err) {
      console.error('Erro ao carregar aliases:', err);
    }
  };

  const resolveCourse = (alias: string | null): string => {
    if (!alias) return '-';
    const found = courseAliases.find(c => c.alias.toLowerCase() === alias.toLowerCase());
    return found ? found.short_name : alias;
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
    // Inicializar mapeamentos com valores padrão inteligentes
    const mappings: ParamMapping[] = t.parameters.map((_: string, i: number) => {
      if (i === 0) return { type: 'lead_name', value: '' };
      if (i === 1) return { type: 'lead_course', value: '' };
      if (i === 2) return { type: 'lead_course', value: '' };
      return { type: 'fixed_text', value: '' };
    });
    setParamMappings(mappings);
  };

  const updateMapping = (index: number, type: string) => {
    const newMappings = [...paramMappings];
    newMappings[index] = { type, value: newMappings[index]?.value || '' };
    setParamMappings(newMappings);
  };

  const updateMappingValue = (index: number, value: string) => {
    const newMappings = [...paramMappings];
    newMappings[index] = { ...newMappings[index], value };
    setParamMappings(newMappings);
  };

  const getMappingLabel = (mapping: ParamMapping): string => {
    const opt = MAPPING_OPTIONS.find(o => o.value === mapping.type);
    if (mapping.type === 'fixed_text') return mapping.value || '[Texto fixo]';
    return opt?.label || mapping.type;
  };

  const getPreview = () => {
    if (!selectedTemplate) return '';
    let text = selectedTemplate.body;
    paramMappings.forEach((mapping, i) => {
      const label = getMappingLabel(mapping);
      text = text.replace(`{{${i + 1}}}`, label);
    });
    return text;
  };

  const sdrs = [...new Set(leads.map(l => l.sdr_name).filter(Boolean))].sort() as string[];
  const stages = stats ? Object.keys(stats.by_stage).sort() : [];
  const subSources = stats ? Object.keys(stats.by_sub_source).sort() : [];
  const funnelIds = stats?.by_funnel ? Object.keys(stats.by_funnel) : [];

  const filteredLeads = leads.filter((lead) => {
    const matchSearch = !search || lead.name.toLowerCase().includes(search.toLowerCase()) || (lead.phone1 && lead.phone1.includes(search));
    const matchStage = !stageFilter || lead.stage === stageFilter;
    const matchSubSource = !subSourceFilter || lead.sub_source === subSourceFilter;
    const matchSdr = !sdrFilter || lead.sdr_name === sdrFilter;
    const matchFunnel = !funnelFilter || String(lead.funnel_id) === funnelFilter;
    return matchSearch && matchStage && matchSubSource && matchSdr && matchFunnel;
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

  const selectedFunnelCount = () =>
    new Set(leads.filter(l => selectedIds.has(l.id)).map(l => l.funnel_id)).size;

  const handleBulkSend = async () => {
    if (!selectedTemplate || selectedIds.size === 0) return;
    if (selectedFunnelCount() > 1) {
      alert('O envio em massa não cruza funis. Filtre por um único funil (ou selecione leads do mesmo funil) antes de enviar.');
      return;
    }
    setSending(true);
    setSendResult(null);
    setSendError(null);
    setShowConfirm(false);
    try {
      const res = await api.post('/exact-leads/bulk-send-template', {
        template_name: selectedTemplate.name,
        language: selectedTemplate.language,
        channel_id: activeChannelId,
        param_mappings: paramMappings.length > 0 ? paramMappings : undefined,
        lead_ids: Array.from(selectedIds),
      });
      setSendResult(res.data);
    } catch (err: any) {
      // Não engolir o erro: o backend recusa o template de boas-vindas com 400 e uma
      // mensagem legível. O usuário precisa vê-la.
      setSendError(err?.response?.data?.detail || 'Erro ao enviar.');
    } finally {
      setSending(false);
    }
  };

  const handleSchedule = async () => {
    if (!selectedTemplate || selectedIds.size === 0 || !scheduleAt) return;
    if (selectedFunnelCount() > 1) {
      alert('O agendamento em massa não cruza funis. Filtre por um único funil (ou selecione leads do mesmo funil) antes de agendar.');
      return;
    }
    setScheduling(true);
    try {
      await api.post('/scheduled-messages', {
        template_name: selectedTemplate.name,
        language: selectedTemplate.language,
        channel_id: activeChannelId,
        param_mappings: paramMappings.length > 0 ? paramMappings : undefined,
        lead_ids: Array.from(selectedIds),
        scheduled_at: scheduleAt,
      });
      setShowConfirm(false);
      setScheduleAt('');
      setSelectedIds(new Set());
      setSelectAll(false);
      await loadSchedules();
      setShowSchedules(true);
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Erro ao agendar');
    } finally {
      setScheduling(false);
    }
  };

  const loadSchedules = async () => {
    try {
      const res = await api.get('/scheduled-messages');
      setSchedules(res.data);
    } catch (err) { console.error('Erro:', err); }
  };

  const cancelSchedule = async (id: number) => {
    try {
      await api.post(`/scheduled-messages/${id}/cancel`);
      await loadSchedules();
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Erro ao cancelar');
    }
  };

  const handleSingleSend = async (lead: ExactLead) => {
    if (!selectedTemplate || !lead.phone1) return;
    setSending(true);
    setSendResult(null);
    setSendError(null);
    try {
      const res = await api.post('/exact-leads/bulk-send-template', {
        template_name: selectedTemplate.name,
        language: selectedTemplate.language,
        channel_id: activeChannelId,
        param_mappings: paramMappings.length > 0 ? paramMappings : undefined,
        lead_ids: [lead.id],
      });
      setSendResult(res.data);
    } catch (err: any) {
      setSendError(err?.response?.data?.detail || 'Erro ao enviar.');
    } finally {
      setSending(false);
    }
  };

  const formatPhone = (phone: string | null) => {
    if (!phone) return '-';
    return phone.replace(/^55/, '').replace(/(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
  };

  const hasActiveFilters = search || stageFilter || subSourceFilter || sdrFilter || funnelFilter;

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
        <div className={`flex items-start justify-between gap-4 transition-all duration-700 ease-out ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'}`}>
          <div>
            <p className="text-sm text-gray-400 mb-0.5">Envio em massa</p>
            <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight">Automações</h1>
          </div>
          <button
            onClick={() => { loadSchedules(); setShowSchedules(true); }}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-gray-200 bg-white text-[13px] font-medium text-gray-600 hover:bg-gray-50 transition-colors flex-shrink-0"
          >
            <Calendar className="w-4 h-4 text-[#2A658F]" />
            Agendamentos
          </button>
        </div>

        {/* ══════════════════════════════════════ */}
        {/* MENSAGEM AUTOMÁTICA DE BOAS-VINDAS     */}
        {/* ══════════════════════════════════════ */}
        {awCfg && (
          <div className={`bg-white rounded-2xl border border-gray-100 overflow-hidden transition-all duration-700 ease-out delay-75 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
            <div className="flex items-center justify-between gap-4 p-5">
              <div className="flex items-center gap-3 min-w-0">
                <div className={`w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0 ${awCfg.enabled ? 'bg-emerald-50' : 'bg-gray-100'}`}>
                  <MessageSquare className={`w-5 h-5 ${awCfg.enabled ? 'text-emerald-600' : 'text-gray-400'}`} />
                </div>
                <div className="min-w-0">
                  <h2 className="text-[15px] font-semibold text-[#27273D]">Mensagem automática de boas-vindas</h2>
                  <p className="text-[12.5px] text-gray-400">
                    Enviada para cada lead novo que entrar nos funis selecionados.
                    {awCfg.updated_by_name && ` • Alterada por ${awCfg.updated_by_name}`}
                  </p>
                </div>
              </div>

              {/* Switch */}
              <button
                onClick={awToggle}
                disabled={awSaving}
                aria-pressed={awCfg.enabled}
                aria-label={awCfg.enabled ? 'Desligar automação' : 'Ligar automação'}
                className={`relative flex items-center gap-2.5 px-4 py-2.5 rounded-xl font-medium text-[13px] flex-shrink-0 transition-all active:scale-[0.98] disabled:opacity-50 ${
                  awCfg.enabled
                    ? 'bg-emerald-500 text-white hover:bg-emerald-600'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                {awSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Power className="w-4 h-4" />}
                {awCfg.enabled ? 'Ligada' : 'Desligada'}
                <span className={`w-9 h-5 rounded-full flex items-center px-0.5 transition-colors ${awCfg.enabled ? 'bg-white/30 justify-end' : 'bg-white justify-start'}`}>
                  <span className={`w-4 h-4 rounded-full ${awCfg.enabled ? 'bg-white' : 'bg-gray-400'}`} />
                </span>
              </button>
            </div>

            {/* Aviso de estado */}
            <div className={`px-5 py-3 flex items-start gap-2.5 border-t ${awCfg.enabled ? 'bg-amber-50 border-amber-100' : 'bg-gray-50 border-gray-100'}`}>
              <AlertTriangle className={`w-4 h-4 flex-shrink-0 mt-0.5 ${awCfg.enabled ? 'text-amber-600' : 'text-gray-400'}`} />
              <p className={`text-[12.5px] leading-relaxed ${awCfg.enabled ? 'text-amber-800' : 'text-gray-500'}`}>
                {awCfg.enabled
                  ? 'Ligada. Leads novos dos funis selecionados recebem a mensagem automaticamente. A mensagem promete um consultor ligando em minutos — confirme que há SDR disponível.'
                  : 'Desligada. Nenhum lead recebe boas-vindas — nem os que entrarem enquanto estiver desligada. Ao ligar, apenas leads cadastrados a partir daquele momento receberão.'}
              </p>
            </div>

            {/* Configuração */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 p-5 border-t border-gray-100">
              <div className="space-y-1.5">
                <label className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider block">Canal</label>
                <select
                  value={awChannelId}
                  onChange={(e) => {
                    const v = e.target.value === '' ? '' : Number(e.target.value);
                    setAwChannelId(v);
                    if (v !== '') loadAwTemplates(Number(v));
                  }}
                  className="w-full px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] focus:bg-white transition-all cursor-pointer"
                >
                  <option value="">Escolha um canal…</option>
                  {channels.map(ch => (
                    <option key={ch.id} value={ch.id}>{ch.name}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider block">Template</label>
                <select
                  value={awTemplateName}
                  onChange={(e) => setAwTemplateName(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] focus:bg-white transition-all cursor-pointer"
                >
                  {awTemplates.length === 0 && awTemplateName && (
                    <option value={awTemplateName}>{awTemplateName}</option>
                  )}
                  {awTemplates.map((t: any) => (
                    <option key={t.name} value={t.name}>{t.name}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider block">Funis (IDs)</label>
                <input
                  type="text"
                  value={awFunnels}
                  onChange={(e) => setAwFunnels(e.target.value)}
                  placeholder="18535,18537,25588"
                  className="w-full px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] focus:bg-white transition-all"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider block">Idioma</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={awLang}
                    onChange={(e) => setAwLang(e.target.value)}
                    placeholder="pt_BR"
                    className="flex-1 min-w-0 px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] focus:bg-white transition-all"
                  />
                  <button
                    onClick={awSave}
                    disabled={awSaving}
                    className="px-4 py-2.5 rounded-xl bg-[#2A658F] text-white text-[13px] font-medium hover:bg-[#1f5375] active:scale-[0.98] transition-all disabled:opacity-40 flex-shrink-0"
                  >
                    Salvar
                  </button>
                </div>
              </div>
            </div>

            {awMsg && (
              <div className={`px-5 py-3 border-t flex items-start gap-2.5 ${awMsg.type === 'ok' ? 'bg-emerald-50 border-emerald-100' : 'bg-red-50 border-red-100'}`}>
                {awMsg.type === 'ok'
                  ? <CheckCircle className="w-4 h-4 text-emerald-600 flex-shrink-0 mt-0.5" />
                  : <XCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />}
                <p className={`text-[12.5px] leading-relaxed ${awMsg.type === 'ok' ? 'text-emerald-800' : 'text-red-700'}`}>{awMsg.text}</p>
              </div>
            )}
          </div>
        )}

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
                  {templates.map((t: any) => {
                    const blocked = isBlockedTemplate(t.name);
                    return (
                      <button
                        key={t.name}
                        onClick={() => selectTemplate(t)}
                        disabled={blocked}
                        title={blocked ? 'Bloqueado — é o template das boas-vindas automáticas' : undefined}
                        className={`w-full text-left px-3 py-2.5 rounded-xl border text-sm transition-all ${
                          blocked
                            ? 'border-gray-50 bg-gray-50 text-gray-400 cursor-not-allowed'
                            : selectedTemplate?.name === t.name
                              ? 'border-[#2A658F] bg-[#2A658F]/5 text-[#2A658F]'
                              : 'border-gray-50 text-gray-700 hover:bg-gray-50 hover:border-gray-100'
                        }`}
                      >
                        <p className="font-medium text-[12px] flex items-center gap-1.5">
                          {blocked && <Lock className="w-3 h-3 flex-shrink-0" />}
                          {t.name.replace(/_/g, ' ')}
                        </p>
                        <p className="text-[10px] text-gray-400 mt-0.5">
                          {blocked ? '(bloqueado — boas-vindas automáticas)' : `${t.parameters.length} variáveis`}
                        </p>
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Mapeamento de variáveis */}
              {selectedTemplate && selectedTemplate.parameters.length > 0 && (
                <div className="mt-4 pt-4 border-t border-gray-100 space-y-3">
                  <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Mapeamento de variáveis</p>
                  {selectedTemplate.parameters.map((_: string, i: number) => (
                    <div key={i} className="space-y-1.5">
                      <label className="text-[11px] text-gray-400 block">{`{{${i + 1}}}`} — Variável {i + 1}</label>
                      <select
                        value={paramMappings[i]?.type || 'fixed_text'}
                        onChange={(e) => updateMapping(i, e.target.value)}
                        className="w-full px-3 py-2 bg-gray-50 border border-gray-100 rounded-lg text-[13px] text-gray-800 focus:outline-none focus:border-[#2A658F] focus:bg-white transition-all cursor-pointer"
                      >
                        {MAPPING_OPTIONS.map(opt => (
                          <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                      </select>
                      {paramMappings[i]?.type === 'fixed_text' && (
                        <input
                          type="text"
                          value={paramMappings[i]?.value || ''}
                          onChange={(e) => updateMappingValue(i, e.target.value)}
                          placeholder="Digite o texto fixo..."
                          className="w-full px-3 py-2 bg-gray-50 border border-gray-100 rounded-lg text-[13px] text-gray-800 placeholder:text-gray-400 focus:outline-none focus:border-[#2A658F] focus:bg-white transition-all"
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Prévia */}
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

            {/* Erro do envio (ex.: trava do template de boas-vindas) */}
            {sendError && (
              <div className="bg-red-50 rounded-2xl p-4 border border-red-100 flex items-start gap-2.5">
                <XCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                <p className="text-[12.5px] text-red-700 leading-relaxed">{sendError}</p>
              </div>
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
                  <select value={funnelFilter} onChange={(e) => setFunnelFilter(e.target.value)} className="px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] transition-all cursor-pointer">
                    <option value="">Todos os funis</option>
                    {funnelIds.map(id => <option key={id} value={id}>{funnelName(Number(id))} ({stats?.by_funnel?.[id]})</option>)}
                  </select>
                  <select value={stageFilter} onChange={(e) => setStageFilter(e.target.value)} className="px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] transition-all cursor-pointer">
                    <option value="">Todos estágios</option>
                    {stages.map(s => <option key={s} value={s}>{s} ({stats?.by_stage[s]})</option>)}
                  </select>
                  <select value={subSourceFilter} onChange={(e) => setSubSourceFilter(e.target.value)} className="px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] transition-all cursor-pointer">
                    <option value="">Todos cursos</option>
                    {subSources.map(s => <option key={s} value={s}>{resolveCourse(s)} ({stats?.by_sub_source[s]})</option>)}
                  </select>
                  <select value={sdrFilter} onChange={(e) => setSdrFilter(e.target.value)} className="px-3 py-2.5 rounded-xl border border-gray-100 bg-gray-50 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F] transition-all cursor-pointer">
                    <option value="">Todos SDRs</option>
                    {sdrs.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                {hasActiveFilters && (
                  <button
                    onClick={() => { setSearch(''); setStageFilter(''); setSubSourceFilter(''); setSdrFilter(''); setFunnelFilter(''); }}
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
                          <span className="text-[13px] text-gray-500">
                            {resolveCourse(lead.sub_source) !== (lead.sub_source ?? '-')
                              ? resolveCourse(lead.sub_source)
                              : funnelName(lead.funnel_id)}
                          </span>
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
      {/* MODAL — LIGAR A BOAS-VINDAS            */}
      {/* ══════════════════════════════════════ */}
      {awConfirm && awPreview && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={() => setAwConfirm(false)}>
          <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-2xl mx-4 border border-gray-100" onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-5">
              <div className="w-11 h-11 bg-amber-50 rounded-xl flex items-center justify-center">
                <Power className="w-5 h-5 text-amber-600" />
              </div>
              <div>
                <h2 className="text-[15px] font-semibold text-[#27273D]">Ligar a boas-vindas automática</h2>
                <p className="text-[13px] text-gray-400">Confirme antes de ativar</p>
              </div>
            </div>

            <div className="bg-gray-50 rounded-xl p-4 mb-4 space-y-2 border border-gray-100">
              <div className="flex justify-between">
                <span className="text-[12px] text-gray-400">Canal</span>
                <span className="text-[13px] font-medium text-gray-700">
                  {channels.find(c => c.id === Number(awChannelId))?.name || '— não escolhido —'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[12px] text-gray-400">Template</span>
                <span className="text-[13px] font-medium text-gray-700">{awTemplateName || '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[12px] text-gray-400">Funis</span>
                <span className="text-[13px] font-medium text-gray-700">{awFunnelIds().join(', ') || '—'}</span>
              </div>
            </div>

            <div className="bg-amber-50 border border-amber-100 rounded-xl p-4 mb-5 flex items-start gap-2.5">
              <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
              <p className="text-[12.5px] text-amber-800 leading-relaxed">
                Ao ligar, <strong>{awPreview.pending_count}</strong> leads que já existem serão marcados
                como &quot;não recebem&quot; e <strong>nunca</strong> receberão a boas-vindas. Só quem for
                cadastrado <strong>depois</strong> deste momento receberá.
              </p>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setAwConfirm(false)}
                className="flex-1 py-2.5 border border-gray-200 rounded-xl text-[13px] font-medium text-gray-500 hover:bg-gray-50 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={awEnable}
                disabled={awSaving}
                className="flex-1 py-2.5 bg-emerald-500 text-white rounded-xl text-[13px] font-medium hover:bg-emerald-600 active:scale-[0.98] transition-all disabled:opacity-60 flex items-center justify-center gap-2"
              >
                {awSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Power className="w-4 h-4" />}
                Ligar automação
              </button>
            </div>
          </div>
        </div>
      )}

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
              {paramMappings.length > 0 && (
                <div className="pt-2 border-t border-gray-200 space-y-1">
                  <span className="text-[11px] text-gray-400 font-semibold uppercase">Variáveis</span>
                  {paramMappings.map((m, i) => (
                    <div key={i} className="flex justify-between">
                      <span className="text-[12px] text-gray-400">{`{{${i + 1}}}`}</span>
                      <span className="text-[12px] font-medium text-gray-700">{getMappingLabel(m)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="mb-4 rounded-xl border border-gray-100 bg-gray-50 p-3">
              <label className="flex items-center gap-1.5 text-[12px] font-medium text-gray-500 mb-1.5">
                <Clock className="w-3.5 h-3.5 text-[#2A658F]" />
                Agendar para (opcional)
              </label>
              <input
                type="datetime-local"
                value={scheduleAt}
                onChange={e => setScheduleAt(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-gray-200 bg-white text-[13px] text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#2A658F]/10 focus:border-[#2A658F]"
              />
              <p className="text-[11px] text-gray-400 mt-1">Deixe em branco para enviar agora.</p>
            </div>
            <div className="flex gap-3">
              <button onClick={() => { setShowConfirm(false); setScheduleAt(''); }} className="flex-1 py-2.5 border border-gray-200 rounded-xl text-[13px] font-medium text-gray-500 hover:bg-gray-50 transition-colors">
                Cancelar
              </button>
              {scheduleAt ? (
                <button onClick={handleSchedule} disabled={scheduling} className="flex-1 py-2.5 bg-[#2A658F] text-white rounded-xl text-[13px] font-medium hover:bg-[#1f5375] active:scale-[0.98] transition-all disabled:opacity-60">
                  {scheduling ? 'Agendando...' : 'Agendar'}
                </button>
              ) : (
                <button onClick={handleBulkSend} className="flex-1 py-2.5 bg-[#2A658F] text-white rounded-xl text-[13px] font-medium hover:bg-[#1f5375] active:scale-[0.98] transition-all">
                  Enviar agora
                </button>
              )}
            </div>
          </div>
        </div>
      )}
      {showSchedules && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={() => setShowSchedules(false)}>
          <div className="bg-white rounded-2xl w-full max-w-2xl shadow-2xl mx-4 border border-gray-100 max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div className="flex items-center gap-2.5">
                <Calendar className="w-5 h-5 text-[#2A658F]" />
                <h2 className="text-[15px] font-semibold text-[#27273D]">Agendamentos</h2>
              </div>
              <button onClick={() => setShowSchedules(false)} className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors">
                <X className="w-4 h-4 text-gray-400" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {schedules.length === 0 ? (
                <p className="text-[13px] text-gray-400 text-center py-10">Nenhum agendamento</p>
              ) : (
                schedules.map(s => {
                  const stCfg: Record<string, string> = { pending: 'bg-amber-50 text-amber-700', sending: 'bg-blue-50 text-blue-700', sent: 'bg-emerald-50 text-emerald-700', cancelled: 'bg-gray-100 text-gray-500', error: 'bg-red-50 text-red-700' };
                  const stLabel: Record<string, string> = { pending: 'Pendente', sending: 'Enviando', sent: 'Enviado', cancelled: 'Cancelado', error: 'Erro' };
                  return (
                    <div key={s.id} className="flex items-center justify-between gap-3 p-3 rounded-xl border border-gray-100 bg-gray-50/50">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-[13px] font-medium text-[#27273D] truncate">{(s.template_name || '').replace(/_/g, ' ')}</span>
                          <span className={`px-2 py-0.5 rounded-md text-[10px] font-semibold ${stCfg[s.status] || 'bg-gray-100 text-gray-500'}`}>{stLabel[s.status] || s.status}</span>
                        </div>
                        <p className="text-[11.5px] text-gray-400">
                          {s.lead_count} leads • {s.scheduled_at ? new Date(s.scheduled_at).toLocaleString('pt-BR') : ''}{s.created_by_name ? ` • por ${s.created_by_name}` : ''}
                        </p>
                      </div>
                      {s.status === 'pending' && (
                        <button onClick={() => cancelSchedule(s.id)} className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[12px] font-medium text-red-600 hover:bg-red-50 transition-colors flex-shrink-0">
                          <Trash2 className="w-3.5 h-3.5" />
                          Cancelar
                        </button>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  );
}