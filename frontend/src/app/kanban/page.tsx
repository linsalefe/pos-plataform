'use client';

import { useEffect, useState } from 'react';
import {
  Bot, User, MessageCircle, Clock, CheckCircle, ArrowRight,
  Loader2, ChevronDown, Filter, RefreshCw, FileText, Phone,
  GraduationCap, Calendar, Sparkles, AlertCircle
} from 'lucide-react';
import AppLayout from '@/components/AppLayout';
import api from '@/lib/api';

interface KanbanCard {
  id: number;
  contact_wa_id: string;
  channel_id: number;
  status: string;
  summary: string | null;
  lead_name: string | null;
  lead_course: string | null;
  ai_messages_count: number;
  human_took_over: boolean;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string | null;
}

interface KanbanStats {
  total: number;
  em_atendimento_ia: number;
  aguardando_humano: number;
  finalizado: number;
  human_took_over: number;
}

interface ChannelInfo {
  id: number;
  name: string;
}

const columns = [
  {
    key: 'em_atendimento_ia',
    label: 'Em Atendimento IA',
    icon: Bot,
    color: 'purple',
    bgHeader: 'bg-purple-50',
    borderColor: 'border-purple-200',
    textColor: 'text-purple-700',
    badgeBg: 'bg-purple-100',
    iconColor: 'text-purple-500',
    dotColor: 'bg-purple-500',
  },
  {
    key: 'aguardando_humano',
    label: 'Aguardando Humano',
    icon: User,
    color: 'amber',
    bgHeader: 'bg-amber-50',
    borderColor: 'border-amber-200',
    textColor: 'text-amber-700',
    badgeBg: 'bg-amber-100',
    iconColor: 'text-amber-500',
    dotColor: 'bg-amber-500',
  },
  {
    key: 'finalizado',
    label: 'Finalizado',
    icon: CheckCircle,
    color: 'emerald',
    bgHeader: 'bg-emerald-50',
    borderColor: 'border-emerald-200',
    textColor: 'text-emerald-700',
    badgeBg: 'bg-emerald-100',
    iconColor: 'text-emerald-500',
    dotColor: 'bg-emerald-500',
  },
];

export default function KanbanPage() {
  const [cards, setCards] = useState<KanbanCard[]>([]);
  const [stats, setStats] = useState<KanbanStats | null>(null);
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [filterChannel, setFilterChannel] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [movingCard, setMovingCard] = useState<number | null>(null);
  const [generatingSummary, setGeneratingSummary] = useState<number | null>(null);
  const [selectedCard, setSelectedCard] = useState<KanbanCard | null>(null);
  const [editingSummary, setEditingSummary] = useState(false);
  const [summaryText, setSummaryText] = useState('');
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    loadChannels();
    loadCards();
    loadStats();
    const interval = setInterval(() => {
      loadCards();
      loadStats();
    }, 10000);
    return () => clearInterval(interval);
  }, [filterChannel]);

  const loadChannels = async () => {
    try {
      const res = await api.get('/channels');
      setChannels(res.data);
    } catch (err) {
      console.error('Erro:', err);
    }
  };

  const loadCards = async () => {
    try {
      const params = filterChannel ? `?channel_id=${filterChannel}` : '';
      const res = await api.get(`/kanban/cards${params}`);
      setCards(res.data);
    } catch (err) {
      console.error('Erro:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async () => {
    try {
      const params = filterChannel ? `?channel_id=${filterChannel}` : '';
      const res = await api.get(`/kanban/stats${params}`);
      setStats(res.data);
    } catch (err) {
      console.error('Erro:', err);
    }
  };

  const moveCard = async (cardId: number, newStatus: string) => {
    setMovingCard(cardId);
    try {
      await api.patch(`/kanban/cards/${cardId}/move`, { status: newStatus });
      loadCards();
      loadStats();
      if (selectedCard?.id === cardId) {
        setSelectedCard({ ...selectedCard, status: newStatus });
      }
    } catch (err) {
      console.error('Erro ao mover:', err);
    } finally {
      setMovingCard(null);
    }
  };

  const generateSummary = async (cardId: number) => {
    setGeneratingSummary(cardId);
    try {
      const res = await api.post(`/kanban/cards/${cardId}/generate-summary`);
      loadCards();
      if (selectedCard?.id === cardId) {
        setSelectedCard({ ...selectedCard, summary: res.data.summary });
        setSummaryText(res.data.summary);
      }
    } catch (err) {
      console.error('Erro ao gerar resumo:', err);
    } finally {
      setGeneratingSummary(null);
    }
  };

  const saveSummary = async () => {
    if (!selectedCard) return;
    try {
      await api.patch(`/kanban/cards/${selectedCard.id}`, { summary: summaryText });
      setEditingSummary(false);
      loadCards();
      setSelectedCard({ ...selectedCard, summary: summaryText });
    } catch (err) {
      console.error('Erro ao salvar:', err);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '';
    return new Date(dateStr).toLocaleDateString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getCardsByStatus = (status: string) => cards.filter(c => c.status === status);

  if (!mounted) return null;

  return (
    <AppLayout>
      <div className="flex-1 bg-[#f8f9fb] overflow-hidden flex flex-col">

        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 bg-white flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-md">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-[#27273D]">Kanban — Atendimentos IA</h1>
                <p className="text-[12px] text-gray-400">
                  Acompanhe todos os leads atendidos pela Nat
                  {stats && ` · ${stats.total} total`}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {/* Filtro Canal */}
              <select
                value={filterChannel || ''}
                onChange={e => setFilterChannel(e.target.value ? parseInt(e.target.value) : null)}
                className="px-3 py-2 rounded-xl border border-gray-200 text-[13px] bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-purple-200"
              >
                <option value="">Todos os canais</option>
                {channels.map(ch => (
                  <option key={ch.id} value={ch.id}>{ch.name}</option>
                ))}
              </select>

              <button
                onClick={() => { loadCards(); loadStats(); }}
                className="p-2.5 rounded-xl border border-gray-200 bg-white text-gray-500 hover:text-purple-600 hover:border-purple-200 transition-all"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Stats */}
          {stats && (
            <div className="flex gap-4 mt-4">
              {columns.map(col => (
                <div key={col.key} className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${col.badgeBg}`}>
                  <div className={`w-2 h-2 rounded-full ${col.dotColor}`} />
                  <span className={`text-[12px] font-medium ${col.textColor}`}>
                    {col.label}: {stats[col.key as keyof KanbanStats] || 0}
                  </span>
                </div>
              ))}
              {stats.human_took_over > 0 && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-100">
                  <User className="w-3 h-3 text-blue-500" />
                  <span className="text-[12px] font-medium text-blue-700">
                    Humano assumiu: {stats.human_took_over}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Board */}
        <div className="flex-1 overflow-x-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="w-6 h-6 animate-spin text-purple-500" />
            </div>
          ) : (
            <div className="flex gap-5 h-full min-w-max">
              {columns.map(col => {
                const colCards = getCardsByStatus(col.key);
                const Icon = col.icon;

                return (
                  <div key={col.key} className="w-[340px] flex flex-col">
                    {/* Column Header */}
                    <div className={`px-4 py-3 rounded-t-2xl ${col.bgHeader} border ${col.borderColor} border-b-0`}>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Icon className={`w-4 h-4 ${col.iconColor}`} />
                          <span className={`text-[13px] font-semibold ${col.textColor}`}>{col.label}</span>
                        </div>
                        <span className={`text-[12px] font-bold ${col.textColor} ${col.badgeBg} px-2 py-0.5 rounded-full`}>
                          {colCards.length}
                        </span>
                      </div>
                    </div>

                    {/* Cards */}
                    <div className={`flex-1 border ${col.borderColor} border-t-0 rounded-b-2xl bg-white/50 p-3 space-y-3 overflow-y-auto`}>
                      {colCards.length === 0 ? (
                        <div className="text-center py-10 text-gray-300">
                          <Icon className="w-8 h-8 mx-auto mb-2 opacity-30" />
                          <p className="text-[12px]">Nenhum card</p>
                        </div>
                      ) : (
                        colCards.map(card => (
                          <div
                            key={card.id}
                            onClick={() => {
                              setSelectedCard(card);
                              setSummaryText(card.summary || '');
                              setEditingSummary(false);
                            }}
                            className="bg-white rounded-xl border border-gray-200 p-4 space-y-3 cursor-pointer hover:border-gray-300 hover:shadow-sm transition-all"
                          >
                            {/* Card Header */}
                            <div className="flex items-start justify-between">
                              <div className="flex items-center gap-2.5 min-w-0">
                                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-100 to-blue-100 flex items-center justify-center flex-shrink-0">
                                  <span className="text-[12px] font-bold text-purple-600">
                                    {(card.lead_name || '?')[0].toUpperCase()}
                                  </span>
                                </div>
                                <div className="min-w-0">
                                  <p className="text-[13px] font-semibold text-[#27273D] truncate">
                                    {card.lead_name || card.contact_wa_id}
                                  </p>
                                  <p className="text-[11px] text-gray-400 truncate flex items-center gap-1">
                                    <Phone className="w-3 h-3" />
                                    +{card.contact_wa_id}
                                  </p>
                                </div>
                              </div>
                              {card.human_took_over && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 font-medium flex-shrink-0">
                                  👤 Humano
                                </span>
                              )}
                            </div>

                            {/* Curso */}
                            {card.lead_course && (
                              <div className="flex items-center gap-1.5">
                                <GraduationCap className="w-3.5 h-3.5 text-purple-400" />
                                <span className="text-[11px] text-purple-600 font-medium truncate">
                                  {card.lead_course}
                                </span>
                              </div>
                            )}

                            {/* Summary */}
                            {card.summary && (
                              <p className="text-[11px] text-gray-500 leading-relaxed line-clamp-2 bg-gray-50 rounded-lg px-2.5 py-2">
                                {card.summary}
                              </p>
                            )}

                            {/* Footer */}
                            <div className="flex items-center justify-between pt-1 border-t border-gray-100">
                              <div className="flex items-center gap-3">
                                <span className="text-[10px] text-gray-400 flex items-center gap-1">
                                  <MessageCircle className="w-3 h-3" />
                                  {card.ai_messages_count} msgs IA
                                </span>
                                {card.started_at && (
                                  <span className="text-[10px] text-gray-400 flex items-center gap-1">
                                    <Clock className="w-3 h-3" />
                                    {formatDate(card.started_at)}
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Move Buttons */}
                            <div className="flex gap-1.5">
                              {col.key !== 'em_atendimento_ia' && (
                                <button
                                  onClick={e => { e.stopPropagation(); moveCard(card.id, 'em_atendimento_ia'); }}
                                  disabled={movingCard === card.id}
                                  className="flex-1 text-[10px] py-1.5 rounded-lg bg-purple-50 text-purple-600 font-medium hover:bg-purple-100 transition-all"
                                >
                                  🤖 Voltar p/ IA
                                </button>
                              )}
                              {col.key !== 'aguardando_humano' && (
                                <button
                                  onClick={e => { e.stopPropagation(); moveCard(card.id, 'aguardando_humano'); }}
                                  disabled={movingCard === card.id}
                                  className="flex-1 text-[10px] py-1.5 rounded-lg bg-amber-50 text-amber-600 font-medium hover:bg-amber-100 transition-all"
                                >
                                  👤 Humano
                                </button>
                              )}
                              {col.key !== 'finalizado' && (
                                <button
                                  onClick={e => { e.stopPropagation(); moveCard(card.id, 'finalizado'); }}
                                  disabled={movingCard === card.id}
                                  className="flex-1 text-[10px] py-1.5 rounded-lg bg-emerald-50 text-emerald-600 font-medium hover:bg-emerald-100 transition-all"
                                >
                                  ✅ Finalizar
                                </button>
                              )}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Modal Card Detail */}
        {selectedCard && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setSelectedCard(null)}>
            <div className="bg-white rounded-2xl w-[520px] max-h-[80vh] overflow-y-auto shadow-2xl" onClick={e => e.stopPropagation()}>
              <div className="p-6 space-y-5">

                {/* Header */}
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-purple-100 to-blue-100 flex items-center justify-center">
                      <span className="text-lg font-bold text-purple-600">
                        {(selectedCard.lead_name || '?')[0].toUpperCase()}
                      </span>
                    </div>
                    <div>
                      <p className="text-[16px] font-bold text-[#27273D]">
                        {selectedCard.lead_name || selectedCard.contact_wa_id}
                      </p>
                      <p className="text-[12px] text-gray-400 flex items-center gap-1.5">
                        <Phone className="w-3 h-3" /> +{selectedCard.contact_wa_id}
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => setSelectedCard(null)}
                    className="text-gray-400 hover:text-gray-600 text-xl"
                  >
                    ×
                  </button>
                </div>

                {/* Info */}
                <div className="grid grid-cols-2 gap-3">
                  {selectedCard.lead_course && (
                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-purple-50">
                      <GraduationCap className="w-4 h-4 text-purple-500" />
                      <span className="text-[12px] font-medium text-purple-700">{selectedCard.lead_course}</span>
                    </div>
                  )}
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-50">
                    <MessageCircle className="w-4 h-4 text-gray-400" />
                    <span className="text-[12px] text-gray-600">{selectedCard.ai_messages_count} mensagens da IA</span>
                  </div>
                  {selectedCard.started_at && (
                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-50">
                      <Calendar className="w-4 h-4 text-gray-400" />
                      <span className="text-[12px] text-gray-600">Início: {formatDate(selectedCard.started_at)}</span>
                    </div>
                  )}
                  {selectedCard.finished_at && (
                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-50">
                      <CheckCircle className="w-4 h-4 text-emerald-500" />
                      <span className="text-[12px] text-emerald-700">Fim: {formatDate(selectedCard.finished_at)}</span>
                    </div>
                  )}
                </div>

                {/* Status */}
                <div>
                  <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Status</p>
                  <div className="flex gap-2">
                    {columns.map(col => (
                      <button
                        key={col.key}
                        onClick={() => moveCard(selectedCard.id, col.key)}
                        disabled={movingCard === selectedCard.id}
                        className={`flex-1 py-2 rounded-xl text-[12px] font-medium border transition-all ${
                          selectedCard.status === col.key
                            ? `${col.bgHeader} ${col.borderColor} ${col.textColor}`
                            : 'bg-gray-50 border-gray-200 text-gray-500 hover:bg-gray-100'
                        }`}
                      >
                        {col.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Summary */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Resumo da Conversa</p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => generateSummary(selectedCard.id)}
                        disabled={generatingSummary === selectedCard.id}
                        className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-purple-50 text-purple-600 text-[11px] font-medium hover:bg-purple-100 transition-all"
                      >
                        {generatingSummary === selectedCard.id
                          ? <Loader2 className="w-3 h-3 animate-spin" />
                          : <Sparkles className="w-3 h-3" />}
                        {generatingSummary === selectedCard.id ? 'Gerando...' : 'Gerar com IA'}
                      </button>
                      {!editingSummary && (
                        <button
                          onClick={() => setEditingSummary(true)}
                          className="px-2.5 py-1 rounded-lg bg-gray-50 text-gray-500 text-[11px] font-medium hover:bg-gray-100 transition-all"
                        >
                          Editar
                        </button>
                      )}
                    </div>
                  </div>
                  {editingSummary ? (
                    <div className="space-y-2">
                      <textarea
                        value={summaryText}
                        onChange={e => setSummaryText(e.target.value)}
                        rows={4}
                        className="w-full px-3 py-2.5 rounded-xl border border-gray-200 text-[13px] bg-gray-50 focus:outline-none focus:ring-2 focus:ring-purple-200 resize-none"
                        placeholder="Escreva o resumo da conversa..."
                      />
                      <div className="flex justify-end gap-2">
                        <button
                          onClick={() => { setEditingSummary(false); setSummaryText(selectedCard.summary || ''); }}
                          className="px-3 py-1.5 rounded-lg text-[12px] text-gray-500 hover:bg-gray-100"
                        >
                          Cancelar
                        </button>
                        <button
                          onClick={saveSummary}
                          className="px-3 py-1.5 rounded-lg bg-purple-600 text-white text-[12px] font-medium hover:bg-purple-700"
                        >
                          Salvar
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="bg-gray-50 rounded-xl px-4 py-3 min-h-[60px]">
                      {selectedCard.summary ? (
                        <p className="text-[13px] text-gray-600 leading-relaxed">{selectedCard.summary}</p>
                      ) : (
                        <p className="text-[12px] text-gray-400 italic">
                          Nenhum resumo ainda. Clique em &quot;Gerar com IA&quot; para criar automaticamente.
                        </p>
                      )}
                    </div>
                  )}
                </div>

                {/* Open Conversation */}
                <a
                  href={`/conversations`}
                  className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl bg-[#0f1b2d] text-white text-[13px] font-medium hover:bg-[#1a2d42] transition-all"
                >
                  <MessageCircle className="w-4 h-4" />
                  Abrir Conversa
                </a>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
