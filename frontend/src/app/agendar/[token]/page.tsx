'use client';

/**
 * Página pública do lead ESPONTÂNEO — hub.cenatdata.online/agendar/<token>
 *
 * Quem chega aqui recebeu o link da Nat no WhatsApp. NÃO chama `useAuth`: é assim que uma
 * rota fica pública neste projeto — não há middleware, cada página protegida se guarda
 * sozinha (`dashboard/page.tsx:65`).
 *
 * ---------------------------------------------------------------------------------------
 * O QUE FOI HERDADO DA `docs/referencia-obrigado.html`
 * ---------------------------------------------------------------------------------------
 * Quatro armadilhas já resolvidas em produção, e a razão de a referência estar no repo:
 *
 *   1. 409 no booking -> avisa, zera a hora escolhida e RECARREGA a grade. Nunca deixar
 *      clicar de novo no slot que já morreu.
 *   2. Sem grade -> não é beco: cadastra o contato mesmo assim (`/lead`) e avisa que o time
 *      chama no WhatsApp. Perder o lead por falta de horário é o pior desfecho.
 *   3. `rotulo()` monta a data por PARTES. `new Date("2026-08-19")` é lido como UTC e, a
 *      oeste de Greenwich, mostra 18/ago. O backend manda tudo em horário de Brasília.
 *   4. Confirmação com nome da consultora e "(horário de Brasília)" explícito.
 *
 * O que NÃO foi herdado: Pixel do Facebook e DashCENAT (esta página é continuação de uma
 * conversa, não peça de campanha — disparar `Lead` aqui contaria o mesmo lead duas vezes),
 * o campo de telefone editável e o `?lead=` na query.
 *
 * ---------------------------------------------------------------------------------------
 * O TELEFONE NÃO ESTÁ NESTA TELA POR ACIDENTE
 * ---------------------------------------------------------------------------------------
 * Ele vem do token, no servidor, e aparece MASCARADO (`(85) 9****-5219`) só para a pessoa
 * se reconhecer. Nenhum POST daqui carrega telefone: se carregasse, qualquer um agendaria
 * no nome de qualquer número, porque a página é pública.
 */

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';

// Caminho relativo de propósito: o nginx de hub.cenatdata.online já manda `/api/` para o
// backend, e a página é servida pelo mesmo host. Sem env, sem CORS, sem uma variável a mais
// para alguém esquecer de configurar no deploy.
const API = '/api/agendamento';
const WA_CANAL = 'https://wa.me/5511952137432';

const MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun',
             'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const SEM = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];

type Slot = { id: string; hora: string; fim: string };
type Dias = Record<string, Slot[]>;
type Estado = 'carregando' | 'ok' | 'usado' | 'morto';

interface Token {
  status: string;
  nome: string | null;
  curso: string | null;
  telefone_mascarado: string;
  agendamento?: { inicio: string | null; consultora_nome: string };
}

/** Monta a data pelas PARTES — ver o item 3 do cabeçalho. */
function rotulo(iso: string) {
  const p = iso.split('-').map(Number);
  const d = new Date(p[0], p[1] - 1, p[2]);
  return { semana: SEM[d.getDay()], dia: p[2], mes: MES[p[1] - 1] };
}

function dataHoraLegivel(iso: string) {
  const [dia, hora] = iso.split('T');
  const r = rotulo(dia);
  return `${r.semana}, ${r.dia} de ${r.mes} às ${hora.slice(0, 5)}`;
}

export default function AgendarPorToken() {
  const params = useParams<{ token: string }>();
  const token = params?.token ?? '';

  const [estado, setEstado] = useState<Estado>('carregando');
  const [dados, setDados] = useState<Token | null>(null);
  const [dias, setDias] = useState<Dias>({});
  const [diaSel, setDiaSel] = useState<string | null>(null);
  const [slotSel, setSlotSel] = useState<string | null>(null);
  const [nome, setNome] = useState('');
  const [email, setEmail] = useState('');
  const [enviando, setEnviando] = useState(false);
  const [msg, setMsg] = useState<{ texto: string; tipo: 'erro' | 'ok' } | null>(null);
  const [feito, setFeito] = useState<{ inicio: string | null; consultora: string } | null>(null);

  const semGrade = Object.keys(dias).length === 0;

  const carregarSlots = useCallback(async () => {
    try {
      const r = await fetch(`${API}/slots`);
      const d = await r.json();
      const novos: Dias = d.fallback ? {} : (d.dias || {});
      setDias(novos);
      const chaves = Object.keys(novos).sort();
      setDiaSel(chaves[0] ?? null);
      setSlotSel(null);
    } catch {
      setDias({});          // rede caiu: cai no fallback, não em tela quebrada
    }
  }, []);

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const r = await fetch(`${API}/espontaneo/${encodeURIComponent(token)}`);
        if (!r.ok) { setEstado('morto'); return; }
        const d: Token = await r.json();
        setDados(d);
        setNome(d.nome ?? '');
        if (d.status === 'usado') { setEstado('usado'); return; }
        await carregarSlots();
        setEstado('ok');
      } catch {
        setEstado('morto');
      }
    })();
  }, [token, carregarSlots]);

  async function enviar() {
    if (nome.trim().length < 2) { setMsg({ texto: 'Escreva seu nome completo.', tipo: 'erro' }); return; }
    if (!semGrade && !slotSel) { setMsg({ texto: 'Escolha um horário.', tipo: 'erro' }); return; }

    setEnviando(true);
    setMsg({ texto: 'Enviando…', tipo: 'ok' });
    const rota = semGrade ? 'lead' : 'agendar';
    try {
      const r = await fetch(`${API}/espontaneo/${encodeURIComponent(token)}/${rota}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome: nome.trim(), email: email.trim() || null,
                               slot: semGrade ? null : slotSel }),
      });
      const d = await r.json().catch(() => ({}));
      setEnviando(false);

      if (r.status === 409) {
        // Alguém pegou o horário, ou o link foi usado noutra aba. Recarrega em vez de
        // deixar clicar de novo no que já morreu.
        setMsg({ texto: d.detail || 'Esse horário acabou de ser preenchido. Escolha outro.', tipo: 'erro' });
        await carregarSlots();
        return;
      }
      if (r.status === 404 || r.status === 410) { setEstado('morto'); return; }
      if (!r.ok) {
        setMsg({ texto: d.detail || 'Não consegui concluir. Tente de novo.', tipo: 'erro' });
        return;
      }
      setFeito({ inicio: d.inicio ?? null, consultora: d.consultora_nome ?? '' });
    } catch {
      setEnviando(false);
      setMsg({ texto: 'Falha de conexão. Tente de novo em instantes.', tipo: 'erro' });
    }
  }

  // ---------------------------------------------------------------- moldura comum
  const Moldura = ({ children }: { children: React.ReactNode }) => (
    <main className="min-h-screen bg-gradient-to-br from-[#0F1D30] via-[#1A2E4A] to-[#243B5E] px-4 py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[600px] overflow-hidden rounded-3xl bg-white shadow-[0_24px_80px_rgba(0,0,0,.25)]">
        {children}
      </div>
      <p className="mt-6 text-center text-[.72rem] text-white/25">
        Copyright © 2026 CENAT — Centro Educacional Novas Abordagens em Saúde Mental.
      </p>
    </main>
  );

  const Topo = ({ titulo, sub }: { titulo: string; sub: string }) => (
    <div className="bg-gradient-to-br from-[#1A2E4A] to-[#243B5E] px-6 py-8 text-center sm:px-10 sm:py-10">
      <h1 className="text-[1.5rem] font-extrabold leading-tight tracking-tight text-white sm:text-[2rem]">
        {titulo}
      </h1>
      <p className="mx-auto mt-3 max-w-[460px] text-[.95rem] leading-relaxed text-white/70">{sub}</p>
    </div>
  );

  // ---------------------------------------------------------------- telas terminais
  if (estado === 'carregando') {
    return (
      <Moldura>
        <div className="px-6 py-16 text-center text-[#5A6577]">Carregando…</div>
      </Moldura>
    );
  }

  if (estado === 'morto') {
    // NUNCA beco sem saída: o caminho de volta é a conversa que já existia.
    return (
      <Moldura>
        <Topo titulo="Este link não está mais válido"
              sub="Links de agendamento valem por 7 dias e só podem ser usados uma vez." />
        <div className="px-6 py-8 text-center sm:px-10">
          <p className="mb-6 text-[.95rem] leading-relaxed text-[#5A6577]">
            Sem problema — é só retomar a conversa no WhatsApp que a gente manda um novo.
          </p>
          <a href={WA_CANAL} target="_blank" rel="noopener noreferrer"
             className="inline-flex w-full max-w-[420px] items-center justify-center gap-2 rounded-full bg-gradient-to-br from-[#25D366] to-[#128C7E] px-8 py-4 font-bold text-white shadow-[0_4px_20px_rgba(37,211,102,.35)]">
            Voltar para o WhatsApp
          </a>
        </div>
      </Moldura>
    );
  }

  if (estado === 'usado' || feito) {
    const inicio = feito ? feito.inicio : dados?.agendamento?.inicio ?? null;
    const consultora = feito ? feito.consultora : dados?.agendamento?.consultora_nome ?? '';
    return (
      <Moldura>
        <Topo titulo={feito ? 'Prontinho!' : 'Você já agendou'}
              sub={feito ? 'Sua conversa está confirmada.' : 'Este link já foi usado para marcar uma conversa.'} />
        <div className="px-6 py-8 sm:px-10">
          <div className="rounded-2xl bg-[#e6fcf5] px-5 py-4 text-[#087f5b]">
            {inicio ? (
              <>
                <strong>{dataHoraLegivel(inicio)}</strong>
                {consultora && <> — com {consultora}</>}
                <br />
                <span className="text-[.88rem]">(horário de Brasília)</span>
              </>
            ) : (
              <strong>Recebemos seu contato. Nossa equipe fala com você em breve.</strong>
            )}
          </div>
          <p className="mt-4 text-[.88rem] leading-relaxed text-[#5A6577]">
            Precisa remarcar ou cancelar? Fale com a gente pelo WhatsApp — é por lá que
            ajustamos o horário.
          </p>
        </div>
      </Moldura>
    );
  }

  // ---------------------------------------------------------------- tela principal
  const chaves = Object.keys(dias).sort();

  return (
    <Moldura>
      <Topo titulo={dados?.nome ? `Vamos marcar, ${dados.nome.split(' ')[0]}?` : 'Vamos marcar sua conversa?'}
            sub="A conversa dura 45 minutos e acontece online, no horário de Brasília." />

      <div className="px-6 py-7 sm:px-10 sm:py-9">
        {dados?.curso && (
          <div className="mb-6 rounded-2xl border-l-4 border-[#2B6CB0] bg-[#F7F9FC] px-4 py-3">
            <span className="text-[.75rem] font-bold uppercase tracking-widest text-[#5A6577]">
              Curso de interesse
            </span>
            <p className="font-semibold text-[#1A2E4A]">{dados.curso}</p>
          </div>
        )}

        <label className="mb-1 block text-[.8rem] font-bold text-[#1A2E4A]">Nome completo</label>
        <input value={nome} onChange={(e) => setNome(e.target.value)} autoComplete="name"
               placeholder="Seu nome"
               className="w-full rounded-xl border border-[#D8DFE9] bg-white px-4 py-3 text-[#1A2E4A] outline-none focus:border-[#4A9FD8] focus:ring-2 focus:ring-[#4A9FD8]" />

        <label className="mb-1 mt-4 block text-[.8rem] font-bold text-[#1A2E4A]">
          E-mail <span className="font-normal text-[#8B95A5]">(opcional)</span>
        </label>
        <input value={email} onChange={(e) => setEmail(e.target.value)} type="email"
               autoComplete="email" placeholder="voce@email.com"
               className="w-full rounded-xl border border-[#D8DFE9] bg-white px-4 py-3 text-[#1A2E4A] outline-none focus:border-[#4A9FD8] focus:ring-2 focus:ring-[#4A9FD8]" />

        {dados?.telefone_mascarado && (
          <>
            <label className="mb-1 mt-4 block text-[.8rem] font-bold text-[#1A2E4A]">WhatsApp</label>
            <input value={dados.telefone_mascarado} readOnly aria-readonly
                   className="w-full cursor-not-allowed rounded-xl border border-[#D8DFE9] bg-[#F7F9FC] px-4 py-3 text-[#5A6577]" />
            <p className="mt-1 text-[.78rem] text-[#8B95A5]">
              É o número desta conversa. Para trocar, fale com a gente no WhatsApp.
            </p>
          </>
        )}

        {semGrade ? (
          <div className="mt-6 rounded-2xl bg-[#fff5f5] px-5 py-4 text-[.92rem] leading-relaxed text-[#c92a2a]">
            Não há horários abertos no momento — deixe seus dados que entramos em contato
            pelo WhatsApp.
          </div>
        ) : (
          <>
            <label className="mb-2 mt-6 block text-[.8rem] font-bold text-[#1A2E4A]">Dia</label>
            <div className="flex gap-2 overflow-x-auto pb-2">
              {chaves.map((iso) => {
                const r = rotulo(iso);
                const sel = iso === diaSel;
                return (
                  <button key={iso} type="button"
                          onClick={() => { setDiaSel(iso); setSlotSel(null); }}
                          className={`flex-none rounded-xl border px-4 py-2 text-center text-[.85rem] leading-tight ${
                            sel ? 'border-[#2B6CB0] bg-[#2B6CB0] text-white'
                                : 'border-[#D8DFE9] bg-white text-[#1A2E4A]'}`}>
                    {r.semana}
                    <small className="block text-[.75rem] opacity-75">{r.dia} {r.mes}</small>
                  </button>
                );
              })}
            </div>

            <label className="mb-2 mt-4 block text-[.8rem] font-bold text-[#1A2E4A]">Horário</label>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(92px,1fr))] gap-2">
              {(dias[diaSel ?? ''] || []).map((s) => (
                <button key={s.id} type="button" onClick={() => setSlotSel(s.id)}
                        className={`rounded-xl border py-3 ${
                          slotSel === s.id ? 'border-[#2B6CB0] bg-[#2B6CB0] text-white'
                                           : 'border-[#D8DFE9] bg-white text-[#1A2E4A]'}`}>
                  {s.hora}
                </button>
              ))}
            </div>
          </>
        )}

        <button onClick={enviar} disabled={enviando}
                className="mt-7 w-full rounded-full bg-gradient-to-br from-[#E5A83B] to-[#C8891E] px-6 py-4 text-[1.02rem] font-bold text-[#1A2E4A] shadow-[0_4px_20px_rgba(229,168,59,.35)] disabled:opacity-50">
          {enviando ? 'Enviando…' : semGrade ? 'Deixar meu contato' : 'Confirmar agendamento'}
        </button>

        {msg && (
          <div className={`mt-4 rounded-xl px-4 py-3 text-[.92rem] leading-relaxed ${
            msg.tipo === 'erro' ? 'bg-[#fff5f5] text-[#c92a2a]' : 'bg-[#e6fcf5] text-[#087f5b]'}`}>
            {msg.texto}
          </div>
        )}
      </div>
    </Moldura>
  );
}
