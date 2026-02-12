'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Phone, PhoneOff, PhoneIncoming, PhoneOutgoing, PhoneMissed,
  Mic, MicOff, Delete, Clock, User, ExternalLink, Play, ArrowDownLeft, ArrowUpRight,
  RefreshCw
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
  // Dialer state
  const [status, setStatus] = useState<CallStatus>('idle');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [callDuration, setCallDuration] = useState(0);
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState('');
  const [deviceReady, setDeviceReady] = useState(false);
  const [loading, setLoading] = useState(false);

  // History state
  const [callLogs, setCallLogs] = useState<CallLogEntry[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(true);

  // Refs
  const deviceRef = useRef<Device | null>(null);
  const callRef = useRef<Call | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const initStartedRef = useRef(false);

  // Init Twilio on page load
  useEffect(() => {
    initDevice();
    fetchCallLogs();
    return () => {
      if (deviceRef.current) {
        try { deviceRef.current.destroy(); } catch (e) {}
      }
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
      if (!token) {
        setError('Faça login primeiro');
        initStartedRef.current = false;
        setLoading(false);
        return;
      }

      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://hub.cenatdata.online/api';
      const res = await fetch(`${API_URL}/twilio/token`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) throw new Error('Erro ao obter token de voz');
      const data = await res.json();

      const device = new Device(data.token, {
        codecPreferences: [Call.Codec.Opus, Call.Codec.PCMU],
        closeProtection: true,
        logLevel: 1,
      });

      device.on('registered', () => {
        setDeviceReady(true);
        setLoading(false);
        setError('');
      });

      device.on('error', (err: any) => {
        setError(err.message || 'Erro no dispositivo');
        setLoading(false);
      });

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
      initStartedRef.current = false;
      setLoading(false);
    }
  }, []);

  const handleCallEnd = () => {
    setStatus('idle');
    setCallDuration(0);
    setMuted(false);
    callRef.current = null;
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    // Refresh logs after call ends
    setTimeout(() => fetchCallLogs(), 2000);
  };

  const startTimer = () => {
    setCallDuration(0);
    timerRef.current = setInterval(() => {
      setCallDuration((prev) => prev + 1);
    }, 1000);
  };

  const makeCall = async () => {
    if (!deviceRef.current || !phoneNumber.trim()) return;

    let number = phoneNumber.replace(/\D/g, '');
    if (!number.startsWith('55')) number = '55' + number;
    number = '+' + number;

    setStatus('connecting');
    setError('');

    try {
      const call = await deviceRef.current.connect({ params: { To: number } });
      callRef.current = call;

      call.on('ringing', () => setStatus('ringing'));
      call.on('accept', () => { setStatus('in-call'); startTimer(); });
      call.on('disconnect', () => handleCallEnd());
      call.on('cancel', () => handleCallEnd());
      call.on('error', (err: any) => { setError(err.message || 'Erro'); handleCallEnd(); });
    } catch (err: any) {
      setError(err?.message || 'Erro ao iniciar chamada');
      setStatus('idle');
    }
  };

  const acceptCall = () => {
    if (callRef.current) {
      callRef.current.accept();
      setStatus('in-call');
      startTimer();
    }
  };

  const rejectCall = () => {
    if (callRef.current) {
      callRef.current.reject();
      handleCallEnd();
    }
  };

  const hangUp = () => {
    if (callRef.current) callRef.current.disconnect();
    if (deviceRef.current) deviceRef.current.disconnectAll();
    handleCallEnd();
  };

  const toggleMute = () => {
    if (callRef.current) {
      const newMuted = !muted;
      callRef.current.mute(newMuted);
      setMuted(newMuted);
    }
  };

  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const formatPhone = (phone: string) => {
    if (!phone) return '';
    const clean = phone.replace(/\D/g, '');
    if (clean.startsWith('55') && clean.length >= 12) {
      const ddd = clean.slice(2, 4);
      const num = clean.slice(4);
      if (num.length === 9) return `(${ddd}) ${num.slice(0, 5)}-${num.slice(5)}`;
      if (num.length === 8) return `(${ddd}) ${num.slice(0, 4)}-${num.slice(4)}`;
    }
    return phone;
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / 86400000);

    if (days === 0) {
      return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    } else if (days === 1) {
      return 'Ontem ' + date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    } else if (days < 7) {
      return date.toLocaleDateString('pt-BR', { weekday: 'short' }) + ' ' +
        date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    }
    return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + ' ' +
      date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  };

  const getStatusColor = (s: string) => {
    switch (s) {
      case 'completed': return 'text-emerald-400';
      case 'no-answer': return 'text-amber-400';
      case 'busy': return 'text-orange-400';
      case 'failed': case 'canceled': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  const getStatusLabel = (s: string) => {
    switch (s) {
      case 'completed': return 'Completada';
      case 'no-answer': return 'Sem resposta';
      case 'busy': return 'Ocupado';
      case 'failed': return 'Falhou';
      case 'canceled': return 'Cancelada';
      case 'initiated': return 'Iniciada';
      case 'ringing': return 'Chamando';
      default: return s;
    }
  };

  const dialPad = [
    { key: '1', sub: '' },
    { key: '2', sub: 'ABC' },
    { key: '3', sub: 'DEF' },
    { key: '4', sub: 'GHI' },
    { key: '5', sub: 'JKL' },
    { key: '6', sub: 'MNO' },
    { key: '7', sub: 'PQRS' },
    { key: '8', sub: 'TUV' },
    { key: '9', sub: 'WXYZ' },
    { key: '*', sub: '' },
    { key: '0', sub: '+' },
    { key: '#', sub: '' },
  ];

  const isInCall = status === 'in-call' || status === 'connecting' || status === 'ringing';
  const isIncoming = status === 'incoming';

  return (
    <div className="h-full flex gap-0">

      {/* ===== LADO ESQUERDO: DISCADOR ===== */}
      <div className="w-[420px] min-w-[420px] flex flex-col items-center justify-center relative"
        style={{
          background: 'linear-gradient(180deg, #0a1628 0%, #0f1f3d 50%, #0a1628 100%)',
        }}
      >
        {/* Efeito de glow */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full opacity-[0.04]"
            style={{ background: 'radial-gradient(circle, #4d9fd4 0%, transparent 70%)' }}
          />
        </div>

        {/* Status badge */}
        <div className="relative z-10 mb-6">
          <div className={`inline-flex items-center gap-2 px-4 py-1.5 rounded-full text-xs font-medium tracking-wide ${
            deviceReady
              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
              : loading
                ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                : 'bg-red-500/10 text-red-400 border border-red-500/20'
          }`}>
            <span className={`w-2 h-2 rounded-full ${
              deviceReady ? 'bg-emerald-400 animate-pulse' : loading ? 'bg-amber-400 animate-pulse' : 'bg-red-400'
            }`} />
            {deviceReady ? 'Conectado' : loading ? 'Conectando...' : error || 'Desconectado'}
          </div>
        </div>

        {/* Incoming call */}
        {isIncoming && (
          <div className="relative z-10 text-center mb-8">
            <div className="w-20 h-20 rounded-full bg-emerald-500/10 border-2 border-emerald-500/30 flex items-center justify-center mx-auto mb-4 animate-pulse">
              <PhoneIncoming className="w-10 h-10 text-emerald-400" />
            </div>
            <p className="text-white/50 text-sm uppercase tracking-[0.2em] mb-1">Chamada recebida</p>
            <p className="text-white text-2xl font-light tracking-wide">{formatPhone(phoneNumber)}</p>
            <div className="flex gap-4 mt-6 justify-center">
              <button onClick={acceptCall}
                className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white px-8 py-3 rounded-2xl transition-all duration-200 hover:scale-105 shadow-lg shadow-emerald-600/20">
                <Phone className="w-5 h-5" /> Atender
              </button>
              <button onClick={rejectCall}
                className="flex items-center gap-2 bg-red-600 hover:bg-red-500 text-white px-8 py-3 rounded-2xl transition-all duration-200 hover:scale-105 shadow-lg shadow-red-600/20">
                <PhoneOff className="w-5 h-5" /> Recusar
              </button>
            </div>
          </div>
        )}

        {/* In call */}
        {isInCall && (
          <div className="relative z-10 text-center mb-8">
            <div className={`w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-5 ${
              status === 'in-call'
                ? 'bg-emerald-500/10 border-2 border-emerald-500/30'
                : 'bg-[#2A658F]/10 border-2 border-[#2A658F]/30 animate-pulse'
            }`}>
              <Phone className={`w-10 h-10 ${status === 'in-call' ? 'text-emerald-400' : 'text-[#4d9fd4]'}`} />
            </div>
            <p className="text-white/50 text-xs uppercase tracking-[0.25em] mb-1">
              {status === 'connecting' ? 'Conectando' : status === 'ringing' ? 'Chamando' : 'Em chamada'}
            </p>
            <p className="text-white text-xl font-light tracking-wide mb-2">{formatPhone(phoneNumber)}</p>
            {status === 'in-call' && (
              <p className="text-[#4d9fd4] text-4xl font-extralight font-mono tracking-wider">
                {formatDuration(callDuration)}
              </p>
            )}
            <div className="flex gap-4 mt-8 justify-center">
              <button onClick={toggleMute}
                className={`w-14 h-14 rounded-2xl flex items-center justify-center transition-all duration-200 ${
                  muted
                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                    : 'bg-white/5 text-white/60 border border-white/10 hover:bg-white/10 hover:text-white'
                }`}>
                {muted ? <MicOff className="w-6 h-6" /> : <Mic className="w-6 h-6" />}
              </button>
              <button onClick={hangUp}
                className="w-14 h-14 rounded-2xl bg-red-600 hover:bg-red-500 text-white flex items-center justify-center transition-all duration-200 hover:scale-105 shadow-lg shadow-red-600/30">
                <PhoneOff className="w-6 h-6" />
              </button>
            </div>
          </div>
        )}

        {/* Dialer (when idle) */}
        {!isInCall && !isIncoming && (
          <div className="relative z-10 w-full max-w-[320px] px-4">
            {/* Phone input */}
            <div className="relative mb-6">
              <input
                type="tel"
                placeholder="DDD + Número"
                value={phoneNumber}
                onChange={(e) => setPhoneNumber(e.target.value)}
                className="w-full bg-transparent border-b-2 border-white/10 focus:border-[#4d9fd4]/50 px-2 py-4 text-white text-center text-2xl font-light tracking-[0.1em] placeholder-white/20 focus:outline-none transition-colors duration-300"
              />
              {phoneNumber && (
                <button
                  onClick={() => setPhoneNumber(prev => prev.slice(0, -1))}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors"
                >
                  <Delete className="w-5 h-5" />
                </button>
              )}
            </div>

            {/* Error */}
            {error && !loading && (
              <p className="text-red-400 text-xs text-center mb-4 bg-red-400/5 px-3 py-2 rounded-xl border border-red-400/10">
                {error}
              </p>
            )}

            {/* Dial pad */}
            <div className="grid grid-cols-3 gap-3 mb-6">
              {dialPad.map(({ key, sub }) => (
                <button
                  key={key}
                  onClick={() => setPhoneNumber(prev => prev + key)}
                  className="group relative h-16 rounded-2xl bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.04] hover:border-white/[0.1] flex flex-col items-center justify-center transition-all duration-200 active:scale-95"
                >
                  <span className="text-white text-xl font-light">{key}</span>
                  {sub && (
                    <span className="text-white/25 text-[10px] tracking-[0.15em] mt-0.5">{sub}</span>
                  )}
                </button>
              ))}
            </div>

            {/* Call button */}
            <button
              onClick={makeCall}
              disabled={!phoneNumber.trim() || !deviceReady}
              className="w-full h-14 rounded-2xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-white/5 disabled:text-white/20 disabled:cursor-not-allowed text-white font-medium flex items-center justify-center gap-3 transition-all duration-300 hover:scale-[1.02] hover:shadow-lg hover:shadow-emerald-600/20 active:scale-[0.98]"
            >
              <Phone className="w-5 h-5" />
              <span className="tracking-wide">Ligar</span>
            </button>
          </div>
        )}

        {/* CENAT branding */}
        <div className="absolute bottom-6 left-0 right-0 text-center">
          <p className="text-white/10 text-[10px] uppercase tracking-[0.3em]">CENAT Hub Voice</p>
        </div>
      </div>

      {/* ===== LADO DIREITO: HISTÓRICO ===== */}
      <div className="flex-1 bg-[#0B1120] flex flex-col min-h-0">

        {/* Header */}
        <div className="flex items-center justify-between px-8 py-5 border-b border-white/[0.04]">
          <div>
            <h2 className="text-white text-lg font-medium tracking-wide">Histórico de ligações</h2>
            <p className="text-white/30 text-sm mt-0.5">{callLogs.length} ligações registradas</p>
          </div>
          <button onClick={() => { setLoadingLogs(true); fetchCallLogs(); }}
            className="p-2.5 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.05] text-white/40 hover:text-white/70 transition-all duration-200">
            <RefreshCw className={`w-4 h-4 ${loadingLogs ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto custom-scrollbar">
          {loadingLogs ? (
            <div className="flex items-center justify-center h-40">
              <div className="w-6 h-6 border-2 border-white/10 border-t-[#4d9fd4] rounded-full animate-spin" />
            </div>
          ) : callLogs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-white/20">
              <Phone className="w-12 h-12 mb-3 opacity-30" />
              <p className="text-sm">Nenhuma ligação registrada</p>
            </div>
          ) : (
            <div className="divide-y divide-white/[0.03]">
              {callLogs.map((log) => (
                <div key={log.id}
                  className="group flex items-center gap-4 px-8 py-4 hover:bg-white/[0.02] transition-colors duration-150 cursor-pointer"
                  onClick={() => {
                    const num = log.direction === 'outbound' ? log.to_number : log.from_number;
                    setPhoneNumber(num.replace('+55', ''));
                  }}
                >
                  {/* Direction icon */}
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${
                    log.status === 'completed'
                      ? log.direction === 'outbound'
                        ? 'bg-[#2A658F]/10 text-[#4d9fd4]'
                        : 'bg-emerald-500/10 text-emerald-400'
                      : 'bg-red-500/10 text-red-400'
                  }`}>
                    {log.status === 'completed' ? (
                      log.direction === 'outbound'
                        ? <ArrowUpRight className="w-5 h-5" />
                        : <ArrowDownLeft className="w-5 h-5" />
                    ) : (
                      <PhoneMissed className="w-5 h-5" />
                    )}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-white text-sm font-medium truncate">
                        {log.contact_name || formatPhone(
                          log.direction === 'outbound' ? log.to_number : log.from_number
                        )}
                      </p>
                      <span className={`text-[10px] uppercase tracking-wider ${getStatusColor(log.status)}`}>
                        {getStatusLabel(log.status)}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-white/25 text-xs">
                        {log.direction === 'outbound' ? 'Saída' : 'Entrada'}
                      </span>
                      {log.user_name && (
                        <span className="text-white/20 text-xs flex items-center gap-1">
                          <User className="w-3 h-3" /> {log.user_name}
                        </span>
                      )}
                      {log.duration > 0 && (
                        <span className="text-white/20 text-xs flex items-center gap-1">
                          <Clock className="w-3 h-3" /> {formatDuration(log.duration)}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Date + actions */}
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span className="text-white/20 text-xs">{formatDate(log.created_at)}</span>

                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      {log.recording_url && (
                        <button
                          onClick={(e) => { e.stopPropagation(); }}
                          className="p-1.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] text-white/30 hover:text-white/70 transition-all"
                        >
                          <Play className="w-3.5 h-3.5" />
                        </button>
                      )}
                      {log.drive_file_url && (
                        <a
                          href={log.drive_file_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="p-1.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] text-white/30 hover:text-white/70 transition-all"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.06);
          border-radius: 2px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(255, 255, 255, 0.12);
        }
      `}</style>
    </div>
  );
}
