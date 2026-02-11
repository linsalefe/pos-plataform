'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { Phone, PhoneOff, PhoneIncoming, X, Mic, MicOff } from 'lucide-react';

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
  const [loading, setLoading] = useState(false);

  const deviceRef = useRef<any>(null);
  const callRef = useRef<any>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const sdkLoadedRef = useRef(false);
  const initStartedRef = useRef(false);

  // Carregar Twilio Voice SDK 2.x
  useEffect(() => {
    if (sdkLoadedRef.current) return;
    sdkLoadedRef.current = true;

    const script = document.createElement('script');
    script.src = 'https://sdk.twilio.com/js/client/releases/2.7.3/twilio.min.js';
    script.async = true;
    script.onload = () => {
      console.log('📞 Twilio SDK 2.x carregado');
    };
    script.onerror = () => {
      console.error('❌ Erro ao carregar Twilio SDK');
      setError('Erro ao carregar SDK de voz');
    };
    document.head.appendChild(script);

    return () => {
      if (deviceRef.current) {
        try { deviceRef.current.destroy(); } catch (e) {}
      }
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  // Escutar evento de ligação da página de conversas
  useEffect(() => {
    const handler = (e: any) => {
      const phone = e.detail?.phone || '';
      if (phone) {
        setPhoneNumber(phone);
        setShowDialer(true);
        if (!deviceReady && !initStartedRef.current) initDevice();
      }
    };
    window.addEventListener('cenat-call', handler);
    return () => window.removeEventListener('cenat-call', handler);
  }, [deviceReady]);

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

      if (!res.ok) {
        throw new Error('Erro ao obter token de voz');
      }

      const data = await res.json();
      const twilioToken = data.token;

      if (!window.Twilio || !window.Twilio.Device) {
        setError('SDK ainda carregando, tente novamente');
        initStartedRef.current = false;
        setLoading(false);
        return;
      }

      // SDK 2.x: token no construtor
      const device = new window.Twilio.Device(twilioToken, {
        codecPreferences: ['opus', 'pcmu'],
        closeProtection: true,
        logLevel: 1,
      });

      // SDK 2.x: evento 'registered' ao invés de 'ready'
      device.on('registered', () => {
        console.log('📞 Twilio Device registrado e pronto');
        setDeviceReady(true);
        setLoading(false);
        setError('');
      });

      device.on('registering', () => {
        console.log('📞 Twilio Device registrando...');
      });

      device.on('error', (err: any) => {
        console.error('📞 Twilio Error:', err);
        setError(err.message || 'Erro no dispositivo');
        setLoading(false);
      });

      device.on('unregistered', () => {
        console.log('📞 Twilio Device desregistrado');
        setDeviceReady(false);
      });

      // SDK 2.x: chamadas recebidas
      device.on('incoming', (call: any) => {
        callRef.current = call;
        setIncomingFrom(call.parameters?.From || 'Desconhecido');
        setStatus('incoming');

        call.on('disconnect', () => handleCallEnd());
        call.on('cancel', () => handleCallEnd());
        call.on('reject', () => handleCallEnd());
      });

      // Registrar para receber chamadas
      await device.register();

      deviceRef.current = device;
    } catch (err: any) {
      console.error('Erro ao inicializar Twilio:', err);
      setError(err.message || 'Erro ao conectar');
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
      // SDK 2.x: connect retorna Promise
      const call = await deviceRef.current.connect({
        params: { To: number },
      });

      callRef.current = call;

      call.on('ringing', () => {
        console.log('📞 Chamando...');
        setStatus('ringing');
      });

      call.on('accept', () => {
        console.log('📞 Chamada aceita');
        setStatus('in-call');
        startTimer();
      });

      call.on('disconnect', () => {
        console.log('📞 Chamada encerrada');
        handleCallEnd();
      });

      call.on('cancel', () => {
        console.log('📞 Chamada cancelada');
        handleCallEnd();
      });

      call.on('error', (err: any) => {
        console.error('📞 Erro na chamada:', err);
        setError(err.message || 'Erro na chamada');
        handleCallEnd();
      });
    } catch (err: any) {
      console.error('Erro ao fazer chamada:', err);
      setError(err.message || 'Erro ao iniciar chamada');
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
    if (callRef.current) {
      callRef.current.disconnect();
    }
    if (deviceRef.current) {
      deviceRef.current.disconnectAll();
    }
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

  const handleDialerToggle = () => {
    const opening = !showDialer;
    setShowDialer(opening);
    if (opening && !deviceReady && !initStartedRef.current) {
      initDevice();
    }
  };

  const dialPad = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#'];

  // Chamada recebida
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

  // Em chamada
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
        onClick={handleDialerToggle}
        className={`fixed bottom-6 right-6 z-50 w-14 h-14 text-white rounded-full shadow-lg flex items-center justify-center transition-all duration-200 hover:scale-105 ${
          deviceReady ? 'bg-[#2A658F] hover:bg-[#347aab]' : 'bg-gray-400 hover:bg-gray-500'
        }`}
      >
        {showDialer ? <X className="w-6 h-6" /> : <Phone className="w-6 h-6" />}
        <span className={`absolute top-0 right-0 w-3.5 h-3.5 rounded-full border-2 border-white ${
          status === 'in-call' ? 'bg-red-500 animate-pulse' : deviceReady ? 'bg-green-500' : 'bg-gray-400'
        }`} />
      </button>

      {showDialer && (
        <div className="fixed bottom-24 right-6 z-50 bg-[#0f1b2d] border border-white/10 rounded-2xl p-5 shadow-2xl w-[300px]">
          <p className="text-white font-semibold text-sm mb-3">Discador</p>

          {error && (
            <p className="text-red-400 text-xs mb-2 bg-red-400/10 px-3 py-1.5 rounded-lg">{error}</p>
          )}

          {loading && (
            <p className="text-yellow-400 text-xs mb-2 bg-yellow-400/10 px-3 py-1.5 rounded-lg">Conectando ao servidor de voz...</p>
          )}

          {deviceReady && (
            <p className="text-green-400 text-xs mb-2 bg-green-400/10 px-3 py-1.5 rounded-lg">Pronto para ligações</p>
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
