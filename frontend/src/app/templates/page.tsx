'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/auth-context';
import AppLayout from '@/components/AppLayout';
import api from '@/lib/api';
import { toast } from 'sonner';
import { LayoutTemplate, Plus, Loader2, RefreshCw } from 'lucide-react';

interface ChannelInfo {
  id: number;
  name: string;
}

interface TemplateInfo {
  name: string;
  language: string;
  status: string;
  category: string | null;
  rejected_reason: string | null;
  body: string;
  parameters: string[];
}

const STATUS_STYLE: Record<string, string> = {
  APPROVED: 'bg-emerald-50 text-emerald-700 border-emerald-100',
  PENDING: 'bg-amber-50 text-amber-700 border-amber-100',
  REJECTED: 'bg-red-50 text-red-600 border-red-100',
};

const STATUS_LABEL: Record<string, string> = {
  APPROVED: 'Aprovado',
  PENDING: 'Em análise',
  REJECTED: 'Rejeitado',
};

export default function TemplatesPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [channelId, setChannelId] = useState<number | null>(null);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  // Admin-only guard
  useEffect(() => {
    if (user && user.role !== 'admin') router.push('/dashboard');
  }, [user, router]);

  // Carrega canais e seleciona o primeiro (canal ativo padrão)
  useEffect(() => {
    if (!user || user.role !== 'admin') return;
    api.get('/channels')
      .then(res => {
        setChannels(res.data);
        if (res.data.length > 0) setChannelId(res.data[0].id);
      })
      .catch(() => toast.error('Erro ao carregar canais'));
  }, [user]);

  const loadTemplates = async (chId: number) => {
    setLoading(true);
    try {
      const res = await api.get(`/channels/${chId}/templates?status=all`);
      setTemplates(res.data);
    } catch (err) {
      toast.error('Erro ao carregar templates');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (channelId != null) loadTemplates(channelId);
  }, [channelId]);

  if (user && user.role !== 'admin') return null;

  const statusBadge = (status: string) => {
    const cls = STATUS_STYLE[status] || 'bg-gray-50 text-gray-600 border-gray-100';
    const label = STATUS_LABEL[status] || status;
    return (
      <span className={`inline-flex items-center px-2.5 py-0.5 text-[11px] font-semibold rounded-md border ${cls}`}>
        {label}
      </span>
    );
  };

  return (
    <AppLayout>
      <div className="space-y-6 max-w-5xl mx-auto h-full overflow-y-auto pb-6">

        {/* Header */}
        <div className={`flex items-center justify-between transition-all duration-700 ease-out ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'}`}>
          <div>
            <p className="text-sm text-gray-400 mb-0.5">Configuração</p>
            <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight">Templates</h1>
          </div>
          <button
            onClick={() => router.push('/templates/novo')}
            className="flex items-center gap-2 px-4 py-2.5 bg-[#2A658F] text-white text-[13px] font-medium rounded-xl hover:bg-[#1f5375] hover:shadow-lg hover:shadow-[#2A658F]/20 active:scale-[0.98] transition-all"
          >
            <Plus className="w-4 h-4" />
            Novo template
          </button>
        </div>

        {/* Aviso aprovação assíncrona */}
        <div className="text-[12px] text-gray-500 bg-amber-50/60 border border-amber-100 rounded-xl px-4 py-3">
          A aprovação dos templates é feita pelo WhatsApp/Meta e <strong>não é instantânea</strong> — pode levar de minutos a horas.
          Use o botão <em>Atualizar</em> para conferir o status mais recente.
        </div>

        {/* Controles: canal + refresh */}
        <div className="flex items-center gap-3">
          <select
            value={channelId ?? ''}
            onChange={e => setChannelId(Number(e.target.value))}
            className="px-3 py-2 bg-white border border-gray-200 rounded-xl text-sm text-gray-700 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 outline-none transition-all"
          >
            {channels.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <button
            onClick={() => channelId != null && loadTemplates(channelId)}
            disabled={loading || channelId == null}
            className="flex items-center gap-2 px-3 py-2 bg-gray-50 text-gray-600 text-[13px] font-medium rounded-xl hover:bg-gray-100 transition-all disabled:opacity-40"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Atualizar
          </button>
        </div>

        {/* Lista */}
        <div className={`bg-white rounded-2xl border border-gray-100 overflow-hidden transition-all duration-700 ease-out delay-150 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-6 h-6 text-[#2A658F] animate-spin" />
            </div>
          ) : templates.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-gray-400">
              <LayoutTemplate className="w-10 h-10 mb-2 text-gray-300" />
              <p className="text-sm">Nenhum template neste canal</p>
            </div>
          ) : (
            <div>
              {/* Table header */}
              <div className="hidden sm:grid grid-cols-[1fr_120px_110px_120px] px-6 py-3 border-b border-gray-100 bg-gray-50/50">
                <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Template</span>
                <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Categoria</span>
                <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Idioma</span>
                <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider text-right">Status</span>
              </div>

              {templates.map((t) => (
                <div
                  key={`${t.name}_${t.language}`}
                  className="grid grid-cols-1 sm:grid-cols-[1fr_120px_110px_120px] items-center px-6 py-4 border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors gap-2 sm:gap-0"
                >
                  <div className="min-w-0">
                    <p className="font-medium text-[13px] text-[#27273D] truncate">{t.name}</p>
                    <p className="text-[12px] text-gray-400 truncate">{t.body}</p>
                    {t.status === 'REJECTED' && t.rejected_reason && t.rejected_reason !== 'NONE' && (
                      <p className="text-[11px] text-red-500 mt-0.5">Motivo: {t.rejected_reason}</p>
                    )}
                  </div>
                  <div className="text-[12px] text-gray-500">{t.category || '—'}</div>
                  <div className="text-[12px] text-gray-500">{t.language}</div>
                  <div className="flex sm:justify-end">{statusBadge(t.status)}</div>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </AppLayout>
  );
}
