'use client';

/**
 * Distribuição do tempo de resposta. As três primeiras faixas estão dentro do SLA de 2 h e
 * levam a cor da marca; as outras, cinza. A mediana esconde a cauda: é aqui que aparece.
 */
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis,
         YAxis } from 'recharts';
import Dica from './Dica';
import { COR, type FaixaHistograma } from './tipos';

const DENTRO = 3;   // até 15 min · 15 min a 1 h · 1 h a 2 h

export default function HistogramaResposta({ faixas }: { faixas: FaixaHistograma[] }) {
  const total = faixas.reduce((s, f) => s + f.n, 0);
  if (!total) {
    return <p className="text-[12.5px] text-gray-400 py-10 text-center">Nenhuma pergunta respondida no período.</p>;
  }
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 mb-2">
        <span className="inline-flex items-center gap-1.5 text-[11.5px] text-gray-600">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: COR.marca }} />dentro de 2 h
        </span>
        <span className="inline-flex items-center gap-1.5 text-[11.5px] text-gray-600">
          <span className="w-2.5 h-2.5 rounded-sm" style={{ background: COR.foraDoSla }} />depois de 2 h
        </span>
        <span className="ml-auto text-[11.5px] text-gray-400 tabular-nums">{total} respondidas</span>
      </div>
      <div className="h-[260px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={faixas} margin={{ top: 20, right: 8, left: -12, bottom: 0 }} barCategoryGap="18%">
            <CartesianGrid stroke={COR.grade} vertical={false} />
            <XAxis dataKey="faixa" tick={{ fontSize: 10.5, fill: COR.eixo }} tickLine={false}
                   axisLine={{ stroke: COR.grade }} interval={0} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: COR.eixo }} tickLine={false}
                   axisLine={false} width={40} />
            <Tooltip cursor={{ fill: '#f3f4f6' }}
                     content={<Dica formatar={(v) => `${v} (${Math.round((100 * v) / total)}%)`} />} />
            <Bar dataKey="n" name="Respostas" radius={[4, 4, 0, 0]}>
              {faixas.map((f, i) => <Cell key={f.faixa} fill={i < DENTRO ? COR.marca : COR.foraDoSla} />)}
              <LabelList dataKey="n" position="top" style={{ fontSize: 11, fill: COR.tinta }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
