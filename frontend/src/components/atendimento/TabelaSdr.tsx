'use client';

import { useState } from 'react';
import { ArrowDown, ArrowUp } from 'lucide-react';
import { duracao, pctTxt, type LinhaSdr, type Relogio } from './tipos';

type Coluna = 'sdr' | 'perguntas' | 'respondidas' | 'pct' | 'mediana' | 'janelas' | 'agora';

const COLUNAS: { chave: Coluna; rotulo: string; dica?: string }[] = [
  { chave: 'sdr', rotulo: 'SDR' },
  { chave: 'perguntas', rotulo: 'Perguntas', dica: 'Perguntas do time em contatos de que a pessoa é dona hoje' },
  { chave: 'respondidas', rotulo: 'Respondidas' },
  { chave: 'pct', rotulo: 'No SLA', dica: 'Respondidas em até 2 h, sobre as perguntas com prazo vencido' },
  { chave: 'mediana', rotulo: 'Mediana' },
  { chave: 'janelas', rotulo: 'Janelas perdidas', dica: '24 h sem resposta desde a última mensagem do lead' },
  { chave: 'agora', rotulo: 'Sem resposta agora' },
];

function valor(l: LinhaSdr, c: Coluna, r: Relogio): number | string {
  switch (c) {
    case 'sdr': return l.sdr;
    case 'perguntas': return l.perguntas;
    case 'respondidas': return l.respondidas;
    case 'pct': return l[r].pct_sla ?? -1;
    case 'mediana': return l[r].mediana ?? Number.POSITIVE_INFINITY;
    case 'janelas': return l.janelas_perdidas;
    case 'agora': return l.sem_resposta_agora;
  }
}

export default function TabelaSdr({ linhas, relogio, aoEscolher }: {
  linhas: LinhaSdr[];
  relogio: Relogio;
  aoEscolher?: (sdrId: number | null) => void;
}) {
  const [ordem, setOrdem] = useState<{ c: Coluna; asc: boolean }>({ c: 'perguntas', asc: false });
  const ordenadas = [...linhas].sort((a, b) => {
    const x = valor(a, ordem.c, relogio);
    const y = valor(b, ordem.c, relogio);
    const cmp = typeof x === 'string' ? x.localeCompare(String(y)) : x - (y as number);
    return ordem.asc ? cmp : -cmp;
  });
  if (!linhas.length) {
    return <p className="text-[12.5px] text-gray-400 py-10 text-center">Nenhuma pergunta do time no período.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px] tabular-nums">
        <thead>
          <tr className="text-gray-400 text-left">
            {COLUNAS.map((col) => (
              <th key={col.chave} title={col.dica}
                  className={`py-2 font-medium whitespace-nowrap ${col.chave === 'sdr' ? '' : 'text-right'}`}>
                <button onClick={() => setOrdem({ c: col.chave, asc: ordem.c === col.chave ? !ordem.asc : col.chave === 'sdr' })}
                        className="inline-flex items-center gap-0.5 hover:text-[#27273D]">
                  {col.rotulo}
                  {ordem.c === col.chave && (ordem.asc ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ordenadas.map((l) => (
            <tr key={l.sdr_id ?? 'sem'} className="border-t border-gray-50 text-gray-600 hover:bg-gray-50/60">
              <td className="py-2.5">
                {aoEscolher && l.sdr_id !== null ? (
                  <button onClick={() => aoEscolher(l.sdr_id)} title="Filtrar a página por esta pessoa"
                          className="font-medium text-[#27273D] hover:text-[#2A658F]">{l.sdr}</button>
                ) : <span className={`font-medium ${l.sdr_id === null ? 'text-gray-400' : 'text-[#27273D]'}`}>{l.sdr}</span>}
              </td>
              <td className="text-right">{l.perguntas}</td>
              <td className="text-right">
                {l.respondidas}
                {l.respondeu_pessoalmente > 0 && l.respondeu_pessoalmente !== l.respondidas && (
                  <span className="text-gray-400" title="Respondidas pela própria pessoa (desde 01/09)">
                    {' '}({l.respondeu_pessoalmente})
                  </span>
                )}
              </td>
              <td className="text-right">
                {pctTxt(l[relogio].pct_sla)}
                <span className="text-gray-300 text-[11px]"> /{l[relogio].vencidas}</span>
              </td>
              <td className="text-right">{duracao(l[relogio].mediana)}</td>
              <td className="text-right">{l.janelas_perdidas}</td>
              <td className={`text-right font-semibold ${l.sem_resposta_agora ? 'text-rose-700' : 'text-gray-300'}`}>
                {l.sem_resposta_agora}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
