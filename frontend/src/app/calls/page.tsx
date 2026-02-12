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

  // --- UX: Máscara de Telefone ---
  const applyMask = (value: string) => {
    const numbers = value.replace(/\D/g, '');
    if (numbers.length <= 11) {
      return numbers
        .replace(/^(\d{2})(\d)/g, '($1) $2')
        .replace(/(\d{5})(\d)/, '$1-$2')
        .replace(/(-\d{4})\d+?$/, '$1');
    }
    return numbers.slice(0, 11);
  };

  const handlePhoneChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setPhoneNumber(applyMask(e.target.value));
  };

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

  // --- UX: Atalhos de Teclado ---
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (status !== 'idle') return;
      if (/[0-9*#]/.test(e.key) && document.activeElement?.tagName !== 'INPUT') {
        setPhoneNumber(prev => applyMask(prev + e.key));
      }
      if (e.key === 'Backspace' && document.activeElement?.tagName !== 'INPUT') {
        setPhoneNumber(prev => applyMask(prev.slice(0, -1)));
      }
      if (e.key === 'Enter' && phoneNumber.replace(/\D/g, '').length >= 10 && deviceReady) {
        makeCall();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [phoneNumber, deviceReady, status]);

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
        setPhoneNumber(applyMask(call.parameters?.From || ''));
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
    if (clean.length >= 10) {
      const ddd = clean.startsWith('55') ? clean.slice(2, 4) : clean.slice(0, 2);
      const num = clean.startsWith('55') ? clean.slice(4) : clean.slice(2);
      return `(${ddd}) ${num.length === 9 ? num.slice(0, 5) : num.slice(0, 4)}-${num.slice(-4)}`;
    }
    return phone;
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / 86400000);
    if (days === 0) return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    if (days === 1) return 'Ontem ' + date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    return date.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
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
      default: return s;
    }
  };

  const dialPad = [
    { key: '1', sub: '' }, { key: '2', sub: 'ABC' }, { key: '3', sub: 'DEF' },
    { key: '4', sub: 'GHI' }, { key: '5', sub: 'JKL' }, { key: '6', sub: 'MNO' },
    { key: '7', sub: 'PQRS' }, { key: '8', sub: 'TUV' }, { key: '9', sub: 'WXYZ' },
    { key: '*', sub: '' }, { key: '0', sub: '+' }, { key: '#', sub: '' },
  ];

  const isInCall = status === 'in-call' || status === 'connecting' || status === 'ringing';
  const isIncoming = status === 'incoming';

  return (
    <div className="h-full flex gap-0 bg-[#070c17] text-slate-200">
      
      {/* ===== LADO ESQUERDO: DISCADOR ===== */}
      <div className="w-[420px] min-w-[420px] flex flex-col items-center justify-center relative border-r border-white/5"
        style={{ background: 'linear-gradient(180deg, #0a1628 0%, #0f1f3d 50%, #0a1628 100%)' }}
      >
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full opacity-[0.04]"
            style={{ background: 'radial-gradient(circle, #4d9fd4 0%, transparent 70%)' }}
          />
        </div>

        {/* Status Badge */}
        <div className="relative z-10 mb-8">
          <div className={`flex items-center gap-2 px-3 py-1 rounded-full text-[10px] uppercase font-bold tracking-widest border transition-all duration-500 ${
            deviceReady ? 'bg-emerald-500/5 text-emerald-400 border-emerald-500/20' : 'bg-red-500/5 text-red-400 border-red-500/20'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${deviceReady ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
            {deviceReady ? 'Conectado' : 'Offline'}
          </div>
        </div>

        <div className="h-64 flex items-center justify-center w-full relative z-10">
          {isIncoming && (
            <div className="text-center animate-in fade-in zoom-in duration-300">
              <div className="w-20 h-20 rounded-full bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center mx-auto mb-4 animate-bounce">
                <PhoneIncoming className="w-8 h-8 text-emerald-400" />
              </div>
              <p className="text-white text-2xl font-light mb-6">{phoneNumber}</p>
              <div className="flex gap-4 justify-center">
                <button onClick={acceptCall} className="bg-emerald-600 hover:bg-emerald-500 p-5 rounded-2xl transition-transform active:scale-90 shadow-lg shadow-emerald-900/40"><Phone /></button>
                <button onClick={rejectCall} className="bg-red-600 hover:bg-red-500 p-5 rounded-2xl transition-transform active:scale-90 shadow-lg shadow-red-900/40"><PhoneOff /></button>
              </div>
            </div>
          )}

          {isInCall && (
            <div className="text-center animate-in fade-in slide-in-from-bottom-4 duration-500">
              <p className="text-[#4d9fd4] text-5xl font-extralight font-mono mb-2 tracking-tighter">
                {formatDuration(callDuration)}
              </p>
              <p className="text-white/40 text-xs mb-8 tracking-[0.3em] uppercase">{status === 'in-call' ? 'Em chamada' : 'Conectando...'}</p>
              <div className="flex gap-4 justify-center">
                <button onClick={toggleMute} className={`p-4 rounded-2xl border transition-all ${muted ? 'bg-amber-500/20 border-amber-500/40 text-amber-400' : 'bg-white/5 border-white/10 text-white/40'}`}>
                  {muted ? <MicOff /> : <Mic />}
                </button>
                <button onClick={hangUp} className="bg-red-600 hover:bg-red-500 p-4 rounded-2xl shadow-xl shadow-red-900/40 transition-transform active:scale-90">
                  <PhoneOff />
                </button>
              </div>
            </div>
          )}

          {!isInCall && !isIncoming && (
            <div className="w-full max-w-[300px] px-2 animate-in fade-in duration-500">
              <div className="relative mb-6">
                <input
                  type="tel"
                  placeholder="(00) 00000-0000"
                  value={phoneNumber}
                  onChange={handlePhoneChange}
                  className="w-full bg-transparent text-white text-center text-3xl font-light tracking-tighter placeholder-white/10 focus:outline-none"
                />
                {phoneNumber && (
                  <button onClick={() => setPhoneNumber('')} className="absolute -right-4 top-1/2 -translate-y-1/2 text-white/10 hover:text-white/40 transition-colors">
                    <Delete size={18} />
                  </button>
                )}
              </div>
              <div className="grid grid-cols-3 gap-3">
                {dialPad.map(({ key, sub }) => (
                  <button
                    key={key}
                    onClick={() => setPhoneNumber(prev => applyMask(prev + key))}
                    className="h-14 rounded-xl bg-white/[0.02] border border-white/[0.05] hover:bg-white/[0.06] hover:border-white/20 transition-all active:bg-white/10 flex flex-col items-center justify-center group"
                  >
                    <span className="text-xl font-light">{key}</span>
                    <span className="text-[8px] text-white/20 tracking-widest uppercase">{sub}</span>
                  </button>
                ))}
              </div>
              <button
                onClick={makeCall}
                disabled={!phoneNumber.trim() || !deviceReady}
                className="w-full mt-6 h-14 rounded-2xl bg-[#2A658F] hover:bg-[#347ab0] disabled:opacity-20 transition-all flex items-center justify-center gap-3 font-medium shadow-lg shadow-blue-900/20"
              >
                <Phone className="w-5 h-5" /> Ligar
              </button>
            </div>
          )}
        </div>

        <div className="absolute bottom-8 opacity-20 cursor-default">
          <p className="text-[10px] tracking-[0.4em] uppercase font-bold">CENAT VOICE HUB</p>
        </div>
      </div>

      {/* ===== LADO DIREITO: HISTÓRICO ===== */}
      <div className="flex-1 bg-[#070c17] flex flex-col min-h-0">
        <div className="px-8 py-6 flex items-center justify-between border-b border-white/5">
          <h2 className="text-xl font-light tracking-tight text-white/90">Histórico de Ligações</h2>
          <button onClick={() => { setLoadingLogs(true); fetchCallLogs(); }} className="p-2 rounded-lg hover:bg-white/5 transition-colors text-white/20 hover:text-white">
            <RefreshCw className={`w-4 h-4 ${loadingLogs ? 'animate-spin' : ''}`} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar px-6 py-2">
          {loadingLogs ? (
            <div className="flex items-center justify-center h-40 opacity-20"><RefreshCw className="animate-spin" /></div>
          ) : callLogs.map((log) => (
            <div 
              key={log.id} 
              className="group flex items-center gap-4 p-4 my-1 rounded-2xl hover:bg-white/[0.03] transition-all cursor-pointer border border-transparent hover:border-white/5"
              onClick={() => setPhoneNumber(applyMask(log.direction === 'outbound' ? log.to_number : log.from_number))}
            >
              <div className={`w-11 h-11 rounded-full flex items-center justify-center ${
                log.status === 'completed' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-red-500/10 text-red-500'
              }`}>
                {log.direction === 'outbound' ? <ArrowUpRight size={18}/> : <ArrowDownLeft size={18}/>}
              </div>
              
              <div className="flex-1">
                <p className="text-sm font-medium text-white/80">
                  {log.contact_name || formatPhone(log.direction === 'outbound' ? log.to_number : log.from_number)}
                </p>
                <div className="flex items-center gap-2 text-[11px] text-white/30 mt-0.5">
                  <span className={getStatusColor(log.status)}>{getStatusLabel(log.status)}</span>
                  <span>•</span>
                  <span>{formatDate(log.created_at)}</span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                 <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
                    {log.recording_url && (
                      <button onClick={(e) => e.stopPropagation()} className="p-2 text-white/20 hover:text-white"><Play size={14}/></button>
                    )}
                    <button className="p-2.5 bg-[#2A658F]/20 text-[#4d9fd4] rounded-xl hover:bg-[#2A658F]/40 transition-colors">
                      <Phone size={14} />
                    </button>
                 </div>
                 <span className="text-[11px] text-white/10 tabular-nums">{log.duration > 0 ? formatDuration(log.duration) : '--:--'}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar { width: 4px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.05); border-radius: 10px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.1); }
      `}</style>
    </div>
  );
}