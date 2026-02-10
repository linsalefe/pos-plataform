'use client';

import { useState, useEffect } from 'react';
import AppLayout from '@/components/AppLayout';
import { Calendar, Clock, Phone, User, GraduationCap, RefreshCw } from 'lucide-react';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api';

interface AvailableDate {
  date: string;
  weekday: string;
  slots_count: number;
  first_slot: string;
  last_slot: string;
}

export default function AgendaPage() {
  const [dates, setDates] = useState<AvailableDate[]>([]);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<'agenda' | 'disponibilidade'>('agenda');

  const fetchDates = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/calendar/available-dates/victoria`);
      const data = await res.json();
      setDates(data);
    } catch (err) {
      console.error('Erro ao buscar datas:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDates();
  }, []);

  return (
    <AppLayout>
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-white">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
              <Calendar className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-gray-800">Agenda</h1>
              <p className="text-xs text-gray-500">Pré Vendas - CENAT</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex bg-gray-100 rounded-lg p-1">
              <button
                onClick={() => setView('agenda')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                  view === 'agenda'
                    ? 'bg-white text-gray-800 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                Calendário
              </button>
              <button
                onClick={() => setView('disponibilidade')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                  view === 'disponibilidade'
                    ? 'bg-white text-gray-800 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                Disponibilidade
              </button>
            </div>
            <button
              onClick={fetchDates}
              className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-all"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-6">
          {view === 'agenda' ? (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm h-full">
              <iframe
                src="https://calendar.google.com/calendar/embed?src=comercialcenat%40gmail.com&ctz=America%2FSao_Paulo"
                style={{ border: 0 }}
                width="100%"
                height="100%"
                className="min-h-[600px]"
              />
            </div>
          ) : (
            <div className="space-y-4">
              {/* Cards de disponibilidade */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {loading ? (
                  Array.from({ length: 3 }).map((_, i) => (
                    <div key={i} className="bg-white rounded-xl border border-gray-200 p-5 animate-pulse">
                      <div className="h-5 bg-gray-200 rounded w-32 mb-3" />
                      <div className="h-4 bg-gray-100 rounded w-24 mb-2" />
                      <div className="h-4 bg-gray-100 rounded w-20" />
                    </div>
                  ))
                ) : dates.length > 0 ? (
                  dates.map((d) => (
                    <div
                      key={d.date}
                      className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md transition-all"
                    >
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <Calendar className="w-4 h-4 text-blue-500" />
                          <span className="font-semibold text-gray-800">
                            {d.weekday}
                          </span>
                        </div>
                        <span className="text-xs text-gray-500">
                          {d.date.split('-').reverse().join('/')}
                        </span>
                      </div>

                      <div className="space-y-2">
                        <div className="flex items-center gap-2 text-sm text-gray-600">
                          <Clock className="w-3.5 h-3.5 text-green-500" />
                          <span>
                            {d.slots_count} horários livres
                          </span>
                        </div>
                        <div className="text-xs text-gray-500">
                          De {d.first_slot} até {d.last_slot}
                        </div>
                      </div>

                      <div className="mt-3 pt-3 border-t border-gray-100">
                        <div className="flex items-center gap-1.5">
                          <div className={`w-2 h-2 rounded-full ${
                            d.slots_count > 10 ? 'bg-green-400' : d.slots_count > 5 ? 'bg-yellow-400' : 'bg-red-400'
                          }`} />
                          <span className="text-xs text-gray-500">
                            {d.slots_count > 10 ? 'Muita disponibilidade' : d.slots_count > 5 ? 'Disponibilidade moderada' : 'Pouca disponibilidade'}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="col-span-3 text-center py-12 text-gray-400">
                    Nenhum horário disponível encontrado.
                  </div>
                )}
              </div>

              {/* Info */}
              <div className="bg-blue-50 rounded-xl p-4 flex items-start gap-3">
                <Phone className="w-5 h-5 text-blue-500 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="text-sm font-medium text-blue-800">
                    Agendamentos automáticos pela Nat
                  </p>
                  <p className="text-xs text-blue-600 mt-1">
                    A IA Nat verifica esses horários em tempo real antes de sugerir agendamentos aos leads.
                    Eventos criados automaticamente aparecem no calendário acima.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
