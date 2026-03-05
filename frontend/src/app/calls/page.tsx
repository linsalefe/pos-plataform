'use client';

import { useState, useEffect } from 'react';
import AppLayout from '@/components/AppLayout';
import api from '@/lib/api';
import {
  Phone, PhoneIncoming, PhoneOutgoing, Clock,
  RefreshCw, Trash2, Sparkles, X, FileText, Loader2
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

  const transcribeCall = async (call: CallLog, e: React.MouseEvent) => {
    e.stopPropagation();
    setTranscribing(call.id);
    try {
      const token = localStorage.getItem('token');
      const res = await api.post(`/twilio/transcribe/${call.id}`, {}, {
        headers: { Authorization: `Bearer ${token}` },
        timeout: 120000,
      });
      await fetchCalls();
      setSelectedCall({ ...call, ...res.data });
    } catch (err) {
      console.error('Erro ao transcrever:', err);
    } finally {
      setTranscribing(null);
    }
  };

  const openDrawer = (call: CallLog) => setSelectedCall(call);

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

  const statusLabel: Record<string, { text: string; color: string }> = {
    completed: { text: 'Completada', color: 'bg-green-500/10 text-green-400' },
    'no-answer': { text: 'Sem resposta', color: 'bg-yellow-500/10 text-yellow-400' },
    busy: { text: 'Ocupado', color: 'bg-orange-500/10 text-orange-400' },
    failed: { text: 'Falhou', color: 'bg-red-500/10 text-red-400' },
    initiated: { text: 'Iniciada', color: 'bg-blue-500/10 text-blue-400' },
    ringing: { text: 'Chamando', color: 'bg-blue-500/10 text-blue-400' },
    'in-progress': { text: 'Em andamento', color: 'bg-blue-500/10 text-blue-400' },
  };

  const getStatus = (status: string) =>
    statusLabel[status] || { text: status, color: 'bg-gray-500/10 text-gray-400' };

  const totalCalls = calls.length;
  const completedCalls = calls.filter(c => c.status === 'completed').length;
  const totalDuration = calls.reduce((acc, c) => acc + (c.duration || 0), 0);
  const inboundCalls = calls.filter(c => c.direction === 'inbound').length;

  const formatInsights = (text: string) => {
    return text.split('\n').map((line, i) => {
      if (line.startsWith('**') && line.endsWith('**')) {
        return <p key={i} className="font-bold text-gray-800 mt-4 mb-1">{line.replace(/\*\*/g, '')}</p>;
      }
      if (line.match(/^\d+\.\s\*\*/)) {
        const clean = line.replace(/\*\*/g, '');
        return <p key={i} className="font-semibold text-gray-700 mt-4 mb-1">{clean}</p>;
      }
      if (line.startsWith('   - ') || line.startsWith('- ')) {
        return <p key={i} className="text-gray-600 text-sm pl-3 before:content-['•'] before:mr-2">{line.replace(/^\s*-\s/, '')}</p>;
      }
      if (line.trim() === '') return <br key={i} />;
      return <p key={i} className="text-gray-600 text-sm">{line}</p>;
    });
  };

  return (
    <AppLayout>
      <div className="flex-1 overflow-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Ligações</h1>
            <p className="text-sm text-gray-500 mt-1">Histórico de chamadas via VoIP</p>
          </div>
          <button onClick={fetchCalls} className="flex items-center gap-2 px-4 py-2 bg-[#2A658F] text-white rounded-xl text-sm hover:bg-[#347aab] transition-colors">
            <RefreshCw className="w-4 h-4" /> Atualizar
          </button>
        </div>

        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            { icon: <Phone className="w-5 h-5 text-blue-500" />, bg: 'bg-blue-50', value: totalCalls, label: 'Total de ligações' },
            { icon: <PhoneOutgoing className="w-5 h-5 text-green-500" />, bg: 'bg-green-50', value: completedCalls, label: 'Completadas' },
            { icon: <Clock className="w-5 h-5 text-purple-500" />, bg: 'bg-purple-50', value: formatDuration(totalDuration), label: 'Tempo total' },
            { icon: <PhoneIncoming className="w-5 h-5 text-orange-500" />, bg: 'bg-orange-50', value: inboundCalls, label: 'Recebidas' },
          ].map((card, i) => (
            <div key={i} className="bg-white rounded-xl p-4 border border-gray-100">
              <div className="flex items-center gap-3">
                <div className={`w-10 h-10 rounded-xl ${card.bg} flex items-center justify-center`}>{card.icon}</div>
                <div>
                  <p className="text-2xl font-bold text-gray-800">{card.value}</p>
                  <p className="text-xs text-gray-500">{card.label}</p>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <div className="animate-spin w-6 h-6 border-2 border-[#2A658F] border-t-transparent rounded-full" />
            </div>
          ) : calls.length === 0 ? (
            <div className="text-center py-20">
              <Phone className="w-12 h-12 text-gray-300 mx-auto mb-3" />
              <p className="text-gray-500">Nenhuma ligação registrada</p>
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase">Direção</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase">De / Para</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase">Atendente</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase">Status</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase">Duração</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase">Data</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase">Gravação</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((call) => {
                  const st = getStatus(call.status);
                  const phoneDisplay = call.direction === 'outbound' ? call.to_number : call.from_number;
                  const hasRecording = call.local_recording_path || call.recording_url;
                  return (
                    <tr
                      key={call.id}
                      onClick={() => openDrawer(call)}
                      className="border-b border-gray-50 hover:bg-gray-50/50 transition-colors cursor-pointer"
                    >
                      <td className="px-5 py-3.5">
                        {call.direction === 'outbound'
                          ? <PhoneOutgoing className="w-4 h-4 text-blue-500" />
                          : <PhoneIncoming className="w-4 h-4 text-orange-500" />}
                      </td>
                      <td className="px-5 py-3.5">
                        <p className="text-sm text-gray-800 font-medium">{call.contact_name || formatPhone(phoneDisplay)}</p>
                        <p className="text-xs text-gray-400">{formatPhone(phoneDisplay)}</p>
                      </td>
                      <td className="px-5 py-3.5 text-sm text-gray-600">{call.user_name || '-'}</td>
                      <td className="px-5 py-3.5">
                        <span className={`text-xs font-medium px-2.5 py-1 rounded-lg ${st.color}`}>{st.text}</span>
                      </td>
                      <td className="px-5 py-3.5 text-sm text-gray-600 font-mono">{formatDuration(call.duration)}</td>
                      <td className="px-5 py-3.5 text-sm text-gray-500">{formatDate(call.created_at)}</td>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
                          {hasRecording && (
                            <audio controls className="h-8 w-36" preload="none">
                              <source src={`https://hub.cenatdata.online/api/twilio/recording/${call.call_sid}`} type="audio/mpeg" />
                            </audio>
                          )}
                          {hasRecording && call.transcription_status !== 'done' && (
                            <button
                              onClick={(e) => transcribeCall(call, e)}
                              disabled={transcribing === call.id}
                              className="text-purple-500 hover:text-purple-700 transition-colors"
                              title="Transcrever com IA"
                            >
                              {transcribing === call.id
                                ? <Loader2 className="w-4 h-4 animate-spin" />
                                : <Sparkles className="w-4 h-4" />}
                            </button>
                          )}
                          {call.transcription_status === 'done' && (
                            <span className="text-xs text-purple-500 font-medium flex items-center gap-1">
                              <FileText className="w-3 h-3" /> Insights
                            </span>
                          )}
                          {hasRecording && (
                            <button onClick={(e) => deleteRecording(call.call_sid, e)} className="text-red-400 hover:text-red-600 transition-colors" title="Apagar gravação">
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                          {!hasRecording && <span className="text-xs text-gray-400">-</span>}
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

      {/* Drawer lateral */}
      {selectedCall && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/20" onClick={() => setSelectedCall(null)} />
          <div className="relative w-[480px] h-full bg-white shadow-2xl flex flex-col overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div>
                <p className="font-semibold text-gray-800">
                  {selectedCall.contact_name || formatPhone(selectedCall.direction === 'outbound' ? selectedCall.to_number : selectedCall.from_number)}
                </p>
                <p className="text-xs text-gray-400">{formatDate(selectedCall.created_at)} · {formatDuration(selectedCall.duration)}</p>
              </div>
              <button onClick={() => setSelectedCall(null)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
              {/* Player */}
              {(selectedCall.local_recording_path || selectedCall.recording_url) && (
                <div className="bg-gray-50 rounded-xl p-4">
                  <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Gravação</p>
                  <audio controls className="w-full" preload="none">
                    <source src={`https://hub.cenatdata.online/api/twilio/recording/${selectedCall.call_sid}`} type="audio/mpeg" />
                  </audio>
                </div>
              )}

              {/* Botão transcrever */}
              {(selectedCall.local_recording_path || selectedCall.recording_url) && selectedCall.transcription_status !== 'done' && (
                <button
                  onClick={(e) => transcribeCall(selectedCall, e)}
                  disabled={transcribing === selectedCall.id}
                  className="w-full flex items-center justify-center gap-2 py-2.5 bg-purple-50 text-purple-600 hover:bg-purple-100 rounded-xl text-sm font-medium transition-colors"
                >
                  {transcribing === selectedCall.id
                    ? <><Loader2 className="w-4 h-4 animate-spin" /> Processando...</>
                    : <><Sparkles className="w-4 h-4" /> Gerar Transcrição e Insights</>}
                </button>
              )}

              {/* Transcrição */}
              {selectedCall.transcription && (
                <div className="bg-gray-50 rounded-xl p-4">
                  <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Transcrição</p>
                  <p className="text-sm text-gray-700 leading-relaxed">{selectedCall.transcription}</p>
                </div>
              )}

              {/* Insights */}
              {selectedCall.transcription_insights && (
                <div className="bg-purple-50 rounded-xl p-4">
                  <p className="text-xs font-semibold text-purple-500 uppercase mb-2 flex items-center gap-1">
                    <Sparkles className="w-3 h-3" /> Insights da IA
                  </p>
                  <div className="text-sm">{formatInsights(selectedCall.transcription_insights)}</div>
                </div>
              )}

              {/* Sem gravação */}
              {!selectedCall.local_recording_path && !selectedCall.recording_url && (
                <div className="text-center py-10 text-gray-400">
                  <Phone className="w-10 h-10 mx-auto mb-2 opacity-30" />
                  <p className="text-sm">Nenhuma gravação disponível</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  );
}