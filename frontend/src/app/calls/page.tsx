'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Phone, PhoneOff, PhoneIncoming, PhoneMissed,
  Mic, MicOff, Delete, Clock, User, ExternalLink, Play,
  ArrowDownLeft, ArrowUpRight, RefreshCw
} from 'lucide-react';
import { Device, Call } from '@twilio/voice-sdk';

type CallStatus = 'idle' | 'connecting' | 'ringing' | 'in-call' | 'incoming';

interface CallLogEntry {
  id: number;
  call_sid: string;
  from_number: string;
  to_number: string;
  direction: string;
  status: string;
  duration: number;
  recording_url: string | null;
  drive_file_url: string | null;
  user_name: string;
  contact_name: string | null;
  created_at: string;
}

export default function CallsPage() {
  const [status, setStatus] = useState<CallStatus>('idle');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [callDuration, setCallDuration] = useState(0);
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState('');
  const [deviceReady, setDeviceReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [callLogs, setCallLogs] = useState<CallLogEntry[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(true);
  const [playingAudio, setPlayingAudio] = useState<string | null>(null);

  const deviceRef = useRef<Device | null>(null);
  const callRef = useRef<Call | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const initStartedRef = useRef(false);

  useEffect(() => {
    initDevice();
    fetchCallLogs();
    return () => {
      if (deviceRef.current) { try { deviceRef.current.destroy(); } catch (e) {} }
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const fetchCallLogs = async () => {
    try {
      const token = localStorage.getItem('token');
      if (!token) return;
      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://hub.cenatdata.online/api';
      const res = await fetch(`${API_URL}/twilio/call-logs`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setCallLogs(data.call_logs || []);
      }
    } catch (err) {
      console.error('Erro ao buscar histórico:', err);
    } finally {
      setLoadingLogs(false);
    }
  };

  const initDevice = useCallback(async () => {
    if (initStartedRef.current) return;
    initStartedRef.current = true;
    setLoading(true);
    setError('');
    try {
      const token = localStorage.getItem('token');
      if (!token) { setError('Faça login'); initStartedRef.current = false; setLoading(false); return; }
      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://hub.cenatdata.online/api';
      const res = await fetch(`${API_URL}/twilio/token`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error('Erro ao obter token');
      const data = await res.json();
      const device = new Device(data.token, {
        codecPreferences: [Call.Codec.Opus, Call.Codec.PCMU],
        closeProtection: true, logLevel: 1,
      });
      device.on('registered', () => { setDeviceReady(true); setLoading(false); setError(''); });
      device.on('error', (err: any) => { setError(err.message || 'Erro'); setLoading(false); });
      device.on('unregistered', () => setDeviceReady(false));
      device.on('incoming', (call: Call) => {
        callRef.current = call;
        setPhoneNumber(call.parameters?.From || 'Desconhecido');
        setStatus('incoming');
        call.on('disconnect', () => handleCallEnd());
        call.on('cancel', () => handleCallEnd());
        call.on('reject', () => handleCallEnd());
      });
      await device.register();
      deviceRef.current = device;
    } catch (err: any) {
      setError(err?.message || 'Erro ao conectar');
      initStartedRef.current = false; setLoading(false);
    }
  }, []);

  const handleCallEnd = () => {
    setStatus('idle'); setCallDuration(0); setMuted(false); callRef.current = null;
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    setTimeout(() => fetchCallLogs(), 2000);
  };

  const startTimer = () => {
    setCallDuration(0);
    timerRef.current = setInterval(() => setCallDuration((p) => p + 1), 1000);
  };

  const makeCall = async () => {
    if (!deviceRef.current || !phoneNumber.trim()) return;
    let number = phoneNumber.replace(/\D/g, '');
    if (!number.startsWith('55')) number = '55' + number;
    number = '+' + number;
    setStatus('connecting'); setError('');
    try {
      const call = await deviceRef.current.connect({ params: { To: number } });
      callRef.current = call;
      call.on('ringing', () => setStatus('ringing'));
      call.on('accept', () => { setStatus('in-call'); startTimer(); });
      call.on('disconnect', () => handleCallEnd());
      call.on('cancel', () => handleCallEnd());
      call.on('error', (err: any) => { setError(err.message || 'Erro'); handleCallEnd(); });
    } catch (err: any) { setError(err?.message || 'Erro'); setStatus('idle'); }
  };

  const acceptCall = () => { if (callRef.current) { callRef.current.accept(); setStatus('in-call'); startTimer(); } };
  const rejectCall = () => { if (callRef.current) { callRef.current.reject(); handleCallEnd(); } };
  const hangUp = () => {
    if (callRef.current) callRef.current.disconnect();
    if (deviceRef.current) deviceRef.current.disconnectAll();
    handleCallEnd();
  };
  const toggleMute = () => {
    if (callRef.current) { const m = !muted; callRef.current.mute(m); setMuted(m); }
  };

  const fmt = (s: number) => `${Math.floor(s/60).toString().padStart(2,'0')}:${(s%60).toString().padStart(2,'0')}`;

  const formatPhone = (phone: string) => {
    if (!phone) return '';
    const c = phone.replace(/\D/g, '');
    if (c.startsWith('55') && c.length >= 12) {
      const ddd = c.slice(2, 4), num = c.slice(4);
      if (num.length === 9) return `(${ddd}) ${num.slice(0,5)}-${num.slice(5)}`;
      if (num.length === 8) return `(${ddd}) ${num.slice(0,4)}-${num.slice(4)}`;
    }
    return phone;
  };

  const formatDate = (d: string) => {
    const date = new Date(d), now = new Date();
    const days = Math.floor((now.getTime() - date.getTime()) / 86400000);
    const time = date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    if (days === 0) return `Hoje ${time}`;
    if (days === 1) return `Ontem ${time}`;
    return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + ` ${time}`;
  };

  const statusLabel = (s: string) => {
    const map: Record<string, string> = { completed: 'Completada', 'no-answer': 'Sem resposta', busy: 'Ocupado', failed: 'Falhou', canceled: 'Cancelada', initiated: 'Iniciada', ringing: 'Chamando' };
    return map[s] || s;
  };

  const statusColor = (s: string) => {
    const map: Record<string, string> = { completed: 'text-emerald-600 bg-emerald-50', 'no-answer': 'text-amber-600 bg-amber-50', busy: 'text-orange-600 bg-orange-50', failed: 'text-red-600 bg-red-50', canceled: 'text-red-600 bg-red-50' };
    return map[s] || 'text-gray-500 bg-gray-50';
  };

  const dialPad = [
    { k: '1', s: '' }, { k: '2', s: 'ABC' }, { k: '3', s: 'DEF' },
    { k: '4', s: 'GHI' }, { k: '5', s: 'JKL' }, { k: '6', s: 'MNO' },
    { k: '7', s: 'PQRS' }, { k: '8', s: 'TUV' }, { k: '9', s: 'WXYZ' },
    { k: '*', s: '' }, { k: '0', s: '+' }, { k: '#', s: '' },
  ];

  const isActive = status === 'in-call' || status === 'connecting' || status === 'ringing';

  return (
    <div className="h-full flex bg-gray-50">

      {/* ===== DISCADOR ===== */}
      <div className="w-[400px] min-w-[400px] bg-[#0c1929] flex flex-col items-center justify-between py-8 relative overflow-hidden">

        {/* Glow decorativo */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] rounded-full opacity-[0.06] pointer-events-none"
          style={{ background: 'radial-gradient(ellipse, #2A658F 0%, transparent 70%)' }} />

        {/* Status */}
        <div className="relative z-10 flex items-center gap-2 px-4 py-2 rounded-full border"
          style={{
            backgroundColor: deviceReady ? 'rgba(16, 185, 129, 0.08)' : loading ? 'rgba(245, 158, 11, 0.08)' : 'rgba(239, 68, 68, 0.08)',
            borderColor: deviceReady ? 'rgba(16, 185, 129, 0.15)' : loading ? 'rgba(245, 158, 11, 0.15)' : 'rgba(239, 68, 68, 0.15)',
          }}>
          <span className={`w-2 h-2 rounded-full ${deviceReady ? 'bg-emerald-400' : loading ? 'bg-amber-400 animate-pulse' : 'bg-red-400'}`} />
          <span className={`text-xs font-medium ${deviceReady ? 'text-emerald-400' : loading ? 'text-amber-400' : 'text-red-400'}`}>
            {deviceReady ? 'Pronto' : loading ? 'Conectando...' : 'Offline'}
          </span>
        </div>

        {/* Centro */}
        <div className="relative z-10 w-full max-w-[300px] flex-1 flex flex-col items-center justify-center">

          {/* INCOMING */}
          {status === 'incoming' && (
            <div className="text-center">
              <div className="w-20 h-20 rounded-full bg-emerald-500/10 border-2 border-emerald-500/25 flex items-center justify-center mx-auto mb-5 animate-pulse">
                <PhoneIncoming className="w-9 h-9 text-emerald-400" />
              </div>
              <p className="text-white/40 text-xs uppercase tracking-[0.2em] mb-2">Chamada recebida</p>
              <p className="text-white text-2xl font-light mb-8">{formatPhone(phoneNumber)}</p>
              <div className="flex gap-4 justify-center">
                <button onClick={acceptCall} className="flex items-center gap-2 bg-emerald-500 hover:bg-emerald-400 text-white px-7 py-3 rounded-xl font-medium transition-all hover:scale-105">
                  <Phone className="w-5 h-5" /> Atender
                </button>
                <button onClick={rejectCall} className="flex items-center gap-2 bg-red-500 hover:bg-red-400 text-white px-7 py-3 rounded-xl font-medium transition-all hover:scale-105">
                  <PhoneOff className="w-5 h-5" /> Recusar
                </button>
              </div>
            </div>
          )}

          {/* IN CALL */}
          {isActive && (
            <div className="text-center">
              <div className={`w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-6 border-2 ${
                status === 'in-call' ? 'bg-emerald-500/10 border-emerald-500/25' : 'bg-[#2A658F]/10 border-[#2A658F]/25 animate-pulse'
              }`}>
                <Phone className={`w-10 h-10 ${status === 'in-call' ? 'text-emerald-400' : 'text-[#4d9fd4]'}`} />
              </div>
              <p className="text-white/30 text-xs uppercase tracking-[0.25em] mb-2">
                {status === 'connecting' ? 'Conectando' : status === 'ringing' ? 'Chamando' : 'Em chamada'}
              </p>
              <p className="text-white text-xl font-light mb-3">{formatPhone(phoneNumber)}</p>
              {status === 'in-call' && (
                <p className="text-[#4d9fd4] text-4xl font-light font-mono tracking-wider mb-8">{fmt(callDuration)}</p>
              )}
              <div className="flex gap-5 justify-center mt-4">
                <button onClick={toggleMute}
                  className={`w-14 h-14 rounded-2xl flex items-center justify-center transition-all ${
                    muted ? 'bg-amber-500/15 text-amber-400 border border-amber-500/25' : 'bg-white/5 text-white/50 border border-white/10 hover:bg-white/10'
                  }`}>
                  {muted ? <MicOff className="w-6 h-6" /> : <Mic className="w-6 h-6" />}
                </button>
                <button onClick={hangUp}
                  className="w-14 h-14 rounded-2xl bg-red-500 hover:bg-red-400 text-white flex items-center justify-center transition-all hover:scale-105 shadow-lg shadow-red-500/25">
                  <PhoneOff className="w-6 h-6" />
                </button>
              </div>
            </div>
          )}

          {/* IDLE - DISCADOR */}
          {status === 'idle' && (
            <>
              {/* Input */}
              <div className="w-full mb-5 relative">
                <input
                  type="tel"
                  placeholder="DDD + Número"
                  value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value)}
                  className="w-full bg-transparent border-b-2 border-white/10 focus:border-[#2A658F]/60 px-2 py-3 text-white text-center text-2xl font-light tracking-wider placeholder-white/15 focus:outline-none transition-colors"
                />
                {phoneNumber && (
                  <button onClick={() => setPhoneNumber(p => p.slice(0, -1))}
                    className="absolute right-1 top-1/2 -translate-y-1/2 text-white/20 hover:text-white/50 transition-colors p-1">
                    <Delete className="w-5 h-5" />
                  </button>
                )}
              </div>

              {error && !loading && (
                <p className="text-red-400 text-xs text-center mb-3 w-full">{error}</p>
              )}

              {/* Dial pad */}
              <div className="grid grid-cols-3 gap-2.5 w-full mb-5">
                {dialPad.map(({ k, s }) => (
                  <button key={k} onClick={() => setPhoneNumber(p => p + k)}
                    className="h-[58px] rounded-xl bg-white/[0.04] hover:bg-white/[0.09] border border-white/[0.06] hover:border-white/[0.12] flex flex-col items-center justify-center transition-all active:scale-95">
                    <span className="text-white text-xl font-light leading-none">{k}</span>
                    {s && <span className="text-white/20 text-[9px] tracking-[0.15em] mt-1">{s}</span>}
                  </button>
                ))}
              </div>

              {/* Call button */}
              <button onClick={makeCall} disabled={!phoneNumber.trim() || !deviceReady}
                className="w-full h-[52px] rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:bg-white/[0.04] disabled:text-white/15 disabled:border disabled:border-white/[0.06] text-white font-medium flex items-center justify-center gap-2.5 transition-all hover:shadow-lg hover:shadow-emerald-500/20 active:scale-[0.98] disabled:cursor-not-allowed disabled:hover:shadow-none">
                <Phone className="w-5 h-5" />
                Ligar
              </button>
            </>
          )}
        </div>

        {/* Footer */}
        <p className="relative z-10 text-white/[0.07] text-[10px] uppercase tracking-[0.35em]">CENAT Hub Voice</p>
      </div>

      {/* ===== HISTÓRICO ===== */}
      <div className="flex-1 flex flex-col min-h-0 bg-white">

        {/* Header */}
        <div className="flex items-center justify-between px-7 py-5 border-b border-gray-100">
          <div>
            <h2 className="text-gray-800 text-lg font-semibold">Histórico de Ligações</h2>
            <p className="text-gray-400 text-sm">{callLogs.length} ligações</p>
          </div>
          <button onClick={() => { setLoadingLogs(true); fetchCallLogs(); }}
            className="p-2.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors">
            <RefreshCw className={`w-4 h-4 ${loadingLogs ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {/* Lista */}
        <div className="flex-1 overflow-y-auto">
          {loadingLogs ? (
            <div className="flex items-center justify-center h-40">
              <div className="w-6 h-6 border-2 border-gray-200 border-t-[#2A658F] rounded-full animate-spin" />
            </div>
          ) : callLogs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-gray-300">
              <Phone className="w-12 h-12 mb-3" />
              <p className="text-sm">Nenhuma ligação registrada</p>
              <p className="text-xs text-gray-300 mt-1">Faça sua primeira ligação usando o discador</p>
            </div>
          ) : (
            <div>
              {callLogs.map((log, i) => {
                const isOutbound = log.direction === 'outbound';
                const number = isOutbound ? log.to_number : log.from_number;
                const completed = log.status === 'completed';

                return (
                  <div key={log.id}
                    className="flex items-center gap-4 px-7 py-4 hover:bg-gray-50/80 transition-colors cursor-pointer group border-b border-gray-50"
                    onClick={() => setPhoneNumber(number.replace('+55', ''))}
                  >
                    {/* Ícone */}
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 ${
                      completed
                        ? isOutbound ? 'bg-blue-50 text-[#2A658F]' : 'bg-emerald-50 text-emerald-600'
                        : 'bg-red-50 text-red-500'
                    }`}>
                      {completed
                        ? isOutbound ? <ArrowUpRight className="w-5 h-5" /> : <ArrowDownLeft className="w-5 h-5" />
                        : <PhoneMissed className="w-5 h-5" />
                      }
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2.5">
                        <p className="text-gray-800 text-sm font-medium truncate">
                          {log.contact_name || formatPhone(number)}
                        </p>
                        <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${statusColor(log.status)}`}>
                          {statusLabel(log.status)}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-gray-400 text-xs">{isOutbound ? 'Saída' : 'Entrada'}</span>
                        {log.user_name && (
                          <span className="text-gray-300 text-xs flex items-center gap-1">
                            <User className="w-3 h-3" /> {log.user_name}
                          </span>
                        )}
                        {log.duration > 0 && (
                          <span className="text-gray-300 text-xs flex items-center gap-1">
                            <Clock className="w-3 h-3" /> {fmt(log.duration)}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Data + ações */}
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-gray-300 text-xs">{formatDate(log.created_at)}</span>

                      {log.drive_file_url && (
                        <a href={log.drive_file_url} target="_blank" rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-300 hover:text-[#2A658F] transition-colors opacity-0 group-hover:opacity-100">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}

                      {/* Botão de religar */}
                      <button
                        onClick={(e) => { e.stopPropagation(); setPhoneNumber(number.replace('+55', '')); }}
                        className="p-1.5 rounded-lg hover:bg-emerald-50 text-gray-300 hover:text-emerald-600 transition-colors opacity-0 group-hover:opacity-100">
                        <Phone className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
