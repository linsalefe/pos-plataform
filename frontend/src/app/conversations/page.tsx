'use client';

import { useEffect, useState, useRef } from 'react';
import {
  Send, Search, MessageCircle, Check, CheckCheck, Clock, XCircle,
  ArrowLeft, Plus, X, User, Phone, Calendar, ChevronDown, Sparkles, Radio, Loader2
} from 'lucide-react';
import AppLayout from '@/components/AppLayout';
import api from '@/lib/api';

interface ChannelInfo {
  id: number;
  name: string;
  phone_number: string;
}

interface ContactTag {
  id: number;
  name: string;
  color: string;
}

interface Contact {
  wa_id: string;
  name: string;
  lead_status: string;
  notes: string | null;
  last_message: string;
  last_message_time: string | null;
  direction: string | null;
  tags: ContactTag[];
  unread: number;
  created_at: string | null;
  channel_id: number | null;
}

interface Message {
  id: number;
  wa_message_id: string;
  direction: string;
  type: string;
  content: string;
  timestamp: string;
  status: string;
}

const leadStatuses = [
  { value: 'novo', label: 'Novo', color: 'bg-blue-500', bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200' },
  { value: 'em_contato', label: 'Em contato', color: 'bg-amber-500', bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200' },
  { value: 'qualificado', label: 'Qualificado', color: 'bg-purple-500', bg: 'bg-purple-50', text: 'text-purple-700', border: 'border-purple-200' },
  { value: 'negociando', label: 'Negociando', color: 'bg-cyan-500', bg: 'bg-cyan-50', text: 'text-cyan-700', border: 'border-cyan-200' },
  { value: 'convertido', label: 'Convertido', color: 'bg-emerald-500', bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200' },
  { value: 'perdido', label: 'Perdido', color: 'bg-red-500', bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200' },
];

const tagColors = [
  { value: 'blue', bg: 'bg-blue-100', text: 'text-blue-700' },
  { value: 'green', bg: 'bg-emerald-100', text: 'text-emerald-700' },
  { value: 'red', bg: 'bg-red-100', text: 'text-red-700' },
  { value: 'purple', bg: 'bg-purple-100', text: 'text-purple-700' },
  { value: 'amber', bg: 'bg-amber-100', text: 'text-amber-700' },
  { value: 'pink', bg: 'bg-pink-100', text: 'text-pink-700' },
  { value: 'cyan', bg: 'bg-cyan-100', text: 'text-cyan-700' },
];

export default function ConversationsPage() {
  const [channels, setChannels] = useState<ChannelInfo[]>([]);
  const [activeChannel, setActiveChannel] = useState<ChannelInfo | null>(null);
  const [showChannelMenu, setShowChannelMenu] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [newMessage, setNewMessage] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('todos');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [showCRM, setShowCRM] = useState(true);
  const [showStatusMenu, setShowStatusMenu] = useState(false);
  const [showTagMenu, setShowTagMenu] = useState(false);
  const [allTags, setAllTags] = useState<ContactTag[]>([]);
  const [newTagName, setNewTagName] = useState('');
  const [newTagColor, setNewTagColor] = useState('blue');
  const [editingNotes, setEditingNotes] = useState(false);
  const [showNewChat, setShowNewChat] = useState(false);
  const [newChatPhone, setNewChatPhone] = useState('');
  const [newChatName, setNewChatName] = useState('');
  const [newChatCourse, setNewChatCourse] = useState('');
  const [sendingTemplate, setSendingTemplate] = useState(false);
  const [notesValue, setNotesValue] = useState('');
  const [mounted, setMounted] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    loadChannels();
    loadTags();
  }, []);

  useEffect(() => {
    if (activeChannel) {
      loadContacts();
      const interval = setInterval(loadContacts, 5000);
      return () => clearInterval(interval);
    }
  }, [activeChannel]);

  useEffect(() => {
    if (selectedContact) {
      loadMessages(selectedContact.wa_id);
      setNotesValue(selectedContact.notes || '');
      const interval = setInterval(() => loadMessages(selectedContact.wa_id), 3000);
      return () => clearInterval(interval);
    }
  }, [selectedContact]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const loadChannels = async () => {
    try {
      const res = await api.get('/channels');
      setChannels(res.data);
      if (res.data.length > 0 && !activeChannel) {
        setActiveChannel(res.data[0]);
      }
    } catch (err) {
      console.error('Erro:', err);
    }
  };

  const loadContacts = async () => {
    try {
      const params = activeChannel ? `?channel_id=${activeChannel.id}` : '';
      const res = await api.get(`/contacts${params}`);
      setContacts(res.data);
      if (selectedContact) {
        const updated = res.data.find((c: Contact) => c.wa_id === selectedContact.wa_id);
        if (updated) setSelectedContact(updated);
      }
    } catch (err) {
      console.error('Erro:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadMessages = async (waId: string) => {
    try {
      const res = await api.get(`/contacts/${waId}/messages`);
      setMessages(res.data);
    } catch (err) {
      console.error('Erro:', err);
    }
  };

  const loadTags = async () => {
    try {
      const res = await api.get('/tags');
      setAllTags(res.data);
    } catch (err) {
      console.error('Erro:', err);
    }
  };

  const handleSend = async () => {
    if (!newMessage.trim() || !selectedContact || !activeChannel || sending) return;
    setSending(true);
    try {
      await api.post('/send/text', {
        to: selectedContact.wa_id,
        text: newMessage,
        channel_id: activeChannel.id,
      });
      setNewMessage('');
      await loadMessages(selectedContact.wa_id);
      await loadContacts();
    } catch (err) {
      console.error('Erro:', err);
    } finally {
      setSending(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const updateLeadStatus = async (status: string) => {
    if (!selectedContact) return;
    try {
      await api.patch(`/contacts/${selectedContact.wa_id}`, { lead_status: status });
      setShowStatusMenu(false);
      await loadContacts();
    } catch (err) { console.error('Erro:', err); }
  };

  const saveNotes = async () => {
    if (!selectedContact) return;
    try {
      await api.patch(`/contacts/${selectedContact.wa_id}`, { notes: notesValue });
      setEditingNotes(false);
      await loadContacts();
    } catch (err) { console.error('Erro:', err); }
  };

  const addTag = async (tagId: number) => {
    if (!selectedContact) return;
    try {
      await api.post(`/contacts/${selectedContact.wa_id}/tags/${tagId}`);
      await loadContacts();
    } catch (err) { console.error('Erro:', err); }
  };

  const removeTag = async (tagId: number) => {
    if (!selectedContact) return;
    try {
      await api.delete(`/contacts/${selectedContact.wa_id}/tags/${tagId}`);
      await loadContacts();
    } catch (err) { console.error('Erro:', err); }
  };

  const createTag = async () => {
    if (!newTagName.trim()) return;
    try {
      const res = await api.post('/tags', { name: newTagName, color: newTagColor });
      setAllTags([...allTags, res.data]);
      setNewTagName('');
      if (selectedContact) await addTag(res.data.id);
    } catch (err) { console.error('Erro:', err); }
  };

  const handleNewChat = async () => {
    if (!newChatPhone.trim() || !newChatName.trim() || !activeChannel) return;
    setSendingTemplate(true);
    try {
      const phone = newChatPhone.replace(/\D/g, '');
      const params = newChatCourse.trim()
        ? [newChatName, newChatCourse]
        : [newChatName];
      const templateName = newChatCourse.trim() ? 'primeiro_contato_pos' : 'hello_world';
      const lang = newChatCourse.trim() ? 'pt_BR' : 'en_US';

      await api.post('/send/template', {
        to: phone,
        template_name: templateName,
        language: lang,
        channel_id: activeChannel.id,
        parameters: params,
        contact_name: newChatName,
      });
      setShowNewChat(false);
      setNewChatPhone('');
      setNewChatName('');
      setNewChatCourse('');
      await loadContacts();
    } catch (err) {
      console.error('Erro:', err);
    } finally {
      setSendingTemplate(false);
    }
  };

  const getInitials = (name: string) => name.split(' ').map((n) => n[0]).join('').toUpperCase().slice(0, 2);
  const getAvatarColor = (name: string) => {
    const c = ['from-blue-500 to-blue-600','from-purple-500 to-purple-600','from-emerald-500 to-emerald-600','from-orange-500 to-orange-600','from-pink-500 to-pink-600','from-cyan-500 to-cyan-600','from-indigo-500 to-indigo-600'];
    return c[name.charCodeAt(0) % c.length];
  };
  const formatTime = (ts: string) => new Date(ts).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  const formatDate = (ts: string) => {
    const d = new Date(ts); const t = new Date();
    if (d.toDateString() === t.toDateString()) return 'Hoje';
    const y = new Date(t); y.setDate(y.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return 'Ontem';
    return d.toLocaleDateString('pt-BR');
  };
  const formatFullDate = (ts: string) => new Date(ts).toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' });
  const getStatusIcon = (s: string) => {
    switch (s) {
      case 'sent': return <Check className="w-3.5 h-3.5 text-gray-400" />;
      case 'delivered': return <CheckCheck className="w-3.5 h-3.5 text-gray-400" />;
      case 'read': return <CheckCheck className="w-3.5 h-3.5 text-blue-400" />;
      default: return <Clock className="w-3.5 h-3.5 text-gray-400" />;
    }
  };
  const getStatusConfig = (s: string) => leadStatuses.find(x => x.value === s) || leadStatuses[0];
  const getTagColorConfig = (c: string) => tagColors.find(x => x.value === c) || tagColors[0];

  const filteredContacts = contacts.filter(c => {
    const ms = c.name.toLowerCase().includes(search.toLowerCase()) || c.wa_id.includes(search);
    const mst = statusFilter === 'todos' || c.lead_status === statusFilter;
    return ms && mst;
  });

  const groupedMessages: { date: string; msgs: Message[] }[] = [];
  messages.forEach((msg) => {
    const date = formatDate(msg.timestamp);
    const last = groupedMessages[groupedMessages.length - 1];
    if (last && last.date === date) last.msgs.push(msg);
    else groupedMessages.push({ date, msgs: [msg] });
  });

  return (
    <AppLayout fullWidth>
      <div className="flex h-full">
        {/* Sidebar Contatos */}
        <div className={`${selectedContact ? 'hidden lg:flex' : 'flex'} w-full lg:w-[340px] flex-col border-r border-gray-200 bg-white flex-shrink-0`}>
          <div className="px-4 py-3 border-b border-gray-100">
            {/* Channel Selector */}
            <div className="relative mb-3">
              <button
                onClick={() => setShowChannelMenu(!showChannelMenu)}
                className="w-full flex items-center justify-between px-3 py-2.5 bg-gradient-to-r from-[#0f1b2d] to-[#1a2d47] rounded-xl text-left transition-all hover:shadow-md"
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 bg-[#2A658F] rounded-lg flex items-center justify-center">
                    <Radio className="w-4 h-4 text-white" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-white">{activeChannel?.name || 'Selecionar canal'}</p>
                    <p className="text-[11px] text-gray-400">
                      {activeChannel ? `+${activeChannel.phone_number.replace(/(\d{2})(\d{2})(\d{5})(\d{4})/, '$1 $2 $3-$4')}` : 'Nenhum canal'}
                    </p>
                  </div>
                </div>
                <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform ${showChannelMenu ? 'rotate-180' : ''}`} />
              </button>
              {showChannelMenu && (
                <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-xl border border-gray-200 shadow-xl z-20 overflow-hidden">
                  {channels.map(ch => (
                    <button
                      key={ch.id}
                      onClick={() => { setActiveChannel(ch); setShowChannelMenu(false); setSelectedContact(null); setLoading(true); }}
                      className={`w-full flex items-center gap-3 px-3 py-2.5 hover:bg-gray-50 transition-colors text-left ${activeChannel?.id === ch.id ? 'bg-[#2A658F]/5' : ''}`}
                    >
                      <div className={`w-2 h-2 rounded-full ${activeChannel?.id === ch.id ? 'bg-[#2A658F]' : 'bg-gray-300'}`} />
                      <div>
                        <p className="text-sm font-medium text-gray-800">{ch.name}</p>
                        <p className="text-[11px] text-gray-500">+{ch.phone_number}</p>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Buscar contato..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 transition-all outline-none"
              />
              {search && (
                <button onClick={() => setSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2">
                  <XCircle className="w-4 h-4 text-gray-400" />
                </button>
              )}
            </div>

            {/* Nova conversa */}
            <button
              onClick={() => setShowNewChat(true)}
              className="w-full mt-2 flex items-center justify-center gap-2 py-2 bg-gradient-to-r from-[#2A658F] to-[#3d7ba8] text-white text-xs font-medium rounded-xl hover:shadow-lg hover:shadow-[#2A658F]/30 transition-all"
            >
              <Plus className="w-3.5 h-3.5" />
              Nova conversa
            </button>

            {/* Status Filter */}
            <div className="flex gap-1.5 mt-3 overflow-x-auto pb-1">
              <button
                onClick={() => setStatusFilter('todos')}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-all ${statusFilter === 'todos' ? 'bg-[#2A658F] text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
              >
                Todos ({contacts.length})
              </button>
              {leadStatuses.map(s => {
                const count = contacts.filter(c => c.lead_status === s.value).length;
                if (count === 0) return null;
                return (
                  <button
                    key={s.value}
                    onClick={() => setStatusFilter(s.value)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition-all ${statusFilter === s.value ? `${s.bg} ${s.text} border ${s.border}` : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
                  >
                    {s.label} ({count})
                  </button>
                );
              })}
            </div>
          </div>

          {/* Contacts List */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="animate-pulse space-y-1 p-3">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="flex items-center gap-3 p-3">
                    <div className="w-11 h-11 bg-gray-100 rounded-full" />
                    <div className="flex-1 space-y-2">
                      <div className="h-4 bg-gray-100 rounded w-28" />
                      <div className="h-3 bg-gray-100 rounded w-40" />
                    </div>
                  </div>
                ))}
              </div>
            ) : filteredContacts.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-gray-400">
                <MessageCircle className="w-10 h-10 mb-2" />
                <p className="text-sm">Nenhuma conversa</p>
              </div>
            ) : (
              filteredContacts.map((contact) => {
                const st = getStatusConfig(contact.lead_status);
                return (
                  <button
                    key={contact.wa_id}
                    onClick={() => setSelectedContact(contact)}
                    className={`w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left border-b border-gray-50 ${selectedContact?.wa_id === contact.wa_id ? 'bg-[#2A658F]/5' : ''}`}
                  >
                    <div className="relative flex-shrink-0">
                      <div className={`w-11 h-11 rounded-full bg-gradient-to-br ${getAvatarColor(contact.name)} flex items-center justify-center text-white font-semibold text-xs shadow-sm`}>
                        {getInitials(contact.name || contact.wa_id)}
                      </div>
                      <div className={`absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 ${st.color} rounded-full border-2 border-white`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <p className="font-medium text-sm text-[#27273D] truncate">{contact.name || contact.wa_id}</p>
                        {contact.last_message_time && (
                          <span className="text-[11px] text-gray-400 ml-2 flex-shrink-0">{formatTime(contact.last_message_time)}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        {contact.tags.length > 0 && (
                          <div className="flex gap-0.5">
                            {contact.tags.slice(0, 2).map(tag => {
                              const tc = getTagColorConfig(tag.color);
                              return <span key={tag.id} className={`w-2 h-2 rounded-full ${tc.bg}`} />;
                            })}
                          </div>
                        )}
                        <p className="text-xs text-gray-500 truncate">
                          {contact.direction === 'outbound' && '✓ '}
                          {contact.last_message || 'Sem mensagens'}
                        </p>
                      </div>
                    </div>
                    {contact.unread > 0 && (
                      <span className="w-5 h-5 bg-[#2A658F] text-white text-[10px] font-bold rounded-full flex items-center justify-center flex-shrink-0">
                        {contact.unread}
                      </span>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Chat Area */}
        <div className={`${selectedContact ? 'flex' : 'hidden lg:flex'} flex-1 flex-col min-w-0`}>
          {selectedContact ? (
            <>
              <div className="px-4 py-3 border-b border-gray-200 bg-white flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <button onClick={() => setSelectedContact(null)} className="lg:hidden p-1 hover:bg-gray-100 rounded-lg">
                    <ArrowLeft className="w-5 h-5 text-gray-600" />
                  </button>
                  <div className={`w-9 h-9 rounded-full bg-gradient-to-br ${getAvatarColor(selectedContact.name)} flex items-center justify-center text-white font-semibold text-xs`}>
                    {getInitials(selectedContact.name || selectedContact.wa_id)}
                  </div>
                  <div>
                    <p className="font-semibold text-sm text-[#27273D]">{selectedContact.name || selectedContact.wa_id}</p>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-500">+{selectedContact.wa_id}</span>
                      <span className={`inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded-md ${getStatusConfig(selectedContact.lead_status).bg} ${getStatusConfig(selectedContact.lead_status).text}`}>
                        {getStatusConfig(selectedContact.lead_status).label}
                      </span>
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => setShowCRM(!showCRM)}
                  className={`p-2 rounded-lg transition-colors ${showCRM ? 'bg-[#2A658F]/10 text-[#2A658F]' : 'hover:bg-gray-100 text-gray-500'}`}
                >
                  <User className="w-5 h-5" />
                </button>
              </div>

              <div className="flex flex-1 overflow-hidden">
                {/* Messages */}
                <div className="flex-1 flex flex-col min-w-0">
                  <div className="flex-1 overflow-y-auto px-4 py-4 space-y-1 bg-[#f0f2f5]">
                    {groupedMessages.map((group) => (
                      <div key={group.date}>
                        <div className="flex justify-center my-3">
                          <span className="px-3 py-1 bg-white/90 rounded-lg text-[11px] text-gray-500 shadow-sm font-medium">{group.date}</span>
                        </div>
                        {group.msgs.map((msg) => (
                          <div key={msg.id} className={`flex mb-1 ${msg.direction === 'outbound' ? 'justify-end' : 'justify-start'}`}>
                            <div className={`max-w-[70%] px-3 py-2 rounded-2xl shadow-sm ${
                              msg.direction === 'outbound' ? 'bg-[#2A658F] text-white rounded-br-sm' : 'bg-white text-gray-800 rounded-bl-sm'
                            }`}>
                              <p className="text-[13.5px] whitespace-pre-wrap break-words leading-relaxed">{msg.content}</p>
                              <div className={`flex items-center justify-end gap-1 mt-0.5 ${msg.direction === 'outbound' ? 'text-white/60' : 'text-gray-400'}`}>
                                <span className="text-[10px]">{formatTime(msg.timestamp)}</span>
                                {msg.direction === 'outbound' && getStatusIcon(msg.status)}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    ))}
                    <div ref={messagesEndRef} />
                  </div>

                  <div className="px-4 py-3 border-t border-gray-200 bg-white">
                    <div className="flex items-end gap-2">
                      <textarea
                        value={newMessage}
                        onChange={(e) => setNewMessage(e.target.value)}
                        onKeyDown={handleKeyPress}
                        placeholder="Digite uma mensagem..."
                        rows={1}
                        className="flex-1 px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 resize-none focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 transition-all outline-none"
                      />
                      <button
                        onClick={handleSend}
                        disabled={!newMessage.trim() || sending}
                        className="flex items-center justify-center w-10 h-10 bg-gradient-to-r from-[#2A658F] to-[#3d7ba8] rounded-xl text-white hover:shadow-lg hover:shadow-[#2A658F]/30 transition-all disabled:opacity-50 flex-shrink-0"
                      >
                        <Send className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>

                {/* CRM Panel */}
                {showCRM && (
                  <div className="w-[300px] border-l border-gray-200 bg-white overflow-y-auto flex-shrink-0 hidden xl:block">
                    <div className="p-4 space-y-5">
                      <div className="text-center pb-4 border-b border-gray-100">
                        <div className={`w-16 h-16 rounded-full bg-gradient-to-br ${getAvatarColor(selectedContact.name)} flex items-center justify-center text-white font-bold text-xl shadow-md mx-auto`}>
                          {getInitials(selectedContact.name || selectedContact.wa_id)}
                        </div>
                        <p className="font-semibold text-[#27273D] mt-3">{selectedContact.name || selectedContact.wa_id}</p>
                        <div className="flex items-center justify-center gap-1.5 mt-1 text-gray-500">
                          <Phone className="w-3.5 h-3.5" />
                          <span className="text-xs">+{selectedContact.wa_id}</span>
                        </div>
                        {selectedContact.created_at && (
                          <div className="flex items-center justify-center gap-1.5 mt-1 text-gray-400">
                            <Calendar className="w-3.5 h-3.5" />
                            <span className="text-xs">Desde {formatFullDate(selectedContact.created_at)}</span>
                          </div>
                        )}
                      </div>

                      {/* Lead Status */}
                      <div>
                        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Status do Lead</p>
                        <div className="relative">
                          <button
                            onClick={() => setShowStatusMenu(!showStatusMenu)}
                            className={`w-full flex items-center justify-between px-3 py-2 rounded-xl border ${getStatusConfig(selectedContact.lead_status).border} ${getStatusConfig(selectedContact.lead_status).bg} transition-all`}
                          >
                            <div className="flex items-center gap-2">
                              <div className={`w-2.5 h-2.5 rounded-full ${getStatusConfig(selectedContact.lead_status).color}`} />
                              <span className={`text-sm font-medium ${getStatusConfig(selectedContact.lead_status).text}`}>
                                {getStatusConfig(selectedContact.lead_status).label}
                              </span>
                            </div>
                            <ChevronDown className="w-4 h-4 text-gray-400" />
                          </button>
                          {showStatusMenu && (
                            <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-xl border border-gray-200 shadow-lg z-10 overflow-hidden">
                              {leadStatuses.map(s => (
                                <button key={s.value} onClick={() => updateLeadStatus(s.value)} className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-50 transition-colors text-left">
                                  <div className={`w-2.5 h-2.5 rounded-full ${s.color}`} />
                                  <span className="text-sm text-gray-700">{s.label}</span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Tags */}
                      <div>
                        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Tags</p>
                        <div className="flex flex-wrap gap-1.5 mb-2">
                          {selectedContact.tags.map(tag => {
                            const tc = getTagColorConfig(tag.color);
                            return (
                              <span key={tag.id} className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-lg ${tc.bg} ${tc.text}`}>
                                {tag.name}
                                <button onClick={() => removeTag(tag.id)} className="hover:opacity-70"><X className="w-3 h-3" /></button>
                              </span>
                            );
                          })}
                        </div>
                        <button onClick={() => setShowTagMenu(!showTagMenu)} className="flex items-center gap-1 text-xs text-[#2A658F] hover:text-[#1a4a6e] font-medium">
                          <Plus className="w-3.5 h-3.5" /> Adicionar tag
                        </button>
                        {showTagMenu && (
                          <div className="mt-2 bg-gray-50 rounded-xl p-3 space-y-2">
                            {allTags.filter(t => !selectedContact.tags.find(ct => ct.id === t.id)).map(tag => {
                              const tc = getTagColorConfig(tag.color);
                              return (
                                <button key={tag.id} onClick={() => { addTag(tag.id); setShowTagMenu(false); }} className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-medium ${tc.bg} ${tc.text} hover:opacity-80 transition-opacity`}>
                                  {tag.name}
                                </button>
                              );
                            })}
                            <div className="pt-2 border-t border-gray-200">
                              <p className="text-[10px] text-gray-400 uppercase font-semibold mb-1.5">Criar nova tag</p>
                              <input value={newTagName} onChange={(e) => setNewTagName(e.target.value)} placeholder="Nome da tag" className="w-full px-2.5 py-1.5 text-xs text-gray-800 border border-gray-200 rounded-lg outline-none focus:border-[#2A658F]" />
                              <div className="flex gap-1 mt-1.5">
                                {tagColors.map(c => (
                                  <button key={c.value} onClick={() => setNewTagColor(c.value)} className={`w-5 h-5 rounded-full ${c.bg} ${newTagColor === c.value ? 'ring-2 ring-offset-1 ring-[#2A658F]' : ''}`} />
                                ))}
                              </div>
                              <button onClick={() => { createTag(); setShowTagMenu(false); }} disabled={!newTagName.trim()} className="w-full mt-2 px-2.5 py-1.5 bg-[#2A658F] text-white text-xs font-medium rounded-lg disabled:opacity-50 hover:bg-[#1a4a6e] transition-colors">
                                Criar tag
                              </button>
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Notes */}
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Notas</p>
                          {!editingNotes && <button onClick={() => setEditingNotes(true)} className="text-xs text-[#2A658F] font-medium">Editar</button>}
                        </div>
                        {editingNotes ? (
                          <div>
                            <textarea value={notesValue} onChange={(e) => setNotesValue(e.target.value)} rows={4} className="w-full px-3 py-2 text-sm text-gray-800 border border-gray-200 rounded-xl outline-none focus:border-[#2A658F] resize-none" placeholder="Adicione notas sobre este lead..." />
                            <div className="flex gap-2 mt-2">
                              <button onClick={saveNotes} className="px-3 py-1.5 bg-[#2A658F] text-white text-xs font-medium rounded-lg hover:bg-[#1a4a6e]">Salvar</button>
                              <button onClick={() => { setEditingNotes(false); setNotesValue(selectedContact.notes || ''); }} className="px-3 py-1.5 text-gray-500 text-xs font-medium rounded-lg hover:bg-gray-100">Cancelar</button>
                            </div>
                          </div>
                        ) : (
                          <div className="bg-gray-50 rounded-xl p-3 min-h-[60px]">
                            <p className="text-sm text-gray-600 whitespace-pre-wrap">{selectedContact.notes || 'Sem notas'}</p>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-gray-400 bg-[#f0f2f5]">
              <div className="w-20 h-20 bg-white rounded-full flex items-center justify-center mb-4 shadow-sm">
                <MessageCircle className="w-10 h-10 text-gray-300" />
              </div>
              <p className="text-lg font-medium text-[#27273D]">Cenat WhatsApp</p>
              <p className="text-sm mt-1 text-gray-400">Selecione uma conversa para começar</p>
            </div>
          )}
        </div>
      </div>

      {/* Modal Nova Conversa */}
      {showNewChat && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setShowNewChat(false)}>
          <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-2xl mx-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-[#27273D]">Nova Conversa</h2>
              <button onClick={() => setShowNewChat(false)} className="p-1 hover:bg-gray-100 rounded-lg">
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-600 mb-1.5">Telefone do lead</label>
                <input
                  type="text"
                  value={newChatPhone}
                  onChange={e => setNewChatPhone(e.target.value)}
                  placeholder="5583988001234"
                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 outline-none"
                />
                <p className="text-[11px] text-gray-400 mt-1">DDD + número com 9 (sem espaços)</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-600 mb-1.5">Nome do lead</label>
                <input
                  type="text"
                  value={newChatName}
                  onChange={e => setNewChatName(e.target.value)}
                  placeholder="Maria Silva"
                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-600 mb-1.5">Nome da Pós-Graduação</label>
                <input
                  type="text"
                  value={newChatCourse}
                  onChange={e => setNewChatCourse(e.target.value)}
                  placeholder="Boas práticas: Como trabalhar com pessoas que ouvem vozes"
                  className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 outline-none"
                />
                <p className="text-[11px] text-gray-400 mt-1">Será enviado no template de primeiro contato</p>
              </div>
            </div>

            <button
              onClick={handleNewChat}
              disabled={sendingTemplate || !newChatPhone.trim() || !newChatName.trim()}
              className="w-full mt-6 py-3 bg-gradient-to-r from-[#2A658F] to-[#3d7ba8] text-white font-medium rounded-xl hover:shadow-lg hover:shadow-[#2A658F]/30 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {sendingTemplate ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Enviando...
                </>
              ) : (
                <>
                  <Send className="w-4 h-4" />
                  Enviar template
                </>
              )}
            </button>
          </div>
        </div>
      )}
    </AppLayout>
  );
}
