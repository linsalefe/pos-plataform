'use client';

import { useEffect, useState, useRef } from 'react';
import {
  Bot, Send, Loader2, Trash2, User
} from 'lucide-react';
import AppLayout from '@/components/AppLayout';
import api from '@/lib/api';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  model?: string;
  rag_docs?: number;
}

interface ChannelInfo {
  id: number;
  name: string;
}

export default function AITestPage() {
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [activeChannel, setActiveChannel] = useState<number>(2);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [leadName, setLeadName] = useState("");
  const [leadCourse, setLeadCourse] = useState("");  const [mounted, setMounted] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => { 
    setMounted(true); 
    loadChannels(); 
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadChannels = async () => {
    try {
      const res = await api.get('/channels');
      setChannels(res.data);
    } catch (err) {
      console.error('Erro ao carregar canais:', err);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || sending) return;

    const userMsg: ChatMessage = {
      role: 'user',
      content: input.trim(),
      timestamp: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setSending(true);

    try {
      const history = messages.map(m => ({
        role: m.role,
        content: m.content,
      }));

      const res = await api.post('/ai/test-chat', {
        message: userMsg.content,
        channel_id: activeChannel,
        conversation_history: history,
        lead_name: leadName,
        lead_course: leadCourse,
      });

      const aiMsg: ChatMessage = {
        role: 'assistant',
        content: res.data.response,
        timestamp: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
        model: res.data.model,
        rag_docs: res.data.rag_docs,
      };

      setMessages(prev => [...prev, aiMsg]);
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        role: 'assistant',
        content: `❌ Erro: ${err.response?.data?.detail || err.message || 'Erro desconhecido'}`,
        timestamp: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setSending(false);
    }
  };

  const clearChat = () => {
    setMessages([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  if (!mounted) return null;

  return (
    <AppLayout>
      <div className="flex-1 bg-[#f8f9fb] flex flex-col overflow-hidden">

        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 bg-white flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center shadow-md">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-[#27273D]">Teste da Nat</h1>
                <p className="text-[12px] text-gray-400">Simule uma conversa com a IA antes de colocar em produção</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <select
                value={activeChannel}
                onChange={e => { setActiveChannel(parseInt(e.target.value)); clearChat(); }}
                className="px-3 py-2 rounded-xl border border-gray-200 text-[13px] bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-emerald-200"
              >
                {channels.map(ch => (
                  <option key={ch.id} value={ch.id}>{ch.name}</option>
                ))}
              </select>

              <button
                onClick={clearChat}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-gray-200 bg-white text-gray-500 hover:text-red-500 hover:border-red-200 transition-all text-[13px]"
              >
                <Trash2 className="w-4 h-4" />
                Limpar
              </button>
            </div>
          </div>

          {/* Lead Info */}
          <div className="flex gap-3 mt-3">
            <div className="flex items-center gap-2 flex-1">
              <label className="text-[12px] text-gray-400 font-medium whitespace-nowrap">Nome do Lead:</label>
              <input type="text" value={leadName} onChange={e => setLeadName(e.target.value)} placeholder="Ex: Maria Silva" className="flex-1 px-3 py-1.5 rounded-lg border border-gray-200 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-emerald-200" />
            </div>
            <div className="flex items-center gap-2 flex-1">
              <label className="text-[12px] text-gray-400 font-medium whitespace-nowrap">Curso:</label>
              <input type="text" value={leadCourse} onChange={e => setLeadCourse(e.target.value)} placeholder="Ex: Saúde Mental Infantojuvenil" className="flex-1 px-3 py-1.5 rounded-lg border border-gray-200 text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-emerald-200" />
            </div>
          </div>
        </div>

        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          <div className="max-w-3xl mx-auto space-y-4">

            {/* Welcome Message */}
            {messages.length === 0 && (
              <div className="text-center py-16 space-y-4">
                <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-emerald-100 to-teal-100 flex items-center justify-center mx-auto shadow-sm">
                  <Bot className="w-10 h-10 text-emerald-600" />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-[#27273D]">🤖 Teste da Nat</h2>
                  <p className="text-[13px] text-gray-400 mt-1 max-w-md mx-auto">
                    Simule uma conversa como se fosse um lead. A Nat vai responder usando o prompt e a base de conhecimento configurados.
                  </p>
                </div>
                <div className="flex flex-wrap justify-center gap-2 pt-2">
                  {[
                    'Olá, tenho interesse na pós',
                    'Quais os cursos disponíveis?',
                    'Quanto custa?',
                    'Como funciona a matrícula?',
                  ].map(suggestion => (
                    <button
                      key={suggestion}
                      onClick={() => { setInput(suggestion); }}
                      className="px-3 py-1.5 rounded-full bg-white border border-gray-200 text-[12px] text-gray-600 hover:border-emerald-300 hover:text-emerald-700 hover:bg-emerald-50 transition-all"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Messages */}
            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[75%] ${msg.role === 'user' ? 'order-2' : 'order-1'}`}>
                  
                  {/* Avatar + Name */}
                  <div className={`flex items-center gap-1.5 mb-1 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    {msg.role === 'assistant' && (
                      <div className="w-5 h-5 rounded-md bg-emerald-100 flex items-center justify-center">
                        <Bot className="w-3 h-3 text-emerald-600" />
                      </div>
                    )}
                    <span className="text-[10px] font-medium text-gray-400">
                      {msg.role === 'user' ? 'Você (Lead)' : 'Nat (IA)'}
                    </span>
                    {msg.role === 'user' && (
                      <div className="w-5 h-5 rounded-md bg-blue-100 flex items-center justify-center">
                        <User className="w-3 h-3 text-blue-600" />
                      </div>
                    )}
                  </div>

                  {/* Bubble */}
                  <div
                    className={`px-4 py-3 rounded-2xl text-[13px] leading-relaxed whitespace-pre-wrap ${
                      msg.role === 'user'
                        ? 'bg-[#2A658F] text-white rounded-br-md'
                        : 'bg-white border border-gray-200 text-[#374151] rounded-bl-md shadow-sm'
                    }`}
                  >
                    {msg.content || "(resposta vazia)"}
                  </div>

                  {/* Footer */}
                  <div className={`flex items-center gap-2 mt-1 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <span className="text-[10px] text-gray-400">{msg.timestamp}</span>
                    {msg.role === 'assistant' && msg.model && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-400">
                        {msg.model}
                      </span>
                    )}
                    {msg.role === 'assistant' && msg.rag_docs !== undefined && msg.rag_docs > 0 && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-500">
                        📚 {msg.rag_docs} docs RAG
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))}

            {/* Typing indicator */}
            {sending && (
              <div className="flex justify-start">
                <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-md px-4 py-3 shadow-sm">
                  <div className="flex items-center gap-2">
                    <div className="flex gap-1">
                      <div className="w-2 h-2 rounded-full bg-emerald-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                      <div className="w-2 h-2 rounded-full bg-emerald-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                      <div className="w-2 h-2 rounded-full bg-emerald-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                    </div>
                    <span className="text-[11px] text-gray-400">Nat está digitando...</span>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input Area */}
        <div className="border-t border-gray-200 bg-white px-6 py-4 flex-shrink-0">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-end gap-3">
              <div className="flex-1 relative">
                <textarea
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  rows={1}
                  placeholder="Digite uma mensagem como se fosse um lead..."
                  className="w-full px-4 py-3 rounded-xl border border-gray-200 text-[13px] bg-gray-50 focus:outline-none focus:ring-2 focus:ring-emerald-200 focus:border-emerald-400 resize-none pr-12"
                  style={{ minHeight: '46px', maxHeight: '120px' }}
                  onInput={e => {
                    const target = e.target as HTMLTextAreaElement;
                    target.style.height = '46px';
                    target.style.height = Math.min(target.scrollHeight, 120) + 'px';
                  }}
                />
              </div>
              <button
                onClick={sendMessage}
                disabled={!input.trim() || sending}
                className="w-11 h-11 rounded-xl bg-emerald-600 text-white flex items-center justify-center hover:bg-emerald-700 transition-all disabled:opacity-50 flex-shrink-0 shadow-sm"
              >
                {sending ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
              </button>
            </div>
            <p className="text-[10px] text-gray-400 mt-2 text-center">
              As mensagens de teste não são enviadas pelo WhatsApp. O histórico é perdido ao sair da página.
            </p>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}