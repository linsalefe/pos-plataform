'use client';

/**
 * Mediana e % no SLA, por dia (ou hora do dia). DOIS PAINÉIS e não um gráfico de dois
 * eixos: minutos e porcentagem em escalas sobrepostas fazem o cruzamento das linhas parecer
 * significativo quando é só a escolha das escalas. Mesmo eixo X nos dois, um embaixo do outro.
 */
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis,
         YAxis } from 'recharts';
import Dica from './Dica';
import { COR, duracao, rotuloChave, type LinhaSerie, type Relogio } from './tipos';

const TETO_H = 48;

export default function SerieChart({ linhas, relogio }: { linhas: LinhaSerie[]; relogio: Relogio }) {
  const dados = linhas.map((l) => ({
    rotulo: rotuloChave(l.chave),
    mediana: l[relogio].mediana === null ? null : Math.round((l[relogio].mediana as number) / 360) / 10,
    pct: l[relogio].pct_sla,
    n: l[relogio].vencidas,
  }));
  const temDado = dados.some((d) => d.mediana !== null || d.pct !== null);
  if (!temDado) {
    return <p className="text-[12.5px] text-gray-400 py-10 text-center">Nenhuma pergunta respondida no período.</p>;
  }
  // Um dia com mediana de 290 h achatava todos os outros contra o zero. O eixo vai até
  // TETO_H e os dias acima dele são ditos por extenso, não escondidos.
  const acima = dados.filter((d) => d.mediana !== null && d.mediana > TETO_H);
  const eixoX = (
    <XAxis dataKey="rotulo" tick={{ fontSize: 11, fill: COR.eixo }} tickLine={false}
           axisLine={{ stroke: COR.grade }} interval="preserveStartEnd" minTickGap={16} />
  );
  return (
    <div className="space-y-4">
      <div>
        <p className="text-[12px] text-gray-500 mb-1">
          Mediana do tempo de resposta (horas) <span className="text-gray-400">· tracejado: SLA de 2 h</span>
        </p>
        <div className="h-[170px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={dados} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={COR.grade} vertical={false} />
              {eixoX}
              <YAxis tick={{ fontSize: 11, fill: COR.eixo }} tickLine={false} axisLine={false} width={44}
                     domain={acima.length ? [0, TETO_H] : [0, 'auto']} allowDataOverflow
                     tickFormatter={(v: number) => `${v} h`} />
              <ReferenceLine y={2} stroke={COR.eixo} strokeDasharray="4 4" />
              <Tooltip content={<Dica formatar={(v) => duracao(v * 3600)} />} />
              <Line type="monotone" dataKey="mediana" name="Mediana" stroke={COR.marca} strokeWidth={2}
                    dot={{ r: 3, strokeWidth: 0, fill: COR.marca }} activeDot={{ r: 5 }} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        {acima.length > 0 && (
          <p className="text-[11px] text-gray-400 mt-1">
            Eixo limitado a {TETO_H} h. Acima disso: {acima.map((d) => `${d.rotulo} (${duracao((d.mediana as number) * 3600)})`).join(', ')}.
          </p>
        )}
      </div>
      <div>
        <p className="text-[12px] text-gray-500 mb-1">Respondidas em até 2 h (%)</p>
        <div className="h-[170px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={dados} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={COR.grade} vertical={false} />
              {eixoX}
              <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fontSize: 11, fill: COR.eixo }}
                     tickLine={false} axisLine={false} width={44}
                     tickFormatter={(v: number) => `${v}%`} />
              <Tooltip content={<Dica formatar={(v) => `${v.toLocaleString('pt-BR')}%`} />} />
              <Line type="monotone" dataKey="pct" name="No SLA" stroke={COR.noSla} strokeWidth={2}
                    dot={{ r: 3, strokeWidth: 0, fill: COR.noSla }} activeDot={{ r: 5 }} connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
