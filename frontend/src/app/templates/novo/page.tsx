'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/auth-context';
import AppLayout from '@/components/AppLayout';
import api from '@/lib/api';
import { toast } from 'sonner';
import { ArrowLeft, Plus, Trash2, Loader2, Send } from 'lucide-react';

interface ChannelInfo {
  id: number;
  name: string;
}

type ButtonType = 'QUICK_REPLY' | 'URL' | 'PHONE_NUMBER';

interface TemplateButton {
  type: ButtonType;
  text: string;
  url?: string;
  phone_number?: string;
}

const NAME_RE = /^[a-z0-9_]+$/;

export default function NovoTemplatePage() {
  const { user } = useAuth();
  const router = useRouter();

  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [channelId, setChannelId] = useState<number | null>(null);

  const [name, setName] = useState('');
  const [category, setCategory] = useState('MARKETING');
  const [headerText, setHeaderText] = useState('');
  const [bodyText, setBodyText] = useState('');
  const [bodyExamples, setBodyExamples] = useState<string[]>([]);
  const [footerText, setFooterText] = useState('');
  const [buttons, setButtons] = useState<TemplateButton[]>([]);
  const [submitting, setSubmitting] = useState(false);

  // Admin-only guard
  useEffect(() => {
    if (user && user.role !== 'admin') router.push('/dashboard');
  }, [user, router]);

  useEffect(() => {
    if (!user || user.role !== 'admin') return;
    api.get('/channels')
      .then(res => {
        setChannels(res.data);
        if (res.data.length > 0) setChannelId(res.data[0].id);
      })
      .catch(() => toast.error('Erro ao carregar canais'));
  }, [user]);

  // Variáveis {{n}} detectadas no corpo (únicas, ordenadas)
  const varNums = useMemo(() => {
    const nums = [...bodyText.matchAll(/\{\{(\d+)\}\}/g)].map(m => Number(m[1]));
    return [...new Set(nums)].sort((a, b) => a - b);
  }, [bodyText]);

  // Mantém o array de exemplos do mesmo tamanho que o nº de variáveis
  useEffect(() => {
    setBodyExamples(prev => {
      const next = [...prev];
      next.length = varNums.length;
      for (let i = 0; i < next.length; i++) if (next[i] == null) next[i] = '';
      return next;
    });
  }, [varNums.length]);

  const insertVariable = () => {
    const nextN = varNums.length + 1;
    setBodyText(prev => `${prev}{{${nextN}}}`);
  };

  const addButton = (type: ButtonType) => {
    setButtons(prev => [...prev, { type, text: '', url: '', phone_number: '' }]);
  };
  const updateButton = (i: number, patch: Partial<TemplateButton>) => {
    setButtons(prev => prev.map((b, idx) => idx === i ? { ...b, ...patch } : b));
  };
  const removeButton = (i: number) => setButtons(prev => prev.filter((_, idx) => idx !== i));

  // Preview com exemplos substituídos
  const preview = useMemo(() => {
    let txt = bodyText;
    varNums.forEach((n, i) => {
      txt = txt.replaceAll(`{{${n}}}`, bodyExamples[i]?.trim() ? bodyExamples[i] : `{{${n}}}`);
    });
    return txt;
  }, [bodyText, varNums, bodyExamples]);

  const nameValid = name === '' || NAME_RE.test(name);

  const canSubmit =
    channelId != null &&
    NAME_RE.test(name) &&
    bodyText.trim() !== '' &&
    bodyExamples.length === varNums.length &&
    bodyExamples.every(e => e.trim() !== '');

  const handleSubmit = async () => {
    if (!canSubmit || channelId == null) return;
    setSubmitting(true);
    try {
      const payload = {
        name,
        category,
        language: 'pt_BR',
        header_text: headerText.trim() || null,
        body_text: bodyText,
        body_examples: bodyExamples,
        footer_text: footerText.trim() || null,
        buttons: buttons.map(b => ({
          type: b.type,
          text: b.text,
          url: b.type === 'URL' ? b.url : null,
          phone_number: b.type === 'PHONE_NUMBER' ? b.phone_number : null,
        })),
      };
      const res = await api.post(`/channels/${channelId}/templates`, payload);
      toast.success(`Template "${res.data.name}" enviado para aprovação (${res.data.status}). A análise é feita pelo Meta e não é instantânea.`);
      router.push('/templates');
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Erro ao criar template');
    } finally {
      setSubmitting(false);
    }
  };

  if (user && user.role !== 'admin') return null;

  const labelCls = 'block text-[13px] font-medium text-gray-500 mb-1.5';
  const inputCls = 'w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 placeholder:text-gray-400 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 focus:bg-white outline-none transition-all';

  return (
    <AppLayout>
      <div className="space-y-6 max-w-3xl mx-auto h-full overflow-y-auto pb-10">

        {/* Header */}
        <div className="flex items-center gap-3">
          <button onClick={() => router.push('/templates')} className="p-2 hover:bg-gray-100 rounded-xl transition-colors">
            <ArrowLeft className="w-5 h-5 text-gray-500" />
          </button>
          <div>
            <p className="text-sm text-gray-400 mb-0.5">Configuração / Templates</p>
            <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight">Novo template</h1>
          </div>
        </div>

        <div className="bg-white rounded-2xl border border-gray-100 p-6 space-y-5">

          {/* Canal */}
          <div>
            <label className={labelCls}>Canal</label>
            <select
              value={channelId ?? ''}
              onChange={e => setChannelId(Number(e.target.value))}
              className={inputCls}
            >
              {channels.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>

          {/* Nome */}
          <div>
            <label className={labelCls}>Nome do template</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="ex: confirmacao_matricula"
              className={`${inputCls} ${!nameValid ? 'border-red-300 focus:border-red-400 focus:ring-red-100' : ''}`}
            />
            <p className={`text-[12px] mt-1 ${!nameValid ? 'text-red-500' : 'text-gray-400'}`}>
              minúsculo, sem espaço, use _ (apenas a-z, 0-9 e _)
            </p>
          </div>

          {/* Categoria + Idioma */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelCls}>Categoria</label>
              <div className="flex gap-2">
                {(['MARKETING', 'UTILITY'] as const).map(cat => (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => setCategory(cat)}
                    className={`flex-1 py-2.5 rounded-xl text-[13px] font-medium border transition-all ${
                      category === cat ? 'border-[#2A658F] bg-[#2A658F]/5 text-[#2A658F]' : 'border-gray-200 text-gray-400 hover:bg-gray-50'
                    }`}
                  >
                    {cat === 'MARKETING' ? 'Marketing' : 'Utilidade'}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className={labelCls}>Idioma</label>
              <input type="text" value="pt_BR" disabled className={`${inputCls} bg-gray-100 text-gray-400 cursor-not-allowed`} />
            </div>
          </div>

          {/* Header (opcional) */}
          <div>
            <label className={labelCls}>Cabeçalho <span className="text-gray-400 font-normal">(opcional, texto fixo)</span></label>
            <input
              type="text"
              value={headerText}
              onChange={e => setHeaderText(e.target.value)}
              placeholder="ex: CENAT — Pós-Graduação"
              className={inputCls}
            />
          </div>

          {/* Corpo (obrigatório) */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[13px] font-medium text-gray-500">Corpo <span className="text-red-400">*</span></label>
              <button
                type="button"
                onClick={insertVariable}
                className="flex items-center gap-1 text-[12px] font-medium text-[#2A658F] hover:underline"
              >
                <Plus className="w-3.5 h-3.5" /> inserir variável
              </button>
            </div>
            <textarea
              value={bodyText}
              onChange={e => setBodyText(e.target.value)}
              rows={4}
              placeholder="Olá {{1}}, sua matrícula em {{2}} foi confirmada."
              className={`${inputCls} resize-y`}
            />
            <p className="text-[12px] text-gray-400 mt-1">Use variáveis {'{{1}}, {{2}}'}… sequenciais. Cada uma precisa de um exemplo abaixo.</p>
          </div>

          {/* Exemplos das variáveis */}
          {varNums.length > 0 && (
            <div className="space-y-2 bg-gray-50/60 border border-gray-100 rounded-xl p-4">
              <p className="text-[12px] font-semibold text-gray-500 uppercase tracking-wider">Exemplos das variáveis</p>
              {varNums.map((n, i) => (
                <div key={n} className="flex items-center gap-3">
                  <span className="text-[13px] font-mono text-gray-500 w-12">{`{{${n}}}`}</span>
                  <input
                    type="text"
                    value={bodyExamples[i] ?? ''}
                    onChange={e => setBodyExamples(prev => prev.map((v, idx) => idx === i ? e.target.value : v))}
                    placeholder={`Exemplo da variável ${n}`}
                    className={inputCls}
                  />
                </div>
              ))}
            </div>
          )}

          {/* Rodapé (opcional) */}
          <div>
            <label className={labelCls}>Rodapé <span className="text-gray-400 font-normal">(opcional)</span></label>
            <input
              type="text"
              value={footerText}
              onChange={e => setFooterText(e.target.value)}
              placeholder="ex: Equipe CENAT"
              className={inputCls}
            />
          </div>

          {/* Botões (opcional) */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-[13px] font-medium text-gray-500">Botões <span className="text-gray-400 font-normal">(opcional)</span></label>
              <div className="flex gap-2">
                <button type="button" onClick={() => addButton('QUICK_REPLY')} className="text-[12px] font-medium text-[#2A658F] hover:underline">+ Resposta rápida</button>
                <button type="button" onClick={() => addButton('URL')} className="text-[12px] font-medium text-[#2A658F] hover:underline">+ Link</button>
                <button type="button" onClick={() => addButton('PHONE_NUMBER')} className="text-[12px] font-medium text-[#2A658F] hover:underline">+ Telefone</button>
              </div>
            </div>
            {buttons.length > 0 && (
              <div className="space-y-2">
                {buttons.map((b, i) => (
                  <div key={i} className="flex items-center gap-2 bg-gray-50/60 border border-gray-100 rounded-xl p-3">
                    <span className="text-[11px] font-semibold text-gray-400 w-20 flex-shrink-0">
                      {b.type === 'QUICK_REPLY' ? 'Resposta' : b.type === 'URL' ? 'Link' : 'Telefone'}
                    </span>
                    <input
                      type="text"
                      value={b.text}
                      onChange={e => updateButton(i, { text: e.target.value })}
                      placeholder="Texto do botão"
                      className={`${inputCls} flex-1`}
                    />
                    {b.type === 'URL' && (
                      <input
                        type="text"
                        value={b.url ?? ''}
                        onChange={e => updateButton(i, { url: e.target.value })}
                        placeholder="https://..."
                        className={`${inputCls} flex-1`}
                      />
                    )}
                    {b.type === 'PHONE_NUMBER' && (
                      <input
                        type="text"
                        value={b.phone_number ?? ''}
                        onChange={e => updateButton(i, { phone_number: e.target.value })}
                        placeholder="+55119..."
                        className={`${inputCls} flex-1`}
                      />
                    )}
                    <button type="button" onClick={() => removeButton(i)} className="p-2 hover:bg-red-50 rounded-lg text-gray-400 hover:text-red-500 transition-colors">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Preview */}
          <div>
            <label className={labelCls}>Pré-visualização</label>
            <div className="bg-[#e5ddd5] rounded-xl p-4">
              <div className="bg-white rounded-lg shadow-sm p-3 max-w-sm text-[13px] text-gray-800 whitespace-pre-wrap break-words">
                {headerText.trim() && <p className="font-semibold mb-1">{headerText}</p>}
                <p>{preview || <span className="text-gray-400">O corpo da mensagem aparece aqui…</span>}</p>
                {footerText.trim() && <p className="text-[11px] text-gray-400 mt-1">{footerText}</p>}
                {buttons.length > 0 && (
                  <div className="mt-2 border-t border-gray-100 pt-2 space-y-1">
                    {buttons.map((b, i) => (
                      <p key={i} className="text-center text-[#2A658F] text-[13px] font-medium">{b.text || '(botão)'}</p>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Aviso + Submit */}
        <div className="space-y-3">
          <p className="text-[12px] text-gray-500 bg-amber-50/60 border border-amber-100 rounded-xl px-4 py-3">
            Ao enviar, o template fica <strong>em análise (PENDING)</strong>. A aprovação é feita pelo WhatsApp/Meta e <strong>não é instantânea</strong>.
          </p>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit || submitting}
            className="w-full py-3 bg-[#2A658F] text-white font-medium rounded-xl hover:bg-[#1f5375] hover:shadow-lg hover:shadow-[#2A658F]/20 active:scale-[0.98] transition-all disabled:opacity-40 disabled:active:scale-100 flex items-center justify-center gap-2"
          >
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            {submitting ? 'Enviando...' : 'Enviar para aprovação'}
          </button>
        </div>

      </div>
    </AppLayout>
  );
}
