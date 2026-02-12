'use client';

import { useState, useEffect } from 'react';
import AppLayout from '@/components/AppLayout';
import api from '@/lib/api';
import {
  Phone,
  PhoneIncoming,
  PhoneOutgoing,
  Clock,
  ExternalLink,
  RefreshCw,
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
  drive_file_url: string | null;
  user_name: string | null;
  contact_name: string | null;
  created_at: string | null;
}

export default function CallsPage() {
  const [calls, setCalls] = useState<CallLog[]>([]);
  const [loading, setLoading] = useState(true);

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

  useEffect(() => {
    fetchCalls();
  }, []);

  const formatDuration = (seconds: number) => {
    if (!seconds) return '0s';
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    if (m === 0) return `${s}s`;
    return `${m}m${s.toString().padStart(2, '0')}s`;
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    const d = new Date(dateStr);
    return d.toLocaleDateString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatPhone = (phone: string) => {
    const clean = phone.replace('+55', '').replace('+', '');
    if (clean.length === 11) {
      return `(${clean.slice(0, 2)}) ${clean.slice(2, 7)}-${clean.slice(7)}`;
    }
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
  const completedCalls = calls.filter((c) => c.status === 'completed').length;
  const totalDuration = calls.reduce((acc, c) => acc + (c.duration || 0), 0);
  const inboundCalls = calls.filter((c) => c.direction === 'inbound').length;

  return (
    <AppLayout>
      <div className="flex-1 overflow-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-800">Ligações</h1>
            <p className="text-sm text-gray-500 mt-1">Histórico de chamadas via VoIP</p>
          </div>
          <button
            onClick={fetchCalls}
            className="flex items-center gap-2 px-4 py-2 bg-[#2A658F] text-white rounded-xl text-sm hover:bg-[#347aab] transition-colors"
          >
            <RefreshCw className="w-4 h-4" /> Atualizar
          </button>
        </div>

        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="bg-white rounded-xl p-4 border border-gray-100">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
                <Phone className="w-5 h-5 text-blue-500" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-800">{totalCalls}</p>
                <p className="text-xs text-gray-500">Total de ligações</p>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl p-4 border border-gray-100">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-green-50 flex items-center justify-center">
                <PhoneOutgoing className="w-5 h-5 text-green-500" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-800">{completedCalls}</p>
                <p className="text-xs text-gray-500">Completadas</p>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl p-4 border border-gray-100">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-purple-50 flex items-center justify-center">
                <Clock className="w-5 h-5 text-purple-500" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-800">{formatDuration(totalDuration)}</p>
                <p className="text-xs text-gray-500">Tempo total</p>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-xl p-4 border border-gray-100">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-orange-50 flex items-center justify-center">
                <PhoneIncoming className="w-5 h-5 text-orange-500" />
              </div>
              <div>
                <p className="text-2xl font-bold text-gray-800">{inboundCalls}</p>
                <p className="text-xs text-gray-500">Recebidas</p>
              </div>
            </div>
          </div>
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
                  return (
                    <tr key={call.id} className="border-b border-gray-50 hover:bg-gray-50/50 transition-colors">
                      <td className="px-5 py-3.5">
                        {call.direction === 'outbound' ? (
                          <PhoneOutgoing className="w-4 h-4 text-blue-500" />
                        ) : (
                          <PhoneIncoming className="w-4 h-4 text-orange-500" />
                        )}
                      </td>
                      <td className="px-5 py-3.5">
                        <p className="text-sm text-gray-800 font-medium">
                          {call.contact_name || formatPhone(phoneDisplay)}
                        </p>
                        <p className="text-xs text-gray-400">{formatPhone(phoneDisplay)}</p>
                      </td>
                      <td className="px-5 py-3.5 text-sm text-gray-600">{call.user_name || '-'}</td>
                      <td className="px-5 py-3.5">
                        <span className={`text-xs font-medium px-2.5 py-1 rounded-lg ${st.color}`}>{st.text}</span>
                      </td>
                      <td className="px-5 py-3.5 text-sm text-gray-600 font-mono">{formatDuration(call.duration)}</td>
                      <td className="px-5 py-3.5 text-sm text-gray-500">{formatDate(call.created_at)}</td>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-2">
                          {call.recording_url && (
                            <audio controls className="h-8 w-36" preload="none">
                              <source
                                src={`https://hub.cenatdata.online/api/twilio/recording/${call.recording_url.match(/Recordings\/(RE[^.]+)/)?.[1] || ''}`}
                                type="audio/mpeg"
                              />
                            </audio>
                          )}
                          {call.drive_file_url && (
                            <a
                              href={call.drive_file_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[#2A658F] hover:text-[#347aab] transition-colors"
                              title="Abrir no Google Drive"
                            >
                              <ExternalLink className="w-4 h-4" />
                            </a>
                          )}
                          {!call.recording_url && !call.drive_file_url && (
                            <span className="text-xs text-gray-400">-</span>
                          )}
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
    </AppLayout>
  );
}