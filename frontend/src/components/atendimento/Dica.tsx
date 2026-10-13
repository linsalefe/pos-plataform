'use client';

/** Tooltip dos gráficos. Tipado à mão para não depender dos genéricos do Recharts. */
export interface ItemDica {
  name?: string | number;
  value?: number | string | (number | string)[];
  color?: string;
  dataKey?: string | number | ((obj: unknown) => unknown);
}

export default function Dica({ active, payload, label, titulo, formatar }: {
  active?: boolean;
  payload?: ItemDica[];
  label?: string | number;
  titulo?: (label: string | number) => string;
  formatar?: (valor: number, nome: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-sm px-3 py-2 text-[12px]">
      {label !== undefined && (
        <p className="font-semibold text-[#27273D] mb-1">{titulo ? titulo(label) : label}</p>
      )}
      {payload.map((p) => {
        const nome = String(p.name ?? '');
        const v = typeof p.value === 'number' ? p.value : null;
        return (
          <p key={nome} className="flex items-center gap-2 text-gray-600">
            <span className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ background: p.color }} />
            <span>{nome}</span>
            <span className="ml-auto pl-3 font-medium text-[#27273D] tabular-nums">
              {v === null ? '—' : formatar ? formatar(v, nome) : v.toLocaleString('pt-BR')}
            </span>
          </p>
        );
      })}
    </div>
  );
}
