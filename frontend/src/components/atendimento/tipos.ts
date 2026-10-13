/**
 * Contrato de `backend/app/atendimento_routes.py`. Definições e limitações vêm do backend
 * e vão para a tela como estão: uma fonte só, igual à página de Relatórios.
 */

export type Relogio = 'corrido' | 'expediente';
export type Quem = 'time' | 'ia' | 'ambos';
export type EstadoJanela = 'aberta' | 'perto' | 'expirada';

export interface Variacao {
  anterior: number | null;
  delta: number | null;
  pct: number | null;
}

export interface Sla {
  mediana: number | null;
  no_sla: number;
  fora_sla: number;
  vencidas: number;
  pct_sla: number | null;
}

export interface Periodo {
  de: string;
  ate: string;
  dias: number;
  rotulo: string;
}

export interface Erro {
  tipo: string;
  mensagem: string;
}

export interface Metrica {
  id: string;
  rotulo: string;
  valor: number | Record<Relogio, number | null> | null;
  n: number | Record<Relogio, number> | null;
  relogio: string;
  confianca: 'alta' | 'media' | 'baixa' | 'indisponivel' | 'nao_medivel';
  definicao: string;
  limitacao: string | null;
  unidade?: string;
  variacao?: Variacao | Record<Relogio, Variacao>;
  por_janela?: Record<EstadoJanela, number>;
}

export interface Cobertura {
  desde: string;
  confianca: string;
  aviso: string | null;
}

export interface FaixaHistograma {
  faixa: string;
  n: number;
}

export interface Resumo {
  periodo: Periodo | null;
  periodo_anterior?: Periodo;
  apurado_em: string;
  metricas: Metrica[];
  cobertura_sent_by?: Cobertura;
  nota_dono?: string;
  respondidas_por?: { ia: number; time: number };
  histograma?: Record<Relogio, FaixaHistograma[]>;
  leads_de_teste?: { excluidos: number };
  erro?: Erro;
}

export interface LinhaSerie {
  chave: string | number;
  perguntas: number;
  sem_resposta: number;
  so_template: number;
  corrido: Sla;
  expediente: Sla;
}

export interface Serie {
  periodo: Periodo | null;
  linhas?: LinhaSerie[];
  nota?: string;
  definicao?: string;
  erro?: Erro;
}

export interface LinhaSdr {
  sdr_id: number | null;
  sdr: string;
  perguntas: number;
  respondidas: number;
  respondeu_pessoalmente: number;
  janelas_perdidas: number;
  corrido: Sla;
  expediente: Sla;
  sem_resposta_agora: number;
}

export interface PorSdr {
  periodo: Periodo | null;
  linhas?: LinhaSdr[];
  definicao?: string;
  nota_dono?: string;
  cobertura_sent_by?: Cobertura;
  erro?: Erro;
}

export interface Pendente {
  wa_id: string;
  nome: string | null;
  dono_inbound: 'sdr' | 'agente' | 'regua';
  dono_detalhe: string | null;
  sdr_id: number | null;
  sdr_nome: string;
  esperando_desde: string;
  ultimo_inb: string;
  horas_esperando: number;
  janela: EstadoJanela;
  janela_fecha_em: string;
  ultima_msg: string;
  so_template: boolean;
  primeira_sem_resposta: string;
  anomalia: boolean;
}

export interface Pendentes {
  apurado_em: string;
  total?: number;
  por_janela?: Record<EstadoJanela, number>;
  ocultos_automacao?: number;
  itens?: Pendente[];
  definicao?: string;
  erro?: Erro;
}

// ── cores: as do Hub, mais o trio de estado validado (CVD e visão normal) ─────────────
export const COR = {
  marca: '#2A658F',
  tinta: '#27273D',
  grade: '#eef0f3',
  eixo: '#9ca3af',
  noSla: '#047857',
  foraSla: '#f59e0b',
  semResposta: '#be123c',
  foraDoSla: '#cbd5e1',
} as const;

// ── formatação ─────────────────────────────────────────────────────────────────────────
/** Segundos em algo que se lê: 42 s · 23 min · 5 h 11. Nunca "18662.78". */
export function duracao(seg: number | null | undefined): string {
  if (seg === null || seg === undefined) return '—';
  if (seg < 60) return `${Math.round(seg)} s`;
  // Arredonda o TOTAL de minutos antes de quebrar em horas: 5 h 59,6 min vira 6 h, não "5 h 60".
  const total = Math.round(seg / 60);
  if (total < 60) return `${total} min`;
  const h = Math.floor(total / 60);
  if (h >= 48) return `${Math.round(h / 24)} d`;
  const m = total % 60;
  return m ? `${h} h ${String(m).padStart(2, '0')}` : `${h} h`;
}

export function horas(h: number): string {
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${Math.floor(h)} h`;
  return `${Math.floor(h / 24)} d ${Math.floor(h % 24)} h`;
}

/** ISO naive em SP para "13/10 14:05". O texto já é SP: não passa por `Date` (fuso). */
export function quando(iso: string | null | undefined): string {
  if (!iso) return '—';
  const [d, t = ''] = iso.split('T');
  const [, mes, dia] = d.split('-');
  return `${dia}/${mes}${t ? ` ${t.slice(0, 5)}` : ''}`;
}

/** Chave da série: '2026-10-07' vira '07/10'; hora 9 vira '9h'. */
export function rotuloChave(c: string | number): string {
  if (typeof c === 'number') return `${c}h`;
  const [, mes, dia] = c.split('-');
  return `${dia}/${mes}`;
}

export const num = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : v.toLocaleString('pt-BR');

export const pctTxt = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${v.toLocaleString('pt-BR')}%`;
