'use client';

import { ArrowDownRight, ArrowUpRight, Info, Minus } from 'lucide-react';
import type { Variacao } from './tipos';

/**
 * Um número grande, o N pequeno, a seta contra o período anterior, e a definição no ⓘ.
 * `melhor` diz para que lado a seta é boa: tempo de resposta bom é o que CAI.
 */
export default function KpiCard({ rotulo, valor, n, variacao, melhor, definicao, limitacao,
                                  rodape, destaque }: {
  rotulo: string;
  valor: string;
  n?: string;
  variacao?: Variacao | null;
  melhor?: 'sobe' | 'desce';
  definicao: string;
  limitacao?: string | null;
  rodape?: React.ReactNode;
  destaque?: 'vermelho' | null;
}) {
  return (
    <div className={`bg-white rounded-2xl p-5 border flex flex-col ${
      destaque === 'vermelho' ? 'border-rose-200' : 'border-gray-100'}`}>
      <div className="flex items-start justify-between gap-2 mb-3">
        <p className="text-[13px] text-gray-500 leading-snug">{rotulo}</p>
        <span title={limitacao ? `${definicao}\n\n${limitacao}` : definicao}
              className="inline-flex cursor-help text-gray-300 hover:text-[#2A658F] transition-colors">
          <Info className="w-3.5 h-3.5" />
        </span>
      </div>
      <p className="text-[30px] leading-none font-bold text-[#27273D] tabular-nums">{valor}</p>
      <div className="flex items-center justify-between gap-2 mt-2 min-h-[18px]">
        {n ? <span className="text-[12px] text-gray-400 tabular-nums">{n}</span> : <span />}
        {variacao && melhor && <Seta v={variacao} melhor={melhor} />}
      </div>
      {rodape && <div className="mt-3 pt-3 border-t border-gray-50">{rodape}</div>}
    </div>
  );
}

function Seta({ v, melhor }: { v: Variacao; melhor: 'sobe' | 'desce' }) {
  if (v.delta === null || v.anterior === null) {
    return <span className="text-[11px] text-gray-300" title="Sem dado no período anterior">sem base</span>;
  }
  if (v.delta === 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[11.5px] text-gray-400">
        <Minus className="w-3 h-3" /> igual
      </span>
    );
  }
  const subiu = v.delta > 0;
  const bom = (subiu && melhor === 'sobe') || (!subiu && melhor === 'desce');
  const Icone = subiu ? ArrowUpRight : ArrowDownRight;
  const texto = v.pct !== null ? `${subiu ? '+' : ''}${v.pct.toLocaleString('pt-BR')}%` : 'novo';
  return (
    <span title="Comparado ao período anterior de mesma duração"
          className={`inline-flex items-center gap-0.5 text-[11.5px] font-medium tabular-nums ${
            bom ? 'text-emerald-700' : 'text-rose-700'}`}>
      <Icone className="w-3.5 h-3.5" /> {texto}
    </span>
  );
}
