'use client';

/**
 * A página de Relatórios. Somente leitura, nenhuma ação.
 *
 * Quem lê é a gestora comercial e o diretor, sozinhos. Três regras governam a tela:
 *
 *   1. N ao lado de todo percentual. As amostras são de dezenas.
 *   2. Métrica não medível tem estado visual PRÓPRIO — nem zero, nem vazio, nem spinner
 *      eterno. Um card cinza dizendo "não medível" e o motivo.
 *   3. `definicao` e `limitacao` vêm do backend e são renderizadas como estão. O front não
 *      reescreve nenhuma das duas: uma fonte só, senão o texto da tela e o do relatório
 *      divergem e ninguém sabe qual vale.
 *
 * SEM BIBLIOTECA DE GRÁFICO, de propósito. As métricas deste painel são comparações de
 * poucas categorias (IA × humano, 6 degraus de funil, 2 coortes) e barra horizontal com o
 * número ao lado resolve todas — `div` + largura em %. `recharts` custaria ~500 kB e um
 * `npm install` no build que já quebrou uma vez (FIX_FRONTEND_CHUNK_404_20260825).
 *
 * AS CINCO SEÇÕES CARREGAM INDEPENDENTES. Uma seção lenta não segura as outras, e uma
 * seção quebrada aparece quebrada — com o motivo — em vez de derrubar a página.
 */

import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle, BarChart3, Info, Loader2, RefreshCw, Users, Clock,
  CalendarCheck, HeartPulse, Route, Ban,
} from 'lucide-react';
import AppLayout from '@/components/AppLayout';
import { useAuth } from '@/contexts/auth-context';
import api from '@/lib/api';

// ── contrato do backend (app/relatorios.py) ────────────────────────────────────────────
type Confianca = 'alta' | 'media' | 'baixa' | 'indisponivel' | 'nao_medivel';

interface Metrica {
  id: string;
  rotulo: string;
  valor: unknown;
  n: unknown;
  relogio: string;
  confianca: Confianca;
  definicao: string;
  limitacao: string | null;
  unidade?: string;
  quebra?: Record<string, number>;
  cobertura?: Record<string, unknown>;
  lista?: Record<string, unknown>[];
  por_consultora?: Record<string, { agendou: number; em_vendas: number; vendido: number }>;
  comparacao_ressalvada?: boolean;
  ignora_periodo?: boolean;
}

interface Secao {
  secao: string;
  periodo: { de: string; ate: string; dias: number; rotulo: string } | null;
  apurado_em: string;
  metricas: Metrica[];
  tabela?: Record<string, unknown>[];
  leads_de_teste?: { excluidos: number; duvidosos: { nome: string }[] };
  erro?: { tipo: string; mensagem: string };
}

const PERIODOS = [
  { chave: 'hoje', rotulo: 'Hoje' },
  { chave: '7d', rotulo: '7 dias' },
  { chave: '30d', rotulo: '30 dias' },
];

const ROTAS = ['resumo', 'ia', 'humano', 'atritos', 'jornada'] as const;
type Rota = (typeof ROTAS)[number];

// ── helpers de formatação ───────────────────────────────────────────────────────────────
const num = (v: unknown) => (typeof v === 'number' ? v.toLocaleString('pt-BR') : String(v ?? '—'));

/** Segundos em algo que se lê. 3,7 s · 23 min · 2 h 37. Nunca "9455.19". */
function duracao(seg: number | null | undefined): string {
  if (seg === null || seg === undefined) return '—';
  if (seg < 60) return `${seg.toFixed(1).replace('.', ',')} s`;
  if (seg < 3600) return `${Math.round(seg / 60)} min`;
  const h = Math.floor(seg / 3600);
  return `${h} h ${Math.round((seg % 3600) / 60)}`;
}

function pct(v: unknown, n: unknown): string | null {
  if (typeof v !== 'number' || typeof n !== 'number' || n === 0) return null;
  return `${Math.round((v / n) * 100)}%`;
}

function quando(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit',
                                     minute: '2-digit' });
}

// ── peças ───────────────────────────────────────────────────────────────────────────────
function Dica({ texto }: { texto: string }) {
  return (
    <span title={texto} className="inline-flex align-middle cursor-help text-gray-300
                                   hover:text-[#2A658F] transition-colors">
      <Info className="w-3.5 h-3.5" />
    </span>
  );
}

/** `limitacao` é TEXTO VISÍVEL, não tooltip. É a diferença entre a gestora ler o número
 *  certo e ler o número certo entendendo o que ele não diz. */
function Ressalva({ texto, tom = 'ambar' }: { texto: string; tom?: 'ambar' | 'cinza' }) {
  const cor = tom === 'ambar'
    ? 'bg-amber-50 text-amber-800 border-amber-100'
    : 'bg-gray-50 text-gray-500 border-gray-100';
  return (
    <p className={`text-[11.5px] leading-relaxed border rounded-lg px-2.5 py-2 mt-3 ${cor}`}>
      {texto}
    </p>
  );
}

/** O estado visual próprio do "não medível": cinza, sem barra, sem número. */
function NaoMedivel({ m }: { m: Metrica }) {
  return (
    <div className="bg-white rounded-2xl p-5 border border-dashed border-gray-200">
      <div className="flex items-center gap-2 mb-2">
        <Ban className="w-4 h-4 text-gray-300" />
        <p className="text-[13px] font-medium text-gray-500">{m.rotulo}</p>
      </div>
      <p className="text-[15px] font-semibold text-gray-400">não medível</p>
      <p className="text-[11.5px] text-gray-500 leading-relaxed mt-2">{m.limitacao}</p>
    </div>
  );
}

function Card({ m }: { m: Metrica }) {
  if (m.confianca === 'nao_medivel') return <NaoMedivel m={m} />;
  const p = pct(m.valor, m.n);
  const indisp = m.confianca === 'indisponivel' && m.valor === null;
  return (
    <div className="bg-white rounded-2xl p-5 border border-gray-100">
      <div className="flex items-start justify-between gap-2 mb-3">
        <p className="text-[13px] text-gray-500 leading-snug">{m.rotulo}</p>
        <Dica texto={`${m.definicao}\n\nRelógio: ${m.relogio}`} />
      </div>
      {indisp ? (
        <p className="text-[15px] font-semibold text-gray-400">ainda sem dado</p>
      ) : (
        <>
          <p className="text-[26px] leading-none font-bold text-[#27273D] tabular-nums">
            {num(m.valor)}
          </p>
          {typeof m.n === 'number' && (
            <p className="text-[12px] text-gray-400 mt-1.5 tabular-nums">
              de {num(m.n)}{p ? ` · ${p}` : ''}{m.unidade ? ` ${m.unidade}` : ''}
            </p>
          )}
        </>
      )}
      {m.limitacao && <Ressalva texto={m.limitacao} />}
    </div>
  );
}

/** Barra horizontal: `div` + largura em %. É tudo que este painel precisa. */
function Barras({ itens, total, cor = 'bg-[#2A658F]' }: {
  itens: { rotulo: string; n: number; nota?: string }[];
  total: number;
  cor?: string;
}) {
  const base = Math.max(total, 1);
  return (
    <div className="space-y-3">
      {itens.map((it) => {
        const p = (it.n / base) * 100;
        return (
          <div key={it.rotulo}>
            <div className="flex items-baseline justify-between mb-1">
              <span className="text-[12.5px] text-gray-600">{it.rotulo}</span>
              <span className="text-[12.5px] tabular-nums">
                <span className="font-semibold text-[#27273D]">{it.n}</span>
                <span className="text-gray-400"> · {Math.round(p)}%</span>
              </span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div className={`h-full ${cor} rounded-full transition-all duration-500`}
                   style={{ width: `${Math.max(p, it.n > 0 ? 3 : 0)}%` }} />
            </div>
            {it.nota && <p className="text-[11px] text-gray-400 mt-1">{it.nota}</p>}
          </div>
        );
      })}
    </div>
  );
}

function Bloco({ titulo, icone: Icone, sub, children }: {
  titulo: string; icone: React.ElementType; sub?: string; children: React.ReactNode;
}) {
  return (
    <section className="bg-white rounded-2xl p-6 border border-gray-100">
      <div className="flex items-start gap-3 mb-5">
        <div className="w-9 h-9 bg-[#2A658F]/8 rounded-lg flex items-center justify-center
                        flex-shrink-0">
          <Icone className="w-4 h-4 text-[#2A658F]" />
        </div>
        <div>
          <h2 className="text-[15px] font-semibold text-[#27273D]">{titulo}</h2>
          {sub && <p className="text-[12px] text-gray-400 mt-0.5">{sub}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

function Quebrada({ nome, erro, aoTentar }: {
  nome: string; erro: { tipo: string; mensagem: string }; aoTentar: () => void;
}) {
  return (
    <section className="bg-white rounded-2xl p-6 border border-red-100">
      <div className="flex items-start gap-3">
        <AlertTriangle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
        <div className="flex-1">
          <h2 className="text-[15px] font-semibold text-[#27273D]">
            A seção “{nome}” não carregou
          </h2>
          <p className="text-[12px] text-gray-500 mt-1">
            As outras continuam valendo. {erro.tipo}: {erro.mensagem}
          </p>
          <button onClick={aoTentar}
                  className="mt-3 text-[12px] text-[#2A658F] hover:underline
                             inline-flex items-center gap-1">
            <RefreshCw className="w-3 h-3" /> tentar de novo
          </button>
        </div>
      </div>
    </section>
  );
}

function Esqueleto() {
  return <div className="bg-white rounded-2xl border border-gray-100 h-[180px] animate-pulse" />;
}

// ── página ──────────────────────────────────────────────────────────────────────────────
export default function RelatoriosPage() {
  const { user, loading: authLoading } = useAuth();
  const [periodo, setPeriodo] = useState('30d');
  const [custom, setCustom] = useState({ de: '', ate: '' });
  const [dados, setDados] = useState<Partial<Record<Rota, Secao>>>({});
  const [carregando, setCarregando] = useState<Partial<Record<Rota, boolean>>>({});

  const carregar = useCallback(async (rota: Rota, p: string) => {
    setCarregando((c) => ({ ...c, [rota]: true }));
    try {
      const res = await api.get(`/relatorios/${rota}`, { params: { periodo: p } });
      setDados((d) => ({ ...d, [rota]: res.data }));
    } catch (e: unknown) {
      // A rota já devolve erro tratado em 200; isto cobre rede caída e 401/403.
      const msg = e instanceof Error ? e.message : 'falha de rede';
      setDados((d) => ({
        ...d,
        [rota]: { secao: rota, periodo: null, apurado_em: '', metricas: [],
                  erro: { tipo: 'Rede', mensagem: msg } },
      }));
    } finally {
      setCarregando((c) => ({ ...c, [rota]: false }));
    }
  }, []);

  // AS CINCO EM PARALELO. Nenhuma espera a anterior.
  useEffect(() => {
    if (!user) return;
    ROTAS.forEach((r) => carregar(r, periodo));
  }, [user, periodo, carregar]);

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#f8f9fb]">
        <Loader2 className="w-8 h-8 text-[#2A658F] animate-spin" />
      </div>
    );
  }
  if (!user) return null;

  const resumo = dados.resumo;
  const ia = dados.ia;
  const humano = dados.humano;
  const atritos = dados.atritos;
  const jornada = dados.jornada;

  const met = (s: Secao | undefined, id: string) => s?.metricas.find((m) => m.id === id);
  const apurado = resumo?.apurado_em ?? ia?.apurado_em;

  const aplicarCustom = () => {
    if (custom.de && custom.ate) setPeriodo(`${custom.de}:${custom.ate}`);
  };

  const funil = (m: Metrica | undefined) =>
    (Array.isArray(m?.valor) ? (m.valor as { rotulo: string; n: number }[]) : []);

  const mediana = met(humano, 'resposta_mediana');
  const medVal = (mediana?.valor ?? {}) as { ia?: number; humano?: number };
  const medN = (mediana?.n ?? {}) as { ia?: number; humano?: number };

  const sdr = met(humano, 'mensagens_por_sdr');
  const linhasSdr = (Array.isArray(sdr?.valor)
    ? (sdr.valor as { sdr: string; enviadas: number; pessoas: number }[]) : []);

  const vao = met(atritos, 'vao_espontaneo');
  const listaVao = (vao?.lista ?? []) as {
    nome: string | null; wa_id: string; escreveu: string; etapa: string | null }[];

  const agendaram = met(jornada, 'agendaram');
  const emVendas = met(jornada, 'chegou_em_vendas');
  const vendidos = met(jornada, 'vendidos_rastreaveis');
  const tabela = (jornada?.tabela ?? []) as {
    lead_id: number; nome: string; origem: string; consultora: string;
    funil: number; etapa: string; ultima_transicao: string | null }[];

  return (
    <AppLayout>
      <div className="space-y-6 max-w-7xl mx-auto overflow-y-auto h-full pb-10">

        {/* ── cabeçalho + seletor ── */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight">Relatórios</h1>
            <p className="text-[12.5px] text-gray-400 mt-1">
              Apurado em {quando(apurado)} · horário de São Paulo
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {PERIODOS.map((p) => (
              <button key={p.chave} onClick={() => setPeriodo(p.chave)}
                className={`px-3.5 py-1.5 rounded-lg text-[12.5px] font-medium transition-colors
                  ${periodo === p.chave
                    ? 'bg-[#2A658F] text-white'
                    : 'bg-white border border-gray-200 text-gray-600 hover:border-gray-300'}`}>
                {p.rotulo}
              </button>
            ))}
            <div className="flex items-center gap-1.5 bg-white border border-gray-200
                            rounded-lg px-2 py-1">
              <input type="date" value={custom.de}
                     onChange={(e) => setCustom({ ...custom, de: e.target.value })}
                     className="text-[12px] text-gray-600 outline-none w-[110px]" />
              <span className="text-gray-300">→</span>
              <input type="date" value={custom.ate}
                     onChange={(e) => setCustom({ ...custom, ate: e.target.value })}
                     className="text-[12px] text-gray-600 outline-none w-[110px]" />
              <button onClick={aplicarCustom} disabled={!custom.de || !custom.ate}
                      className="text-[12px] text-[#2A658F] disabled:text-gray-300 px-1">
                ok
              </button>
            </div>
          </div>
        </div>

        {/* ── o número que muda sozinho ── */}
        <div className="flex items-start gap-2 text-[12px] text-gray-500 bg-white border
                        border-gray-100 rounded-xl px-4 py-3">
          <Info className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-gray-300" />
          <p className="leading-relaxed">
            Alguns números contam <strong>quem ainda não foi atendido</strong>. Se alguém do
            time responder essas pessoas hoje, o número cai — mesmo você escolhendo o mesmo
            período. Por isso a hora da apuração fica no topo.
          </p>
        </div>

        {/* ── RESUMO ── */}
        {resumo?.erro
          ? <Quebrada nome="Resumo" erro={resumo.erro} aoTentar={() => carregar('resumo', periodo)} />
          : !resumo ? <Esqueleto /> : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
              {resumo.metricas.map((m) => <Card key={m.id} m={m} />)}
            </div>
          )}

        {/* ── FUNIL POR COORTE ── */}
        {ia?.erro
          ? <Quebrada nome="Nat" erro={ia.erro} aoTentar={() => carregar('ia', periodo)} />
          : !ia ? <Esqueleto /> : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {['funil_t1_t2', 'funil_t3'].map((id) => {
                const m = met(ia, id)!;
                const passos = funil(m);
                return (
                  <Bloco key={id} titulo={m.rotulo} icone={BarChart3}
                         sub={`${m.n} pessoas receberam a abertura`}>
                    <Barras itens={passos} total={passos[0]?.n ?? 0}
                            cor={id === 'funil_t3' ? 'bg-amber-500' : 'bg-[#2A658F]'} />
                    <p className="text-[11px] text-gray-400 mt-3">
                      Base de todos os degraus: quem recebeu a abertura ({num(m.n)}).
                      <span className="ml-1"><Dica texto={m.definicao} /></span>
                    </p>
                    {m.limitacao && <Ressalva texto={m.limitacao} />}
                  </Bloco>
                );
              })}
            </div>
          )}

        {/* ── SAÚDE: fora da área do seletor, com rótulo fixo ── */}
        {ia && !ia.erro && (
          <Bloco titulo="Saúde da Nat" icone={HeartPulse}
                 sub="situação AGORA — este bloco não muda com o período escolhido">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-3">
                {['saude_silencio', 'saude_sem_resposta_agente', 'saude_vigias_disparados']
                  .map((id) => {
                    const m = met(ia, id);
                    if (!m) return null;
                    const zero = m.valor === 0;
                    return (
                      <div key={id} className="flex items-center justify-between gap-3 border-b
                                               border-gray-50 pb-2.5">
                        <span className="text-[12.5px] text-gray-600">
                          {m.rotulo} <Dica texto={`${m.definicao}\n\nRelógio: ${m.relogio}`} />
                        </span>
                        <span className={`text-[13px] font-semibold tabular-nums
                          ${zero ? 'text-emerald-600' : 'text-amber-600'}`}>
                          {num(m.valor)} {zero ? '✓' : '⚠'}
                        </span>
                      </div>
                    );
                  })}
                {met(ia, 'saude_silencio')?.limitacao &&
                  <Ressalva tom="cinza" texto={met(ia, 'saude_silencio')!.limitacao!} />}
              </div>
              <div>
                <p className="text-[12px] text-gray-400 mb-3">Como as conversas terminam</p>
                <Barras
                  itens={((met(ia, 'saude_motivos')?.valor ?? []) as
                          { tipo: string; motivo: string; n: number }[])
                          .slice(0, 6).map((x) => ({ rotulo: x.motivo, n: x.n }))}
                  total={(met(ia, 'saude_motivos')?.n as number) ?? 1}
                  cor="bg-purple-400" />
              </div>
            </div>
          </Bloco>
        )}

        {/* ── HUMANO ── */}
        {humano?.erro
          ? <Quebrada nome="Time" erro={humano.erro}
                      aoTentar={() => carregar('humano', periodo)} />
          : !humano ? <Esqueleto /> : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <Bloco titulo="Tempo até responder" icone={Clock}
                     sub="mediana, não média">
                <div className="grid grid-cols-2 gap-4">
                  {(['ia', 'humano'] as const).map((quem) => (
                    <div key={quem} className="bg-gray-50/60 rounded-xl p-4">
                      <p className="text-[12px] text-gray-500 mb-1">
                        {quem === 'ia' ? 'Nat' : 'Time'}
                      </p>
                      <p className="text-[22px] font-bold text-[#27273D] tabular-nums">
                        {duracao(medVal[quem])}
                      </p>
                      <p className="text-[11.5px] text-gray-400 mt-1 tabular-nums">
                        N = {medN[quem] ?? 0} respostas
                      </p>
                    </div>
                  ))}
                </div>
                {mediana?.limitacao && <Ressalva texto={mediana.limitacao} />}
              </Bloco>

              <Bloco titulo={sdr?.rotulo ?? 'Mensagens por pessoa do time'} icone={Users}>
                {sdr?.limitacao && <Ressalva texto={sdr.limitacao} />}
                {linhasSdr.length > 0 ? (
                  <div className="mt-4">
                    <Barras itens={linhasSdr.map((l) => ({
                      rotulo: l.sdr, n: l.enviadas,
                      nota: `${l.pessoas} pessoa(s) alcançada(s)` }))}
                      total={Math.max(...linhasSdr.map((l) => l.enviadas))}
                      cor="bg-emerald-500" />
                  </div>
                ) : (
                  // Gráfico vazio lê-se como "ninguém trabalhou". Some, e sobra o aviso.
                  <p className="text-[12px] text-gray-400 mt-3">
                    Sem gráfico: não há dado atribuível no período escolhido.
                  </p>
                )}
              </Bloco>
            </div>
          )}

        {/* ── ATRITOS ── */}
        {atritos?.erro
          ? <Quebrada nome="Atritos" erro={atritos.erro}
                      aoTentar={() => carregar('atritos', periodo)} />
          : !atritos ? <Esqueleto /> : (
            <Bloco titulo="Atritos" icone={AlertTriangle}
                   sub="onde o atendimento se atropela ou some">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {atritos.metricas.map((m) => <Card key={m.id} m={m} />)}
              </div>
              {listaVao.length > 0 && (
                <div className="mt-5">
                  <p className="text-[12px] text-gray-400 mb-2">
                    Quem escreveu e não recebeu resposta — {listaVao.length} pessoa(s)
                  </p>
                  <div className="overflow-x-auto border border-gray-100 rounded-xl">
                    <table className="w-full text-[12px]">
                      <thead className="bg-gray-50/70 text-gray-500">
                        <tr>
                          <th className="text-left font-medium px-3 py-2">Nome</th>
                          <th className="text-left font-medium px-3 py-2">WhatsApp</th>
                          <th className="text-left font-medium px-3 py-2">Escreveu em</th>
                          <th className="text-left font-medium px-3 py-2">Situação hoje</th>
                        </tr>
                      </thead>
                      <tbody>
                        {listaVao.map((l) => (
                          <tr key={l.wa_id} className="border-t border-gray-50">
                            <td className="px-3 py-2 text-gray-700">{l.nome ?? '—'}</td>
                            <td className="px-3 py-2 text-gray-500 tabular-nums">{l.wa_id}</td>
                            <td className="px-3 py-2 text-gray-500 tabular-nums">
                              {quando(l.escreveu)}
                            </td>
                            <td className="px-3 py-2">
                              <span className={l.etapa === 'Vendidos'
                                ? 'text-emerald-600 font-medium' : 'text-gray-500'}>
                                {l.etapa ?? 'sem lead na Exact'}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </Bloco>
          )}

        {/* ── JORNADA ── */}
        {jornada?.erro
          ? <Quebrada nome="Jornada" erro={jornada.erro}
                      aoTentar={() => carregar('jornada', periodo)} />
          : !jornada ? <Esqueleto /> : (
            <Bloco titulo="Jornada do lead" icone={Route}
                   sub="da reunião marcada até a matrícula">
              {/* O aviso de cobertura vai EM CIMA do número, não embaixo. */}
              {vendidos?.limitacao && <Ressalva texto={vendidos.limitacao} />}

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4">
                {[
                  { m: agendaram, rot: 'Agendaram', icone: CalendarCheck },
                  { m: emVendas, rot: 'Foram para vendas', icone: Route },
                ].map(({ m, rot }) => {
                  const v = (m?.valor ?? {}) as { ia?: number; landing_page?: number };
                  return (
                    <div key={rot} className="bg-white rounded-2xl p-5 border border-gray-100">
                      <div className="flex items-start justify-between gap-2 mb-3">
                        <p className="text-[13px] text-gray-500">{rot}</p>
                        {m && <Dica texto={`${m.definicao}\n\nRelógio: ${m.relogio}`} />}
                      </div>
                      <p className="text-[26px] leading-none font-bold text-[#27273D]
                                    tabular-nums">{num(m?.n)}</p>
                      <p className="text-[12px] text-gray-400 mt-2 tabular-nums">
                        Nat {v.ia ?? 0} · página de obrigado {v.landing_page ?? 0}
                      </p>
                    </div>
                  );
                })}
                {vendidos && (
                  <div className="bg-white rounded-2xl p-5 border border-gray-100">
                    <div className="flex items-start justify-between gap-2 mb-3">
                      <p className="text-[13px] text-gray-500">{vendidos.rotulo}</p>
                      <Dica texto={`${vendidos.definicao}\n\nRelógio: ${vendidos.relogio}`} />
                    </div>
                    <p className="text-[26px] leading-none font-bold text-[#27273D]
                                  tabular-nums">{num(vendidos.valor)}</p>
                    <p className="text-[12px] text-gray-400 mt-2">
                      vendas com origem rastreável
                    </p>
                  </div>
                )}
              </div>

              {agendaram?.por_consultora && (
                <div className="mt-6">
                  <p className="text-[12px] text-gray-400 mb-2">Por consultora</p>
                  <div className="overflow-x-auto border border-gray-100 rounded-xl">
                    <table className="w-full text-[12px]">
                      <thead className="bg-gray-50/70 text-gray-500">
                        <tr>
                          <th className="text-left font-medium px-3 py-2">Consultora</th>
                          <th className="text-right font-medium px-3 py-2">Agendou</th>
                          <th className="text-right font-medium px-3 py-2">Em vendas</th>
                          <th className="text-right font-medium px-3 py-2">Vendido</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(agendaram.por_consultora).map(([email, c]) => (
                          <tr key={email} className="border-t border-gray-50">
                            <td className="px-3 py-2 text-gray-700">{email}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{c.agendou}</td>
                            <td className="px-3 py-2 text-right tabular-nums">{c.em_vendas}</td>
                            <td className="px-3 py-2 text-right tabular-nums font-medium
                                           text-emerald-700">{c.vendido}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {/* Contagem absoluta, nunca taxa: N por ator não sustenta percentual. */}
                  <p className="text-[11px] text-gray-400 mt-2">
                    Contagem absoluta, sem taxa de conversão: o número de reuniões por ator
                    ainda é pequeno demais para um percentual significar alguma coisa.
                  </p>
                </div>
              )}

              {tabela.length > 0 && (
                <div className="mt-6">
                  <p className="text-[12px] text-gray-400 mb-2">
                    As {tabela.length} pessoas que agendaram, uma a uma — as contagens dizem
                    que o sistema funciona; esta lista diz quem ligar hoje.
                  </p>
                  <div className="overflow-x-auto border border-gray-100 rounded-xl
                                  max-h-[420px] overflow-y-auto">
                    <table className="w-full text-[12px]">
                      <thead className="bg-gray-50/70 text-gray-500 sticky top-0">
                        <tr>
                          <th className="text-left font-medium px-3 py-2">Nome</th>
                          <th className="text-left font-medium px-3 py-2">Origem</th>
                          <th className="text-left font-medium px-3 py-2">Consultora</th>
                          <th className="text-left font-medium px-3 py-2">Situação hoje</th>
                          <th className="text-left font-medium px-3 py-2">Última transição</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tabela.map((l) => (
                          <tr key={l.lead_id} className="border-t border-gray-50">
                            <td className="px-3 py-2 text-gray-700">{l.nome}</td>
                            <td className="px-3 py-2">
                              <span className={`px-1.5 py-0.5 rounded-md text-[11px] ${
                                l.origem === 'ia'
                                  ? 'bg-[#2A658F]/10 text-[#2A658F]'
                                  : 'bg-gray-100 text-gray-500'}`}>
                                {l.origem === 'ia' ? 'Nat' : 'página'}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-gray-500">
                              {(l.consultora ?? '').split('@')[0]}
                            </td>
                            <td className="px-3 py-2">
                              <span className={l.etapa === 'Vendidos'
                                ? 'text-emerald-600 font-medium' : 'text-gray-600'}>
                                {l.etapa ?? '—'}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-gray-400 tabular-nums">
                              {quando(l.ultima_transicao)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </Bloco>
          )}

        {/* ── rodapé: o que ficou de fora do número ── */}
        {resumo?.leads_de_teste && (
          <p className="text-[11px] text-gray-400 leading-relaxed px-1">
            {resumo.leads_de_teste.excluidos} telefones de teste foram excluídos destes
            números.
            {resumo.leads_de_teste.duvidosos.length > 0 && (
              <> Em dúvida, e <strong>mantido(s) na conta</strong> de propósito:{' '}
                {resumo.leads_de_teste.duvidosos.map((d) => d.nome).join(', ')} — o nome
                parece de teste, mas a conversa parece real. Um lead de teste que escapa
                polui um número de leve; uma pessoa real excluída some de tudo, sem sintoma.
              </>
            )}
          </p>
        )}

        {Object.values(carregando).some(Boolean) && (
          <p className="text-[11px] text-gray-300 flex items-center gap-1.5 px-1">
            <Loader2 className="w-3 h-3 animate-spin" /> atualizando…
          </p>
        )}
      </div>
    </AppLayout>
  );
}
