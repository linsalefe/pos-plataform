'use client';

/**
 * Perguntas por dia: no SLA / fora do SLA / sem resposta, empilhadas. As três cores são de
 * ESTADO (validadas para daltonismo e visão normal); o âmbar tem contraste baixo contra o
 * branco, por isso a legenda é texto e a tabela está a um clique.
 */
import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import Dica from './Dica';
import { COR, rotuloChave, type LinhaSerie, type Relogio } from './tipos';

const SERIES = [
  { chave: 'no', nome: 'No SLA', cor: COR.noSla },
  { chave: 'fora', nome: 'Fora do SLA', cor: COR.foraSla },
  { chave: 'sem', nome: 'Sem resposta', cor: COR.semResposta },
] as const;

export default function SlaBarChart({ linhas, relogio }: { linhas: LinhaSerie[]; relogio: Relogio }) {
  const [tabela, setTabela] = useState(false);
  const dados = linhas.map((l) => ({
    rotulo: rotuloChave(l.chave),
    no: l[relogio].no_sla,
    fora: l[relogio].fora_sla,
    sem: l.sem_resposta,
    perguntas: l.perguntas,
  }));
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mb-2">
        {SERIES.map((s) => (
          <span key={s.chave} className="inline-flex items-center gap-1.5 text-[11.5px] text-gray-600">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ background: s.cor }} />{s.nome}
          </span>
        ))}
        <button onClick={() => setTabela(!tabela)}
                className="ml-auto text-[11.5px] text-[#2A658F] hover:underline">
          {tabela ? 'ver gráfico' : 'ver tabela'}
        </button>
      </div>
      {tabela ? (
        <div className="max-h-[340px] overflow-auto">
          <table className="w-full text-[12px] tabular-nums">
            <thead className="text-gray-400 text-left sticky top-0 bg-white">
              <tr><th className="py-1.5 font-medium">Dia</th>
                <th className="text-right font-medium">Perguntas</th>
                {SERIES.map((s) => <th key={s.chave} className="text-right font-medium">{s.nome}</th>)}</tr>
            </thead>
            <tbody>
              {dados.map((d) => (
                <tr key={d.rotulo} className="border-t border-gray-50 text-gray-600">
                  <td className="py-1.5">{d.rotulo}</td><td className="text-right">{d.perguntas}</td>
                  <td className="text-right">{d.no}</td><td className="text-right">{d.fora}</td>
                  <td className="text-right">{d.sem}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-[340px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={dados} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barCategoryGap="20%">
              <CartesianGrid stroke={COR.grade} vertical={false} />
              <XAxis dataKey="rotulo" tick={{ fontSize: 11, fill: COR.eixo }} tickLine={false}
                     axisLine={{ stroke: COR.grade }} interval="preserveStartEnd" minTickGap={16} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: COR.eixo }} tickLine={false}
                     axisLine={false} width={40} />
              <Tooltip cursor={{ fill: '#f3f4f6' }} content={<Dica />} />
              {SERIES.map((s, i) => (
                <Bar key={s.chave} dataKey={s.chave} name={s.nome} stackId="a" fill={s.cor}
                     stroke="#ffffff" strokeWidth={1}
                     radius={i === SERIES.length - 1 ? [4, 4, 0, 0] : [0, 0, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
