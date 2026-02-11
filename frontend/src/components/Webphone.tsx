'use client';

import { useState, useEffect, useRef } from 'react';
import { Phone, PhoneOff, PhoneIncoming, X, Mic, MicOff } from 'lucide-react';
import api from '@/lib/api';

declare global {
  interface Window {
    Twilio: any;
  }
}

type CallStatus = 'idle' | 'connecting' | 'ringing' | 'in-call' | 'incoming';

export default function Webphone() {
  const [status, setStatus] = useState<CallStatus>('idle');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [callDuration, setCallDuration] = useState(0);
  const [muted, setMuted] = useState(false);
  const [showDialer, setShowDialer] = useState(false);
  const [incomingFrom, setIncomingFrom] = useState('');
  const [error, setError] = useState('');

  const [deviceReady, setDeviceReady] = useState(false);

  const deviceRef = useRef<any>(null);
  const connectionRef = useRef<any>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const sdkLoadedRef = useRef(false);

  // Carregar Twilio SDK
  useEffect(() => {
    if (sdkLoadedRef.current) return;

    const script = document.createElement('script');
    script.src = 'https://sdk.twilio.com/js/client/v1.14/twilio.min.js';
    script.async = true;
    script.onload = () => {
      sdkLoadedRef.current = true;
      initDevice();
    };
    document.head.appendChild(script);

    return () => {
      try {
        if (deviceRef.current) deviceRef.current.destroy();
      } catch {}
      if (timerRef.current) clearInterval(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Escutar evento de ligação vindo da página de conversas
  useEffect(() => {
    const handler = (e: any) => {
      const phone = e.detail?.phone || '';
      if (phone) {
        setPhoneNumber(phone);
        setShowDialer(true);
      }
    };
    window.addEventListener('cenat-call', handler);
    return () => window.removeEventListener('cenat-call', handler);
  }, []);

  const initDevice = async () => {
    try {
      const token = localStorage.getItem('token');
      if (!token) return;

      const res = await api.get('/twilio/token', {
        headers: { Authorization: `Bearer ${token}` },
      });

      const device = new window.Twilio.Device(res.data.token, {
        codecPreferences: ['opus', 'pcmu'],
        debug: false,
      });

      device.on('ready', () => {
        console.log('📞 Twilio Device pronto');
        setDeviceReady(true);
      });

      device.on('error', (err: any) => {
        console.error('📞 Twilio Error:', err);
        setError(err.message || 'Erro no dispositivo');
        setStatus('idle');
        setDeviceReady(false);
      });

      device.on('incoming', (conn: any) => {
        connectionRef.current = conn;
        setIncomingFrom(conn.parameters.From || 'Desconhecido');
        setStatus('incoming');

        conn.on('disconnect', () => {
          handleCallEnd();
        });
      });

      device.on('disconnect', () => {
        handleCallEnd();
      });

      deviceRef.current = device;
    } catch (err) {
      console.error('Erro ao inicializar Twilio:', err);
      setDeviceReady(false);
    }
  };

  const handleCallEnd = () => {
    setStatus('idle');
    setCallDuration(0);
    setMuted(false);
    connectionRef.current = null;
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const startTimer = () => {
    setCallDuration(0);
    timerRef.current = setInterval(() => {
      setCallDuration((prev) => prev + 1);
    }, 1000);
  };

  const makeCall = () => {
    if (!deviceRef.current || !phoneNumber.trim()) return;

    let number = phoneNumber.replace(/\D/g, '');
    if (!number.startsWith('55')) number = '55' + number;
    number = '+' + number;

    setStatus('connecting');
    setError('');

    const conn = deviceRef.current.connect({ To: number });
    connectionRef.current = conn;

    conn.on('ringing', () => setStatus('ringing'));
    conn.on('accept', () => {
      setStatus('in-call');
      startTimer();
    });
    conn.on('disconnect', () => handleCallEnd());
    conn.on('error', (err: any) => {
      setError(err.message || 'Erro na chamada');
      handleCallEnd();
    });
  };

  const acceptCall = () => {
    if (connectionRef.current) {
      connectionRef.current.accept();
      setStatus('in-call');
      startTimer();
    }
  };

  const rejectCall = () => {
    if (connectionRef.current) {
      connectionRef.current.reject();
      handleCallEnd();
    }
  };

  const hangUp = () => {
    if (connectionRef.current) {
      connectionRef.current.disconnect();
    }
    if (deviceRef.current) {
      deviceRef.current.disconnectAll();
    }
    handleCallEnd();
  };

  const toggleMute = () => {
    if (connectionRef.current) {
      const newMuted = !muted;
      connectionRef.current.mute(newMuted);
      setMuted(newMuted);
    }
  };

  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const dialPad = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#'];

  // Chamada recebida - popup
  if (status === 'incoming') {
    return (
      <div className="fixed bottom-6 right-6 z-50 bg-[#0f1b2d] border border-green-500/30 rounded-2xl p-6 shadow-2xl w-[300px] animate-pulse">
        <div className="text-center">
          <PhoneIncoming className="w-10 h-10 text-green-400 mx-auto mb-3 animate-bounce" />
          <p className="text-white font-semibold text-lg">Chamada recebida</p>
          <p className="text-gray-400 text-sm mt-1">{incomingFrom}</p>
          <div className="flex gap-3 mt-5 justify-center">
            <button
              onClick={acceptCall}
              className="flex items-center gap-2 bg-green-600 hover:bg-green-700 text-white px-5 py-2.5 rounded-xl transition-colors"
            >
              <Phone className="w-4 h-4" /> Atender
            </button>
            <button
              onClick={rejectCall}
              className="flex items-center gap-2 bg-red-600 hover:bg-red-700 text-white px-5 py-2.5 rounded-xl transition-colors"
            >
              <PhoneOff className="w-4 h-4" /> Recusar
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Em chamada - barra flutuante
  if (status === 'in-call' || status === 'connecting' || status === 'ringing') {
    return (
      <div className="fixed bottom-6 right-6 z-50 bg-[#0f1b2d] border border-[#2A658F]/30 rounded-2xl p-4 shadow-2xl w-[280px]">
        <div className="text-center">
          <p className="text-gray-400 text-xs uppercase tracking-wider mb-1">
            {status === 'connecting' ? 'Conectando...' : status === 'ringing' ? 'Chamando...' : 'Em chamada'}
          </p>
          <p className="text-white font-semibold">{phoneNumber}</p>
          {status === 'in-call' && (
            <p className="text-[#4d9fd4] text-2xl font-mono mt-2">{formatDuration(callDuration)}</p>
          )}
          <div className="flex gap-3 mt-4 justify-center">
            <button
              onClick={toggleMute}
              className={`p-3 rounded-xl transition-colors ${
                muted ? 'bg-yellow-600/20 text-yellow-400' : 'bg-white/5 text-gray-400 hover:text-white'
              }`}
            >
              {muted ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
            </button>
            <button
              onClick={hangUp}
              className="p-3 rounded-xl bg-red-600 hover:bg-red-700 text-white transition-colors"
            >
              <PhoneOff className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Botão flutuante + discador
  return (
    <>
      <button
        onClick={() => setShowDialer(!showDialer)}
        disabled={!deviceReady && !showDialer}
        className={`fixed bottom-6 right-6 z-50 w-14 h-14 text-white rounded-full shadow-lg flex items-center justify-center transition-all duration-200 hover:scale-105 ${
          deviceReady ? 'bg-[#2A658F] hover:bg-[#347aab]' : 'bg-gray-400'
        }`}
      >
        {showDialer ? <X className="w-6 h-6" /> : <Phone className="w-6 h-6" />}
        {/* ✅ Sem comparação com "in-call" aqui, porque nesse return status é sempre "idle" */}
        <span
          className={`absolute top-0 right-0 w-3.5 h-3.5 rounded-full border-2 border-white ${
            deviceReady ? 'bg-green-500' : 'bg-gray-400'
          }`}
        />
      </button>

      {showDialer && (
        <div className="fixed bottom-24 right-6 z-50 bg-[#0f1b2d] border border-white/10 rounded-2xl p-5 shadow-2xl w-[300px]">
          <p className="text-white font-semibold text-sm mb-3">Discador</p>

          {error && (
            <p className="text-red-400 text-xs mb-2 bg-red-400/10 px-3 py-1.5 rounded-lg">{error}</p>
          )}

          <input
            type="tel"
            placeholder="(00) 00000-0000"
            value={phoneNumber}
            onChange={(e) => setPhoneNumber(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white text-center text-lg font-mono placeholder-gray-600 focus:outline-none focus:border-[#2A658F]/50 mb-3"
          />

          <div className="grid grid-cols-3 gap-2 mb-4">
            {dialPad.map((key) => (
              <button
                key={key}
                onClick={() => setPhoneNumber((prev) => prev + key)}
                className="bg-white/5 hover:bg-white/10 text-white text-lg font-medium py-2.5 rounded-xl transition-colors"
              >
                {key}
              </button>
            ))}
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => setPhoneNumber((prev) => prev.slice(0, -1))}
              className="flex-1 bg-white/5 hover:bg-white/10 text-gray-400 py-2.5 rounded-xl text-sm transition-colors"
            >
              Apagar
            </button>
            <button
              onClick={makeCall}
              disabled={!phoneNumber.trim() || !deviceReady}
              className="flex-1 bg-green-600 hover:bg-green-700 disabled:opacity-30 disabled:cursor-not-allowed text-white py-2.5 rounded-xl text-sm font-medium flex items-center justify-center gap-2 transition-colors"
            >
              <Phone className="w-4 h-4" /> Ligar
            </button>
          </div>
        </div>
      )}
    </>
  );
}
