'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Bell, X } from 'lucide-react';
import api from '@/lib/api';

interface Notif {
  id: number;
  contact_wa_id: string | null;
  type: string;
  title: string;
  body: string | null;
  is_read: boolean;
  created_at: string | null;
}

function timeAgo(iso: string | null): string {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return 'agora';
  if (diff < 3600) return `${Math.floor(diff / 60)}min`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

export default function NotificationBell({ collapsed = false }: { collapsed?: boolean }) {
  const router = useRouter();
  const [items, setItems] = useState<Notif[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [perm, setPerm] = useState<string>('default');

  const lastIdRef = useRef(0);
  const initRef = useRef(false);
  const audioCtxRef = useRef<any>(null);

  useEffect(() => {
    if (typeof window !== 'undefined' && 'Notification' in window) {
      setPerm(Notification.permission);
    }
  }, []);

  const unlockAudio = () => {
    try {
      const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext;
      if (!Ctx) return;
      if (!audioCtxRef.current) audioCtxRef.current = new Ctx();
      if (audioCtxRef.current.state === 'suspended' && audioCtxRef.current.resume) audioCtxRef.current.resume();
    } catch {}
  };

  const playSound = () => {
    try {
      const ctx = audioCtxRef.current;
      if (!ctx) return;
      if (ctx.state === 'suspended' && ctx.resume) ctx.resume();
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      o.type = 'sine';
      o.frequency.setValueAtTime(880, ctx.currentTime);
      o.frequency.setValueAtTime(660, ctx.currentTime + 0.12);
      g.gain.setValueAtTime(0.0001, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.3);
      o.start();
      o.stop(ctx.currentTime + 0.32);
    } catch {}
  };

  const showPopup = (title: string, body: string | null, wa: string | null, force = false) => {
    try {
      if (typeof window === 'undefined' || !('Notification' in window)) return;
      if (Notification.permission !== 'granted') return;
      if (!force && document.hasFocus()) return;
      const n = new Notification(title, { body: body || '', icon: '/logo-icon-white.png' });
      n.onclick = () => { window.focus(); router.push(wa ? `/conversations?wa=${wa}` : '/conversations'); n.close(); };
    } catch {}
  };

  const load = async () => {
    try {
      const res = await api.get('/notifications');
      const list: Notif[] = res.data.items || [];
      const cnt: number = res.data.unread_count || 0;
      const maxId = list.reduce((m, n) => Math.max(m, n.id), 0);

      if (!initRef.current) {
        initRef.current = true;
        lastIdRef.current = maxId;
      } else if (maxId > lastIdRef.current) {
        const fresh = list.filter(n => n.id > lastIdRef.current && !n.is_read);
        if (fresh.length > 0 && !document.hasFocus()) {
          playSound();
          if (fresh.length === 1) showPopup(fresh[0].title, fresh[0].body, fresh[0].contact_wa_id);
          else showPopup(`${fresh.length} novas notificações`, 'Você tem novas notificações no Hub.', null);
        }
        lastIdRef.current = maxId;
      }

      setItems(list);
      setUnread(cnt);
    } catch {}
  };

  useEffect(() => {
    if (typeof window !== 'undefined' && !localStorage.getItem('token')) return;
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, []);

  const askPermission = () => {
    unlockAudio();
    try {
      if ('Notification' in window) Notification.requestPermission().then(p => setPerm(p));
    } catch {}
  };

  const testNotification = () => {
    unlockAudio();
    const fire = () => { playSound(); showPopup('Notificação de teste', 'Funcionando! Som e popup ativos. 🔔', null, true); };
    if ('Notification' in window && Notification.permission !== 'granted') {
      Notification.requestPermission().then(p => { setPerm(p); fire(); });
    } else {
      fire();
    }
  };

  const openNotif = async (n: Notif) => {
    unlockAudio();
    try { await api.post(`/notifications/${n.id}/read`); } catch {}
    setOpen(false);
    load();
    router.push(n.contact_wa_id ? `/conversations?wa=${n.contact_wa_id}` : '/conversations');
  };

  const markAll = async () => {
    try { await api.post('/notifications/read-all'); } catch {}
    load();
  };

  return (
    <div className="relative">
      <button
        onClick={() => { unlockAudio(); setOpen(!open); }}
        className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-gray-400 hover:text-white hover:bg-white/[0.04] transition-all duration-200 text-[13px] ${collapsed ? 'justify-center' : ''}`}
      >
        <div className="relative">
          <Bell className="w-[16px] h-[16px] flex-shrink-0" />
          {unread > 0 && (
            <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[9px] font-bold flex items-center justify-center">
              {unread > 99 ? '99+' : unread}
            </span>
          )}
        </div>
        {!collapsed && <span>Notificações</span>}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="fixed left-4 bottom-24 w-[330px] max-h-[60vh] bg-white rounded-2xl border border-gray-200 shadow-2xl z-50 flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
              <p className="text-[13px] font-semibold text-[#27273D]">Notificações</p>
              <div className="flex items-center gap-2">
                {unread > 0 && (
                  <button onClick={markAll} className="text-[11px] text-[#2A658F] hover:underline">marcar todas</button>
                )}
                <button onClick={() => setOpen(false)} className="p-1 hover:bg-gray-100 rounded-lg">
                  <X className="w-3.5 h-3.5 text-gray-400" />
                </button>
              </div>
            </div>

            {perm === 'default' && (
              <button
                onClick={askPermission}
                className="flex items-center gap-2 px-4 py-2.5 bg-[#2A658F]/[0.06] text-[#2A658F] text-[12px] font-medium hover:bg-[#2A658F]/[0.1] transition-colors border-b border-gray-100"
              >
                <Bell className="w-3.5 h-3.5" />
                Ativar notificações no navegador
              </button>
            )}
            {perm === 'granted' && (
              <button
                onClick={testNotification}
                className="px-4 py-2 text-[11px] text-[#2A658F] hover:bg-[#2A658F]/[0.06] transition-colors border-b border-gray-100 text-left"
              >
                Testar notificação (som + popup)
              </button>
            )}
            {perm === 'denied' && (
              <p className="px-4 py-2.5 text-[11px] text-amber-700 bg-amber-50 border-b border-gray-100">
                Notificações bloqueadas. Libere no cadeado da barra de endereço → Notificações → Permitir.
              </p>
            )}

            <div className="flex-1 overflow-y-auto">
              {items.length === 0 ? (
                <p className="text-[12px] text-gray-400 text-center py-8">Nenhuma notificação</p>
              ) : (
                items.map(n => (
                  <button
                    key={n.id}
                    onClick={() => openNotif(n)}
                    className={`w-full text-left px-4 py-3 border-b border-gray-50 hover:bg-gray-50 transition-colors ${n.is_read ? '' : 'bg-[#2A658F]/[0.04]'}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className={`text-[12.5px] ${n.is_read ? 'text-gray-600' : 'font-semibold text-[#27273D]'}`}>{n.title}</p>
                      <span className="text-[10px] text-gray-400 flex-shrink-0 mt-0.5">{timeAgo(n.created_at)}</span>
                    </div>
                    {n.body && <p className="text-[11.5px] text-gray-400 truncate mt-0.5">{n.body}</p>}
                  </button>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
