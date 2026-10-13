'use client';

/**
 * Atendimento: como o time responde os leads (pedido da Isa, 13/10/2026). Somente leitura.
 *
 * As definições são as de /relatorios/humano (backend: app/atendimento_routes.py) e chegam
 * no JSON; esta tela não reescreve nenhuma. Três rotas dependem do período (resumo, série,
 * por SDR) e carregam em paralelo; a lista de pendentes é "agora" e se atualiza sozinha.
 *
 * O toggle "corrido / expediente" não refaz chamada: o backend devolve as duas leituras do
 * SLA no mesmo JSON.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, BarChart3, Clock, Info, Loader2, RefreshCw, Timer, Users } from 'lucide-react';
import AppLayout from '@/components/AppLayout';
import { useAuth } from '@/contexts/auth-context';
import api from '@/lib/api';
import KpiCard from '@/components/atendimento/KpiCard';
import SerieChart from '@/components/atendimento/SerieChart';
import SlaBarChart from '@/components/atendimento/SlaBarChart';
import HistogramaResposta from '@/components/atendimento/HistogramaResposta';
import TabelaSdr from '@/components/atendimento/TabelaSdr';
import ListaPendentes from '@/components/atendimento/ListaPendentes';
import {
  duracao, num, pctTxt, quando,
  type Erro, type Metrica, type PorSdr, type Quem, type Relogio, type Resumo, type Serie, type Variacao,
} from '@/components/atendimento/tipos';

const PERIODOS = [
  { chave: '7d', rotulo: '7 dias' },
  { chave: '14d', rotulo: '14 dias' },
  { chave: '30d', rotulo: '30 dias' },
  { chave: '90d', rotulo: '90 dias' },
];

const QUEM: { chave: Quem; rotulo: string; dica: string }[] = [
  { chave: 'time', rotulo: 'Time', dica: 'Perguntas que eram do time responder' },
  { chave: 'ia', rotulo: 'IA', dica: 'Perguntas que eram do agente ou da régua' },
  { chave: 'ambos', rotulo: 'Ambos', dica: 'Todas as perguntas' },
];

function Toggle<T extends string>({ opcoes, valor, aoMudar }: {
  opcoes: { chave: T; rotulo: string; dica?: string }[]; valor: T; aoMudar: (v: T) => void;
}) {
  return (
    <div className="inline-flex bg-white border border-gray-200 rounded-lg p-0.5">
      {opcoes.map((o) => (
        <button key={o.chave} onClick={() => aoMudar(o.chave)} title={o.dica}
                className={`px-3 py-1 rounded-md text-[12.5px] font-medium transition-colors ${
                  valor === o.chave ? 'bg-[#2A658F] text-white' : 'text-gray-600 hover:text-[#27273D]'}`}>
          {o.rotulo}
        </button>
      ))}
    </div>
  );
}

function Bloco({ titulo, sub, icone: Icone, children, acao }: {
  titulo: string; sub?: string; icone: React.ElementType; children: React.ReactNode; acao?: React.ReactNode;
}) {
  return (
    <section className="bg-white rounded-2xl p-5 border border-gray-100 min-w-0">
      <div className="flex items-start gap-3 mb-4">
        <div className="w-8 h-8 bg-[#2A658F]/8 rounded-lg flex items-center justify-center flex-shrink-0">
          <Icone className="w-4 h-4 text-[#2A658F]" />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-[14.5px] font-semibold text-[#27273D]">{titulo}</h2>
          {sub && <p className="text-[11.5px] text-gray-400 mt-0.5">{sub}</p>}
        </div>
        {acao}
      </div>
      {children}
    </section>
  );
}

function Quebrada({ nome, erro, aoTentar }: { nome: string; erro: Erro; aoTentar: () => void }) {
  return (
    <section className="bg-white rounded-2xl p-5 border border-rose-100 flex items-start gap-3">
      <AlertTriangle className="w-4 h-4 text-rose-600 mt-0.5 flex-shrink-0" />
      <div>
        <p className="text-[13.5px] font-semibold text-[#27273D]">“{nome}” não carregou</p>
        <p className="text-[12px] text-gray-500 mt-1">{erro.tipo}: {erro.mensagem}</p>
        <button onClick={aoTentar} className="mt-2 text-[12px] text-[#2A658F] hover:underline inline-flex items-center gap-1">
          <RefreshCw className="w-3 h-3" /> tentar de novo
        </button>
      </div>
    </section>
  );
}

const Esqueleto = ({ h = 'h-[140px]' }: { h?: string }) =>
  <div className={`bg-white rounded-2xl border border-gray-100 ${h} animate-pulse`} />;

type Rota = 'resumo' | 'serie' | 'sdr';

export default function AtendimentoPage() {
  const { user } = useAuth();
  const [periodo, setPeriodo] = useState('30d');
  const [custom, setCustom] = useState({ de: '', ate: '' });
  const [sdr, setSdr] = useState<number | null>(null);
  const [quem, setQuem] = useState<Quem>('time');
  const [relogio, setRelogio] = useState<Relogio>('corrido');
  const [granularidade, setGranularidade] = useState<'dia' | 'hora'>('dia');
  const [usuarios, setUsuarios] = useState<{ id: number; name: string }[]>([]);
  const [resumo, setResumo] = useState<Resumo | null>(null);
  const [serie, setSerie] = useState<Serie | null>(null);
  const [porSdr, setPorSdr] = useState<PorSdr | null>(null);

  const admin = user?.role === 'admin';

  const carregar = useCallback(async (rota: Rota) => {
    const filtros = { periodo, quem, ...(sdr !== null ? { sdr } : {}) };
    const params = rota === 'sdr' ? { periodo } : rota === 'serie' ? { ...filtros, granularidade } : filtros;
    const set = { resumo: setResumo, serie: setSerie, sdr: setPorSdr }[rota] as
      (v: Resumo | Serie | PorSdr | null) => void;
    set(null);
    try {
      const res = await api.get(`/atendimento/${rota}`, { params });
      set(res.data);
    } catch (e: unknown) {
      set({ periodo: null, apurado_em: '', metricas: [],
            erro: { tipo: 'Rede', mensagem: e instanceof Error ? e.message : 'falha de rede' } });
    }
  }, [periodo, quem, sdr, granularidade]);

  useEffect(() => { if (admin) carregar('resumo'); }, [admin, carregar]);
  useEffect(() => { if (admin) carregar('serie'); }, [admin, carregar]);
  useEffect(() => { if (admin) carregar('sdr'); }, [admin, periodo]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!admin) return;
    api.get('/auth/users').then((r) => setUsuarios(r.data)).catch(() => setUsuarios([]));
  }, [admin]);

  if (user && !admin) {
    return (
      <AppLayout>
        <p className="text-[13px] text-gray-500">Esta página é da gestão (administradores).</p>
      </AppLayout>
    );
  }

  const met = (id: string): Metrica | undefined => resumo?.metricas.find((m) => m.id === id);
  const porRelogio = <T,>(v: unknown): T | null =>
    v && typeof v === 'object' ? ((v as Record<Relogio, T>)[relogio] ?? null) : null;

  const semResp = met('sem_resposta_agora');
  const mediana = met('mediana');
  const sla = met('pct_sla');
  const janelas = met('janelas_perdidas');
  const taxa = met('taxa_resposta');
  const pj = semResp?.por_janela;

  const aplicarCustom = () => { if (custom.de && custom.ate) setPeriodo(`${custom.de}:${custom.ate}`); };
  const nomeSdr = usuarios.find((u) => u.id === sdr)?.name;
  const cob = resumo?.cobertura_sent_by;

  return (
    <AppLayout>
      <div className="space-y-5 overflow-y-auto h-full pb-10 pr-1">

        {/* ── linha 1: título e filtros ── */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight flex items-center gap-2">
              <Timer className="w-6 h-6 text-[#2A658F]" /> Atendimento
            </h1>
            <p className="text-[12.5px] text-gray-400 mt-1">
              {resumo?.periodo
                ? <>Período {quando(resumo.periodo.de)} a {quando(resumo.periodo.ate)} · apurado {quando(resumo.apurado_em)} · horário de São Paulo</>
                : 'Carregando…'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {PERIODOS.map((p) => (
              <button key={p.chave} onClick={() => setPeriodo(p.chave)}
                      className={`px-3 py-1.5 rounded-lg text-[12.5px] font-medium transition-colors ${
                        periodo === p.chave ? 'bg-[#2A658F] text-white'
                          : 'bg-white border border-gray-200 text-gray-600 hover:border-gray-300'}`}>
                {p.rotulo}
              </button>
            ))}
            <div className={`flex items-center gap-1.5 bg-white border rounded-lg px-2 py-1 ${
              periodo.includes(':') ? 'border-[#2A658F]' : 'border-gray-200'}`}>
              <input type="date" value={custom.de} onChange={(e) => setCustom({ ...custom, de: e.target.value })}
                     className="text-[12px] text-gray-600 outline-none w-[112px]" aria-label="De" />
              <span className="text-gray-300">→</span>
              <input type="date" value={custom.ate} onChange={(e) => setCustom({ ...custom, ate: e.target.value })}
                     className="text-[12px] text-gray-600 outline-none w-[112px]" aria-label="Até" />
              <button onClick={aplicarCustom} disabled={!custom.de || !custom.ate}
                      className="text-[12px] text-[#2A658F] disabled:text-gray-300 px-1">ok</button>
            </div>
            <select value={sdr ?? ''} onChange={(e) => setSdr(e.target.value ? Number(e.target.value) : null)}
                    className="bg-white border border-gray-200 rounded-lg px-2.5 py-1.5 text-[12.5px] text-gray-600 outline-none"
                    aria-label="SDR">
              <option value="">Todos os SDRs</option>
              {usuarios.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
            <Toggle opcoes={QUEM} valor={quem} aoMudar={setQuem} />
            <Toggle<Relogio> valor={relogio} aoMudar={setRelogio} opcoes={[
              { chave: 'corrido', rotulo: 'SLA corrido', dica: 'Relógio de 24 h' },
              { chave: 'expediente', rotulo: 'Expediente', dica: 'Só conta 8h às 20h30' },
            ]} />
          </div>
        </div>

        {/* ── avisos que mudam a leitura ── */}
        <div className="flex items-start gap-2 text-[12px] text-gray-500 bg-white border border-gray-100 rounded-xl px-4 py-3">
          <Info className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-gray-300" />
          <p className="leading-relaxed">
            <strong>Template não conta como resposta</strong> (disparo e follow são outra coisa), e ligação também não.
            {' '}{relogio === 'corrido'
              ? 'SLA em relógio corrido: pergunta às 23h respondida às 8h30 conta como fora.'
              : 'SLA em expediente: o relógio só anda das 8h às 20h30, todos os dias.'}
            {nomeSdr && <> Filtrado por <strong>{nomeSdr}</strong> (dono atual do contato).{' '}
              <button onClick={() => setSdr(null)} className="text-[#2A658F] hover:underline">limpar</button></>}
            {resumo?.nota_dono && <span className="block mt-1 text-gray-400">{resumo.nota_dono}</span>}
          </p>
        </div>
        {cob?.aviso && (
          <div className="flex items-start gap-2 text-[12px] text-amber-800 bg-amber-50 border border-amber-100 rounded-xl px-4 py-3">
            <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
            <p className="leading-relaxed">{cob.aviso}</p>
          </div>
        )}

        {/* ── linha 2: cartões ── */}
        {resumo?.erro ? <Quebrada nome="Resumo" erro={resumo.erro} aoTentar={() => carregar('resumo')} />
          : !resumo ? (
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">{[0, 1, 2, 3, 4].map((i) => <Esqueleto key={i} />)}</div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5 gap-4">
              {semResp && (
                <KpiCard rotulo="Sem resposta agora" valor={num(semResp.valor as number)}
                         destaque={pj && pj.expirada > 0 ? 'vermelho' : null}
                         definicao={semResp.definicao} limitacao={semResp.limitacao}
                         rodape={pj && (
                           <div className="flex gap-3 text-[11.5px] tabular-nums">
                             <span className="text-gray-500">{pj.aberta} abertas</span>
                             <span className="text-amber-700">{pj.perto} perto</span>
                             <span className="text-rose-700 font-medium">{pj.expirada} expiradas</span>
                           </div>
                         )} />
              )}
              {mediana && (
                <KpiCard rotulo="Tempo de resposta (mediana)"
                         valor={duracao(porRelogio<number>(mediana.valor))}
                         n={`${num(mediana.n as number)} respondidas`}
                         variacao={porRelogio<Variacao>(mediana.variacao)} melhor="desce"
                         definicao={mediana.definicao} limitacao={mediana.limitacao} />
              )}
              {sla && (
                <KpiCard rotulo="Respondidas em até 2 h" valor={pctTxt(porRelogio<number>(sla.valor))}
                         n={`de ${num(porRelogio<number>(sla.n))} com prazo vencido`}
                         variacao={porRelogio<Variacao>(sla.variacao)} melhor="sobe"
                         definicao={sla.definicao} limitacao={sla.limitacao} />
              )}
              {janelas && (
                <KpiCard rotulo="Janelas de 24 h perdidas" valor={num(janelas.valor as number)}
                         n={`de ${num(janelas.n as number)} perguntas`}
                         variacao={janelas.variacao as Variacao} melhor="desce"
                         definicao={janelas.definicao} limitacao={janelas.limitacao} />
              )}
              {taxa && (
                <KpiCard rotulo="Taxa de resposta" valor={pctTxt(taxa.valor as number | null)}
                         n={`de ${num(taxa.n as number)} perguntas`}
                         variacao={taxa.variacao as Variacao} melhor="sobe"
                         definicao={taxa.definicao} limitacao={taxa.limitacao} />
              )}
            </div>
          )}

        {/* ── linha 3: série e barras ── */}
        {serie?.erro ? <Quebrada nome="Série" erro={serie.erro} aoTentar={() => carregar('serie')} /> : (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Bloco titulo="Velocidade ao longo do tempo" icone={Clock}
                   sub={serie?.nota ?? 'Dia em que o lead perguntou'}
                   acao={<Toggle<'dia' | 'hora'> valor={granularidade} aoMudar={setGranularidade}
                                 opcoes={[{ chave: 'dia', rotulo: 'Por dia' }, { chave: 'hora', rotulo: 'Hora do dia' }]} />}>
              {!serie ? <Esqueleto h="h-[360px]" /> : <SerieChart linhas={serie.linhas ?? []} relogio={relogio} />}
            </Bloco>
            <Bloco titulo="O que aconteceu com cada pergunta" icone={BarChart3}
                   sub={granularidade === 'dia' ? 'Por dia em que o lead perguntou' : 'Por hora do dia em que o lead perguntou'}>
              {!serie ? <Esqueleto h="h-[360px]" /> : <SlaBarChart linhas={serie.linhas ?? []} relogio={relogio} />}
            </Bloco>
          </div>
        )}

        {/* ── linha 4: histograma e tabela por SDR ── */}
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">
          <div className="xl:col-span-2 min-w-0">
            <Bloco titulo="Quanto tempo levou cada resposta" icone={Timer}
                   sub={relogio === 'corrido' ? 'Relógio corrido' : 'Só horas de expediente'}>
              {!resumo ? <Esqueleto h="h-[260px]" />
                : <HistogramaResposta faixas={resumo.histograma?.[relogio] ?? []} />}
            </Bloco>
          </div>
          <div className="xl:col-span-3 min-w-0">
            {porSdr?.erro ? <Quebrada nome="Por SDR" erro={porSdr.erro} aoTentar={() => carregar('sdr')} /> : (
              <Bloco titulo="Por SDR" icone={Users}
                     sub="Perguntas do time, pelo dono atual do contato. Clique no nome para filtrar a página.">
                {!porSdr ? <Esqueleto h="h-[260px]" /> : (
                  <>
                    <TabelaSdr linhas={porSdr.linhas ?? []} relogio={relogio} aoEscolher={setSdr} />
                    {porSdr.cobertura_sent_by?.aviso && (
                      <p className="text-[11px] text-amber-800 bg-amber-50 rounded-lg px-2.5 py-2 mt-3">
                        {porSdr.cobertura_sent_by.aviso}
                      </p>
                    )}
                  </>
                )}
              </Bloco>
            )}
          </div>
        </div>

        {/* ── linha 5: a lista viva ── */}
        <Bloco titulo="Conversas sem resposta agora" icone={AlertTriangle}
               sub="Não depende do período. O lead falou por último e nenhuma mensagem nossa (fora template) veio depois.">
          {user ? <ListaPendentes quem={quem} sdr={sdr} />
            : <Loader2 className="w-5 h-5 text-[#2A658F] animate-spin" />}
        </Bloco>
      </div>
    </AppLayout>
  );
}
