'use client';

/**
 * A lista VIVA: quem está sem resposta agora. Não depende do período escolhido no topo e se
 * atualiza sozinha a cada 60 s. Cada linha abre a conversa já selecionada
 * (`/conversations?wa=`, que casa as duas grafias do telefone).
 */
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Bot, CalendarClock, ExternalLink, Loader2, RefreshCw, Search, User } from 'lucide-react';
import api from '@/lib/api';
import { horas, quando, type EstadoJanela, type Pendentes, type Quem } from './tipos';

const POLLING_MS = 60_000;

const JANELA: Record<EstadoJanela, { rotulo: string; linha: string; chip: string }> = {
  aberta: { rotulo: 'aberta', linha: '', chip: 'bg-gray-100 text-gray-600' },
  perto: { rotulo: 'perto de fechar', linha: 'bg-amber-50/60', chip: 'bg-amber-100 text-amber-800' },
  expirada: { rotulo: 'expirada', linha: 'bg-rose-50/60', chip: 'bg-rose-100 text-rose-800' },
};

const DONO = {
  sdr: { rotulo: 'SDR', icone: User, cor: 'bg-[#2A658F]/8 text-[#2A658F]' },
  agente: { rotulo: 'agente', icone: Bot, cor: 'bg-violet-50 text-violet-700' },
  regua: { rotulo: 'régua', icone: CalendarClock, cor: 'bg-teal-50 text-teal-700' },
} as const;

export default function ListaPendentes({ quem, sdr }: { quem: Quem; sdr: number | null }) {
  const [dados, setDados] = useState<Pendentes | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [busca, setBusca] = useState('');
  const [janela, setJanela] = useState<EstadoJanela | 'todas'>('todas');

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const res = await api.get<Pendentes>('/atendimento/pendentes', {
        params: { quem, ...(sdr !== null ? { sdr } : {}) } });
      setDados(res.data);
    } catch (e: unknown) {
      setDados({ apurado_em: '', erro: { tipo: 'Rede', mensagem: e instanceof Error ? e.message : 'falha' } });
    } finally {
      setCarregando(false);
    }
  }, [quem, sdr]);

  useEffect(() => {
    carregar();
    const id = setInterval(carregar, POLLING_MS);
    return () => clearInterval(id);
  }, [carregar]);

  if (!dados) {
    return <div className="h-[200px] flex items-center justify-center"><Loader2 className="w-5 h-5 text-[#2A658F] animate-spin" /></div>;
  }
  if (dados.erro) {
    return (
      <p className="text-[12.5px] text-rose-700 flex items-center gap-2">
        <AlertTriangle className="w-4 h-4" /> A lista não carregou: {dados.erro.tipo}: {dados.erro.mensagem}
        <button onClick={carregar} className="text-[#2A658F] hover:underline">tentar de novo</button>
      </p>
    );
  }

  const termo = busca.trim().toLowerCase();
  const itens = (dados.itens ?? []).filter((i) =>
    (janela === 'todas' || i.janela === janela)
    && (!termo || (i.nome ?? '').toLowerCase().includes(termo) || i.wa_id.includes(termo)
        || i.sdr_nome.toLowerCase().includes(termo) || i.ultima_msg.toLowerCase().includes(termo)));
  const pj = dados.por_janela ?? { aberta: 0, perto: 0, expirada: 0 };

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <div className="flex items-center gap-1.5 bg-gray-50 rounded-lg px-2.5 py-1.5 w-full sm:w-[260px]">
          <Search className="w-3.5 h-3.5 text-gray-400" />
          <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Nome, telefone, SDR ou mensagem"
                 className="bg-transparent outline-none text-[12.5px] text-gray-700 w-full" />
        </div>
        {(['todas', 'aberta', 'perto', 'expirada'] as const).map((j) => (
          <button key={j} onClick={() => setJanela(j)}
                  className={`px-2.5 py-1.5 rounded-lg text-[11.5px] font-medium tabular-nums transition-colors ${
                    janela === j ? 'bg-[#2A658F] text-white' : 'bg-gray-50 text-gray-500 hover:bg-gray-100'}`}>
            {j === 'todas' ? `Todas · ${dados.total ?? 0}` : `${JANELA[j].rotulo} · ${pj[j]}`}
          </button>
        ))}
        <span className="ml-auto inline-flex items-center gap-1.5 text-[11px] text-gray-400">
          {carregando ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          atualizado {quando(dados.apurado_em)} · a cada 60 s
        </span>
      </div>

      {!!dados.ocultos_automacao && (
        <p className="text-[11.5px] text-gray-400 mb-2">
          {dados.ocultos_automacao} conversa(s) com o agente ou a régua como dona não aparecem aqui
          (filtro “time”).
        </p>
      )}

      {itens.length === 0 ? (
        <p className="text-[12.5px] text-gray-400 py-8 text-center">
          {dados.total ? 'Nada com esse filtro.' : 'Ninguém esperando resposta agora.'}
        </p>
      ) : (
        <div className="overflow-x-auto max-h-[560px] overflow-y-auto border border-gray-100 rounded-xl">
          <table className="w-full text-[12.5px]">
            <thead className="sticky top-0 bg-white z-10 text-gray-400 text-left">
              <tr>
                <th className="py-2 px-3 font-medium">Lead</th>
                <th className="py-2 px-3 font-medium">Dono</th>
                <th className="py-2 px-3 font-medium">Última mensagem</th>
                <th className="py-2 px-3 font-medium text-right whitespace-nowrap">Esperando</th>
                <th className="py-2 px-3 font-medium">Janela 24 h</th>
                <th className="py-2 px-3" />
              </tr>
            </thead>
            <tbody>
              {itens.map((i) => {
                const d = DONO[i.dono_inbound];
                const IconeDono = d.icone;
                return (
                  <tr key={i.wa_id} className={`border-t border-gray-50 ${JANELA[i.janela].linha}`}>
                    <td className="py-2.5 px-3">
                      <p className="font-medium text-[#27273D] truncate max-w-[200px]">{i.nome?.trim() || i.wa_id}</p>
                      <p className="text-[11px] text-gray-400 tabular-nums">{i.wa_id}</p>
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10.5px] font-medium ${d.cor}`}
                            title={i.dono_detalhe ?? undefined}>
                        <IconeDono className="w-3 h-3" />{d.rotulo}
                      </span>
                      <span className={`ml-1.5 text-[12px] ${i.sdr_id === null ? 'text-gray-400' : 'text-gray-600'}`}>{i.sdr_nome}</span>
                      {i.anomalia && (
                        <span title="Automação dona há mais de 10 min sem responder" className="ml-1 text-rose-600">
                          <AlertTriangle className="w-3 h-3 inline" />
                        </span>
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-gray-600 max-w-[340px]">
                      <p className="truncate" title={i.ultima_msg}>{i.ultima_msg || <span className="text-gray-300">(mídia)</span>}</p>
                      {i.so_template && (
                        <p className="text-[10.5px] text-amber-700" title={`Primeira mensagem sem resposta: ${quando(i.primeira_sem_resposta)}`}>
                          recebeu só template desde {quando(i.primeira_sem_resposta)}
                        </p>
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-right tabular-nums whitespace-nowrap">
                      <span className="font-semibold text-[#27273D]">{horas(i.horas_esperando)}</span>
                      <p className="text-[10.5px] text-gray-400">desde {quando(i.esperando_desde)}</p>
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <span className={`px-1.5 py-0.5 rounded-md text-[10.5px] font-medium ${JANELA[i.janela].chip}`}
                            title={`Fecha ${quando(i.janela_fecha_em)}`}>
                        {JANELA[i.janela].rotulo}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      <Link href={`/conversations?wa=${encodeURIComponent(i.wa_id)}`}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-[#2A658F] text-white
                                       text-[11.5px] font-medium hover:bg-[#245a80] whitespace-nowrap">
                        Abrir conversa <ExternalLink className="w-3 h-3" />
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
