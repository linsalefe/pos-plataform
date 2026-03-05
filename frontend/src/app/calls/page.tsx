'use client';

import { useState, useEffect, useRef } from 'react';
import AppLayout from '@/components/AppLayout';
import api from '@/lib/api';
import {
  Phone, PhoneIncoming, PhoneOutgoing, Clock,
  RefreshCw, Trash2, Sparkles, X, FileText, Loader2,
  Play, Volume2, Mic,
  CheckCircle2, AlertCircle, PhoneMissed
} from 'lucide-react';

interface CallLog {
  id: number;
  call_sid: string;
  from_number: string;
  to_number: string;
  direction: string;
  status: string;
  duration: number;
  recording_url: string | null;
  local_recording_path: string | null;
  drive_file_url: string | null;
  user_name: string | null;
  contact_name: string | null;
  transcription_status: string | null;
  transcription: string | null;
  transcription_insights: string | null;
  created_at: string | null;
}

export default function CallsPage() {
  const [calls, setCalls] = useState<CallLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCall, setSelectedCall] = useState<CallLog | null>(null);
  const [transcribing, setTranscribing] = useState<number | null>(null);


  const fetchCalls = async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem('token');
      const res = await api.get('/twilio/call-logs', {
        headers: { Authorization: `Bearer ${token}` },
      });
      setCalls(res.data);
    } catch (err) {
      console.error('Erro ao buscar ligações:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchCalls(); }, []);

  const deleteRecording = async (callSid: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Apagar gravação permanentemente?')) return;
    try {
      const token = localStorage.getItem('token');
      await api.delete(`/twilio/recording/${callSid}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      await fetchCalls();
    } catch (err) {
      console.error('Erro ao apagar gravação:', err);
    }
  };

  const transcribeCall = async (call: CallLog, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setTranscribing(call.id);
    try {
      const token = localStorage.getItem('token');
      const res = await api.post(`/twilio/transcribe/${call.id}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        timeout: 120000,
      });
      await fetchCalls();
      setSelectedCall(prev => prev ? { ...prev, ...res.data } : null);
    } catch (err) {
      console.error('Erro ao transcrever:', err);
    } finally {
      setTranscribing(null);
    }
  };

  const openDrawer = (call: CallLog) => {
    setSelectedCall(call);
  };

  const formatDuration = (seconds: number) => {
    if (!seconds) return '0s';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m === 0 ? `${s}s` : `${m}m${s.toString().padStart(2, '0')}s`;
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString('pt-BR', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  };

  const formatPhone = (phone: string) => {
    const clean = phone.replace('+55', '').replace('+', '');
    if (clean.length === 11) return `(${clean.slice(0, 2)}) ${clean.slice(2, 7)}-${clean.slice(7)}`;
    return phone;
  };

  const statusConfig: Record<string, { text: string; color: string; bg: string; icon: React.ReactNode }> = {
    completed: { text: 'Completada', color: 'text-emerald-600', bg: 'bg-emerald-50', icon: <CheckCircle2 className="w-3 h-3" /> },
    'no-answer': { text: 'Sem resposta', color: 'text-amber-600', bg: 'bg-amber-50', icon: <PhoneMissed className="w-3 h-3" /> },
    busy: { text: 'Ocupado', color: 'text-orange-600', bg: 'bg-orange-50', icon: <AlertCircle className="w-3 h-3" /> },
    failed: { text: 'Falhou', color: 'text-red-600', bg: 'bg-red-50', icon: <AlertCircle className="w-3 h-3" /> },
    initiated: { text: 'Iniciada', color: 'text-blue-600', bg: 'bg-blue-50', icon: <Phone className="w-3 h-3" /> },
    ringing: { text: 'Chamando', color: 'text-blue-600', bg: 'bg-blue-50', icon: <Phone className="w-3 h-3" /> },
    'in-progress': { text: 'Em andamento', color: 'text-blue-600', bg: 'bg-blue-50', icon: <Phone className="w-3 h-3" /> },
  };

  const getStatus = (status: string) =>
    statusConfig[status] || { text: status, color: 'text-gray-600', bg: 'bg-gray-100', icon: null };

  const totalCalls = calls.length;
  const completedCalls = calls.filter(c => c.status === 'completed').length;
  const totalDuration = calls.reduce((acc, c) => acc + (c.duration || 0), 0);
  const inboundCalls = calls.filter(c => c.direction === 'inbound').length;

  const formatInsights = (text: string) => {
    const sections: { title: string; items: string[] }[] = [];
    let currentSection: { title: string; items: string[] } | null = null;

    text.split('\n').forEach(line => {
      if (line.match(/^\d+\.\s\*\*/) || (line.startsWith('**') && line.endsWith('**'))) {
        if (currentSection) sections.push(currentSection);
        currentSection = { title: line.replace(/\*\*/g, '').replace(/^\d+\.\s/, '').trim(), items: [] };
      } else if ((line.startsWith('   - ') || line.startsWith('- ')) && currentSection) {
        currentSection.items.push(line.replace(/^\s*-\s/, '').trim());
      } else if (line.trim() && currentSection && !line.startsWith('**')) {
        currentSection.items.push(line.trim());
      }
    });
    if (currentSection) sections.push(currentSection);

    if (sections.length === 0) {
      return <p className="text-sm text-gray-600 leading-relaxed">{text}</p>;
    }

    const sectionColors = [
      { bg: 'bg-blue-50', border: 'border-blue-100', title: 'text-blue-700', dot: 'bg-blue-400' },
      { bg: 'bg-purple-50', border: 'border-purple-100', title: 'text-purple-700', dot: 'bg-purple-400' },
      { bg: 'bg-emerald-50', border: 'border-emerald-100', title: 'text-emerald-700', dot: 'bg-emerald-400' },
      { bg: 'bg-amber-50', border: 'border-amber-100', title: 'text-amber-700', dot: 'bg-amber-400' },
    ];

    return (
      <div className="space-y-3">
        {sections.map((section, i) => {
          const colors = sectionColors[i % sectionColors.length];
          return (
            <div key={i} className={`rounded-2xl border ${colors.bg} ${colors.border} p-4`}>
              <p className={`text-[10px] font-bold uppercase tracking-widest mb-2 ${colors.title}`}>{section.title}</p>
              <ul className="space-y-1.5">
                {section.items.map((item, j) => (
                  <li key={j} className="flex items-start gap-2 text-sm text-gray-700">
                    <span className={`w-1.5 h-1.5 rounded-full ${colors.dot} mt-1.5 flex-shrink-0`} />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    );
  };

  const phoneDisplay = selectedCall
    ? selectedCall.direction === 'outbound' ? selectedCall.to_number : selectedCall.from_number
    : '';

  const hasRecording = selectedCall && (selectedCall.local_recording_path || selectedCall.recording_url);
  const hasTranscription = selectedCall?.transcription_status === 'done';



  return (
    <AppLayout>
      <div className="flex-1 overflow-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-7">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Ligações</h1>
            <p className="text-sm text-gray-400 mt-0.5">Histórico de chamadas via VoIP</p>
          </div>
          <button
            onClick={fetchCalls}
            className="flex items-center gap-2 px-4 py-2.5 bg-[#2A658F] text-white rounded-xl text-sm font-medium hover:bg-[#347aab] transition-all shadow-sm hover:shadow-md"
          >
            <RefreshCw className="w-4 h-4" /> Atualizar
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            { icon: <Phone className="w-5 h-5 text-[#2A658F]" />, bg: 'bg-[#2A658F]/10', value: totalCalls, label: 'Total de ligações', accent: 'text-[#2A658F]' },
            { icon: <PhoneOutgoing className="w-5 h-5 text-emerald-600" />, bg: 'bg-emerald-50', value: completedCalls, label: 'Completadas', accent: 'text-emerald-600' },
            { icon: <Clock className="w-5 h-5 text-violet-600" />, bg: 'bg-violet-50', value: formatDuration(totalDuration), label: 'Tempo total', accent: 'text-violet-600' },
            { icon: <PhoneIncoming className="w-5 h-5 text-orange-500" />, bg: 'bg-orange-50', value: inboundCalls, label: 'Recebidas', accent: 'text-orange-500' },
          ].map((card, i) => (
            <div key={i} className="bg-white rounded-2xl p-5 border border-gray-100 shadow-sm hover:shadow-md transition-shadow">
              <div className="flex items-center gap-3.5">
                <div className={`w-11 h-11 rounded-xl ${card.bg} flex items-center justify-center flex-shrink-0`}>
                  {card.icon}
                </div>
                <div>
                  <p className={`text-2xl font-bold ${card.accent}`}>{card.value}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{card.label}</p>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Table */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-24 gap-3">
              <div className="animate-spin w-7 h-7 border-2 border-[#2A658F] border-t-transparent rounded-full" />
              <p className="text-sm text-gray-400">Carregando ligações...</p>
            </div>
          ) : calls.length === 0 ? (
            <div className="text-center py-24">
              <div className="w-16 h-16 rounded-2xl bg-gray-50 flex items-center justify-center mx-auto mb-4">
                <Phone className="w-8 h-8 text-gray-300" />
              </div>
              <p className="text-gray-500 font-medium">Nenhuma ligação registrada</p>
              <p className="text-sm text-gray-400 mt-1">As chamadas aparecerão aqui automaticamente</p>
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/70">
                  <th className="text-left px-5 py-3.5 text-[10px] font-bold text-gray-400 uppercase tracking-widest">Direção</th>
                  <th className="text-left px-5 py-3.5 text-[10px] font-bold text-gray-400 uppercase tracking-widest">De / Para</th>
                  <th className="text-left px-5 py-3.5 text-[10px] font-bold text-gray-400 uppercase tracking-widest">Atendente</th>
                  <th className="text-left px-5 py-3.5 text-[10px] font-bold text-gray-400 uppercase tracking-widest">Status</th>
                  <th className="text-left px-5 py-3.5 text-[10px] font-bold text-gray-400 uppercase tracking-widest">Duração</th>
                  <th className="text-left px-5 py-3.5 text-[10px] font-bold text-gray-400 uppercase tracking-widest">Data</th>
                  <th className="text-left px-5 py-3.5 text-[10px] font-bold text-gray-400 uppercase tracking-widest">Gravação</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((call) => {
                  const st = getStatus(call.status);
                  const phone = call.direction === 'outbound' ? call.to_number : call.from_number;
                  const hasRec = call.local_recording_path || call.recording_url;
                  const isSelected = selectedCall?.id === call.id;
                  return (
                    <tr
                      key={call.id}
                      onClick={() => openDrawer(call)}
                      className={`border-b border-gray-50 transition-colors cursor-pointer group ${isSelected ? 'bg-blue-50/60' : 'hover:bg-gray-50/70'}`}
                    >
                      <td className="px-5 py-3.5">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center transition-colors ${call.direction === 'outbound' ? 'bg-blue-50 group-hover:bg-blue-100' : 'bg-orange-50 group-hover:bg-orange-100'}`}>
                          {call.direction === 'outbound'
                            ? <PhoneOutgoing className="w-3.5 h-3.5 text-blue-500" />
                            : <PhoneIncoming className="w-3.5 h-3.5 text-orange-500" />}
                        </div>
                      </td>
                      <td className="px-5 py-3.5">
                        <p className="text-sm text-gray-900 font-semibold">{call.contact_name || formatPhone(phone)}</p>
                        <p className="text-xs text-gray-400 mt-0.5">{formatPhone(phone)}</p>
                      </td>
                      <td className="px-5 py-3.5">
                        {call.user_name
                          ? <span className="text-sm text-gray-600 font-medium">{call.user_name}</span>
                          : <span className="text-sm text-gray-300">—</span>}
                      </td>
                      <td className="px-5 py-3.5">
                        <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-lg ${st.color} ${st.bg}`}>
                          {st.icon} {st.text}
                        </span>
                      </td>
                      <td className="px-5 py-3.5">
                        <span className="text-sm text-gray-600 font-mono tabular-nums">{formatDuration(call.duration)}</span>
                      </td>
                      <td className="px-5 py-3.5 text-sm text-gray-400">{formatDate(call.created_at)}</td>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
                          {hasRec && (
                            <button
                              onClick={() => openDrawer(call)}
                              className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 hover:bg-[#2A658F] hover:text-white text-gray-600 rounded-lg text-xs font-medium transition-all"
                            >
                              <Play className="w-3 h-3" /> Ouvir
                            </button>
                          )}
                          {hasRec && call.transcription_status !== 'done' && (
                            <button
                              onClick={(e) => transcribeCall(call, e)}
                              disabled={transcribing === call.id}
                              className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-50 hover:bg-violet-100 text-violet-600 rounded-lg text-xs font-medium transition-all disabled:opacity-60"
                              title="Transcrever com IA"
                            >
                              {transcribing === call.id
                                ? <Loader2 className="w-3 h-3 animate-spin" />
                                : <Sparkles className="w-3 h-3" />}
                            </button>
                          )}
                          {call.transcription_status === 'done' && (
                            <span className="flex items-center gap-1 text-xs text-violet-500 font-semibold">
                              <FileText className="w-3 h-3" /> Insights
                            </span>
                          )}
                          {hasRec && (
                            <button
                              onClick={(e) => deleteRecording(call.call_sid, e)}
                              className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-300 hover:bg-red-50 hover:text-red-500 transition-all"
                              title="Apagar gravação"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                          {!hasRec && <span className="text-gray-300 text-sm">—</span>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Drawer */}
      {selectedCall && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px]" onClick={() => setSelectedCall(null)} />
          <div className="relative w-[520px] h-full bg-white shadow-2xl flex flex-col" style={{ animation: 'slideIn 0.25s ease-out' }}>

            {/* Header */}
            <div className="px-6 pt-6 pb-4 border-b border-gray-100">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-11 h-11 rounded-2xl flex items-center justify-center ${selectedCall.direction === 'outbound' ? 'bg-blue-50' : 'bg-orange-50'}`}>
                    {selectedCall.direction === 'outbound'
                      ? <PhoneOutgoing className="w-5 h-5 text-blue-500" />
                      : <PhoneIncoming className="w-5 h-5 text-orange-500" />}
                  </div>
                  <div>
                    <p className="font-bold text-gray-900 text-base leading-tight">
                      {selectedCall.contact_name || formatPhone(phoneDisplay)}
                    </p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {formatDate(selectedCall.created_at)} · {formatDuration(selectedCall.duration)}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setSelectedCall(null)}
                  className="w-8 h-8 flex items-center justify-center rounded-xl text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-all"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="mt-3 flex items-center gap-2 flex-wrap">
                {(() => {
                  const st = getStatus(selectedCall.status);
                  return (
                    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-xl ${st.color} ${st.bg}`}>
                      {st.icon} {st.text}
                    </span>
                  );
                })()}
                {selectedCall.user_name && (
                  <span className="text-xs text-gray-500 bg-gray-100 px-3 py-1.5 rounded-xl font-medium">
                    👤 {selectedCall.user_name}
                  </span>
                )}
              </div>

            </div>

            {/* Body — tudo em sequência, sem abas */}
            <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">

              {/* Gravação */}
              {hasRecording ? (
                <div>
                  <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-3">Áudio da chamada</p>
                  <div className="bg-gradient-to-br from-[#2A658F]/5 to-[#347aab]/10 rounded-2xl p-5 border border-[#2A658F]/10">
                    <div className="flex items-center gap-3 mb-4">
                      <div className="w-10 h-10 rounded-xl bg-[#2A658F] flex items-center justify-center flex-shrink-0">
                        <Volume2 className="w-5 h-5 text-white" />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-gray-800">Gravação da chamada</p>
                        <p className="text-xs text-gray-400">Duração: {formatDuration(selectedCall.duration)}</p>
                      </div>
                    </div>
                    <audio controls className="w-full rounded-xl" preload="metadata">
                      <source src={`https://hub.cenatdata.online/api/twilio/recording/${selectedCall.call_sid}`} type="audio/mpeg" />
                    </audio>
                  </div>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-10 text-center">
                  <div className="w-14 h-14 rounded-2xl bg-gray-50 flex items-center justify-center mb-3">
                    <Phone className="w-7 h-7 text-gray-200" />
                  </div>
                  <p className="text-gray-500 font-medium text-sm">Sem gravação</p>
                  <p className="text-xs text-gray-400 mt-1">Esta chamada não possui gravação disponível</p>
                </div>
              )}

              {/* Botão transcrever */}
              {hasRecording && !hasTranscription && (
                <div>
                  <button
                    onClick={() => transcribeCall(selectedCall!)}
                    disabled={transcribing === selectedCall!.id}
                    className="w-full flex items-center justify-center gap-2 py-3 bg-gradient-to-r from-violet-500 to-purple-600 text-white hover:from-violet-600 hover:to-purple-700 rounded-2xl text-sm font-semibold transition-all shadow-sm hover:shadow-md disabled:opacity-60"
                  >
                    {transcribing === selectedCall!.id
                      ? <><Loader2 className="w-4 h-4 animate-spin" /> Processando transcrição...</>
                      : <><Sparkles className="w-4 h-4" /> Gerar Transcrição com IA</>}
                  </button>
                  <p className="text-xs text-gray-400 text-center mt-2">Powered by OpenAI Whisper + GPT-4o</p>
                </div>
              )}

              {/* Transcrição */}
              {selectedCall?.transcription && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <Mic className="w-3.5 h-3.5 text-gray-400" />
                    <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Transcrição</p>
                  </div>
                  <div className="bg-gray-50 rounded-2xl p-4 border border-gray-100">
                    <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{selectedCall.transcription}</p>
                  </div>
                </div>
              )}

              {/* Insights */}
              {selectedCall?.transcription_insights && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <Sparkles className="w-3.5 h-3.5 text-violet-500" />
                    <p className="text-[10px] font-bold text-violet-500 uppercase tracking-widest">Insights da IA</p>
                    <span className="text-[10px] text-gray-400 ml-1">· GPT-4o</span>
                  </div>
                  {formatInsights(selectedCall.transcription_insights)}
                </div>
              )}

            </div>

            {/* Footer */}
            <div className="px-6 py-4 border-t border-gray-100 bg-gray-50/50 flex items-center gap-2">
              {hasRecording && (
                <button
                  onClick={(e) => deleteRecording(selectedCall!.call_sid, e)}
                  className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-red-500 hover:bg-red-50 rounded-xl transition-all"
                >
                  <Trash2 className="w-3.5 h-3.5" /> Apagar gravação
                </button>
              )}
              {hasRecording && !hasTranscription && (
                <button
                  onClick={() => transcribeCall(selectedCall!)}
                  disabled={transcribing === selectedCall!.id}
                  className="ml-auto flex items-center gap-1.5 px-4 py-2 bg-violet-600 text-white text-xs font-semibold rounded-xl hover:bg-violet-700 transition-all disabled:opacity-60"
                >
                  {transcribing === selectedCall!.id
                    ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Processando...</>
                    : <><Sparkles className="w-3.5 h-3.5" /> Transcrever</>}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      <style jsx global>{`
        @keyframes slideIn {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
      `}</style>
    </AppLayout>
  );
}