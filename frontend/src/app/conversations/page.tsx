'use client';

import { useEffect, useState, useRef } from 'react';
import {
  Send,
  Search,
  MessageCircle,
  Check,
  CheckCheck,
  Clock,
  XCircle,
  ArrowLeft,
  Plus,
  X,
  User,
  Phone,
  Calendar,
  ChevronDown,
  Radio,
  Loader2,
  SlidersHorizontal,
  Bot,
  Hash,
  Paperclip,
  Mic,
  Image as ImageIcon,
  FileText,
  Square,
  Trash2
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

interface ExactLeadResult {
  id: number;
  exact_id: number;
  name: string;
  phone1: string | null;
  sub_source: string | null;
  stage: string | null;
}

interface Contact {
  wa_id: string;
  name: string;
  lead_status: string;
  notes: string | null;
  ai_active: boolean;
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
  sent_by_ai: boolean;
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
  const [sendingTemplate, setSendingTemplate] = useState(false);
  const [templates, setTemplates] = useState<any[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<any>(null);
  const [templateParams, setTemplateParams] = useState<string[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [notesValue, setNotesValue] = useState('');
  const [togglingAI, setTogglingAI] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [exactLeadResults, setExactLeadResults] = useState<ExactLeadResult[]>([]);
  const [showLeadSuggestions, setShowLeadSuggestions] = useState(false);
  const [searchingLeads, setSearchingLeads] = useState(false);
  const [sendFeedback, setSendFeedback] = useState<'ok' | 'error' | null>(null);
  const [tagFilter, setTagFilter] = useState<number[]>([]);
  const [unreadFilter, setUnreadFilter] = useState(false);
  const [aiFilter, setAiFilter] = useState<'all' | 'on' | 'off'>('all');
  const [showFilters, setShowFilters] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [showScrollDown, setShowScrollDown] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [showAttachMenu, setShowAttachMenu] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const prevMsgCountRef = useRef<number>(0);
  const isTabFocusedRef = useRef<boolean>(true);
  const notifAudioRef = useRef<HTMLAudioElement | null>(null);
  const attachMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const audioInputRef = useRef<HTMLInputElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const recordingIntervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => { setMounted(true); }, []);

  // Inicializar áudio de notificação
  useEffect(() => {
    notifAudioRef.current = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1pbJF/f3R1eYiNjI2Uf39sZnJ+goOHkZaOgHVqcHuDh4qPkpCIe3FrbnZ+hIuRk5KOh31zbHB3gIeMkZOTj4d9c21udoCGi5KUk4+Ie3Jtb3eAhouRlJOPiHxybnB4gIaMkZSTj4h7cm5wd4CGjJGUk4+IfHJub3iAho2RlJOQiHxybm94f4aNkZSTkId9cm5vd4CGjZGUk5CIfXJub3eAho2RlJOQiHxybm94f4aNkZSTkIh8cm5veICGjZKUk5CIfHJub3h/ho2SlJOQiHxybm94f4aNkpSTkIh8cm5veICGjZKUk5CIfHJucHh/ho2SlJOQiHxybm94gIaNkpSTkIh8cm5veICGjZKVk5CIfHJucHh/ho2SlJOPiHxybm94gIaNkpSUkIh8cW5veICHjZKUk5CIfHFucHmAho2SlJSQiHxybm94gIeNkpSTkIh8cm5veICGjZKVk5GIfHFub3mAho6SlJSQiHxxbm94gIeOkpWUkIh8cW1veYCHjpKVlJCIfHFub3mAh46SlZSQiHxxbm94gIeOk5WUkIl8cG1weYCHj5OVlJCJe3FtcHmBh4+TlZSQiXxxbXB5gIePk5WVkIl7cW1veYCHj5OVlZCJfHBtcHmBh4+UlZWQiXxwbXB5gIeQlJaVkIl7cG1weYGHkJSWlZCJe3FtcHmAh5CUlpWRiXtwbXB5gYeQlJaWkIl7cG1xeYCIkJSWlpGJe3BtcHqBh5GUlpaRiXtwbHB6gYiRlZaWkYl7cGxxeoCIkZWWlpGJe3BscXqBiJGVl5aRiXtwbHF6gYiRlZeXkYl6cGxxeoGIkpaXl5GJe3BscXqBiJKWl5eRiXtwbHF6gYiSlpeXkol6b2xxeoGIkpeYl5KJe29scXuBiZKXmJeSiXtvbHF7gYmTl5iXkol6b2xxe4GJk5eYl5KKem9scXuCiZOXmJiSinpvbHF7gYmTmJiYkop6b2txe4KJk5iYmJKKem9rcXyCiZOYmZiSinpva3F8gomUmJmYk4p5b2txfIKJlJmZmJOKeW9rcXyCipSZmZmTinpva3F8gomUmZqZk4p5b2txfIKKlJmamZOKem9rcXyCipSZmpqTi3luanJ8goqVmpqak4t5bmtzfIKKlZqampOLem5rc3yCi5WampuTi3luanN8g4uWmpubk4t5bmtzfYOLlpucm5OLeW5qc32Di5abnJyTjHluanN9g4uWm5ycl');
    notifAudioRef.current.volume = 0.3;
  }, []);

  // Detectar foco da aba
  useEffect(() => {
    const onFocus = () => { isTabFocusedRef.current = true; setUnreadCount(0); };
    const onBlur = () => { isTabFocusedRef.current = false; };
    window.addEventListener('focus', onFocus);
    window.addEventListener('blur', onBlur);
    return () => { window.removeEventListener('focus', onFocus); window.removeEventListener('blur', onBlur); };
  }, []);

  // Atualizar título da aba com contador
  useEffect(() => {
    document.title = unreadCount > 0 ? `(${unreadCount}) Conversas - Cenat Hub` : 'Conversas - Cenat Hub';
  }, [unreadCount]);

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

  const selectedWaId = selectedContact?.wa_id || null;

  useEffect(() => {
    if (selectedWaId) {
      prevMsgCountRef.current = 0;
      setLoadingMessages(true);
      setMessages([]);
      loadMessages(selectedWaId);
      setNotesValue(selectedContact?.notes || '');
      // Marcar como lido sem forçar reload da lista
      api.post(`/contacts/${selectedWaId}/read`).catch(() => {});
      const interval = setInterval(() => loadMessages(selectedWaId), 3000);
      return () => clearInterval(interval);
    }
  }, [selectedWaId]);

  // Scroll simples: sempre vai pro final quando mensagens mudam
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
        if (updated) {
          // Só atualiza se algo mudou de verdade
          const changed = updated.name !== selectedContact.name
            || updated.lead_status !== selectedContact.lead_status
            || updated.notes !== selectedContact.notes
            || updated.ai_active !== selectedContact.ai_active
            || updated.unread !== selectedContact.unread
            || JSON.stringify(updated.tags) !== JSON.stringify(selectedContact.tags);
          if (changed) setSelectedContact(updated);
        }
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
      const newMsgs: Message[] = res.data;

      // Detectar novas mensagens inbound para notificação
      if (prevMsgCountRef.current > 0 && newMsgs.length > prevMsgCountRef.current) {
        const newOnes = newMsgs.slice(prevMsgCountRef.current);
        const hasInbound = newOnes.some(m => m.direction === 'inbound');
        if (hasInbound && !isTabFocusedRef.current) {
          setUnreadCount(prev => prev + newOnes.filter(m => m.direction === 'inbound').length);
          try { notifAudioRef.current?.play(); } catch {}
        }
      }
      prevMsgCountRef.current = newMsgs.length;

      setMessages(newMsgs);
      setLoadingMessages(false);
    } catch (err) {
      console.error('Erro:', err);
      setLoadingMessages(false);
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
    setSendFeedback(null);
    try {
      await api.post('/send/text', {
        to: selectedContact.wa_id,
        text: newMessage,
        channel_id: activeChannel.id,
      });
      setNewMessage('');
      setSendFeedback('ok');
      setTimeout(() => setSendFeedback(null), 2000);
      await loadMessages(selectedContact.wa_id);
      await loadContacts();
    } catch (err) {
      console.error('Erro:', err);
      setSendFeedback('error');
      setTimeout(() => setSendFeedback(null), 3000);
    } finally {
      setSending(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  // === Upload de mídia ===
  const FILE_SIZE_LIMITS: Record<string, number> = {
    image: 5 * 1024 * 1024,      // 5MB
    video: 16 * 1024 * 1024,     // 16MB
    audio: 16 * 1024 * 1024,     // 16MB
    document: 100 * 1024 * 1024, // 100MB
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const handleFileUpload = async (file: File, type: 'image' | 'document' | 'audio') => {
    if (!selectedContact || !activeChannel) return;

    // Validar tamanho
    const limit = FILE_SIZE_LIMITS[type] || FILE_SIZE_LIMITS.document;
    if (file.size > limit) {
      setSendFeedback('error');
      setTimeout(() => setSendFeedback(null), 4000);
      alert(`Arquivo muito grande (${formatFileSize(file.size)}). Limite para ${type}: ${formatFileSize(limit)}`);
      return;
    }

    setSending(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('to', selectedContact.wa_id);
      formData.append('channel_id', String(activeChannel.id));
      formData.append('type', type);
      await api.post('/send/media', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setSendFeedback('ok');
      setTimeout(() => setSendFeedback(null), 2000);
      await loadMessages(selectedContact.wa_id);
      await loadContacts();
    } catch (err) {
      console.error('Erro ao enviar arquivo:', err);
      setSendFeedback('error');
      setTimeout(() => setSendFeedback(null), 3000);
    } finally {
      setSending(false);
    }
  };

  // === Gravação de áudio ===
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/ogg; codecs=opus' });
        if (audioBlob.size > 0 && selectedContact && activeChannel) {
          setSending(true);
          const formData = new FormData();
          formData.append('file', audioBlob, 'audio.ogg');
          formData.append('to', selectedContact.wa_id);
          formData.append('channel_id', String(activeChannel.id));
          formData.append('type', 'audio');
          try {
            await api.post('/send/media', formData, {
              headers: { 'Content-Type': 'multipart/form-data' },
            });
            setSendFeedback('ok');
            setTimeout(() => setSendFeedback(null), 2000);
            await loadMessages(selectedContact.wa_id);
            await loadContacts();
          } catch (err) {
            console.error('Erro ao enviar áudio:', err);
            setSendFeedback('error');
            setTimeout(() => setSendFeedback(null), 3000);
          } finally {
            setSending(false);
          }
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
      setRecordingTime(0);
      recordingIntervalRef.current = setInterval(() => {
        setRecordingTime(prev => prev + 1);
      }, 1000);
    } catch (err) {
      console.error('Erro ao acessar microfone:', err);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
    if (recordingIntervalRef.current) {
      clearInterval(recordingIntervalRef.current);
      recordingIntervalRef.current = null;
    }
    setRecordingTime(0);
  };

  const cancelRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.ondataavailable = null;
      mediaRecorderRef.current.onstop = () => {
        mediaRecorderRef.current?.stream?.getTracks().forEach(t => t.stop());
      };
      mediaRecorderRef.current.stop();
    }
    setIsRecording(false);
    if (recordingIntervalRef.current) {
      clearInterval(recordingIntervalRef.current);
      recordingIntervalRef.current = null;
    }
    setRecordingTime(0);
  };

  const formatRecordingTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  // Fechar menu de anexo ao clicar fora
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (attachMenuRef.current && !attachMenuRef.current.contains(e.target as Node)) {
        setShowAttachMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleAI = async () => {
    if (!selectedContact) return;
    setTogglingAI(true);
    try {
      const newValue = !selectedContact.ai_active;
      await api.patch(`/ai/contacts/${selectedContact.wa_id}/toggle`, { ai_active: newValue });
      // Atualizar diretamente sem criar objeto novo + recarregar
      selectedContact.ai_active = newValue;
      setSelectedContact({ ...selectedContact });
    } catch (err) {
      console.error("Erro ao alternar IA:", err);
    } finally {
      setTogglingAI(false);
    }
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

  const loadTemplates = async () => {
    if (!activeChannel) return;
    setLoadingTemplates(true);
    try {
      const res = await api.get(`/channels/${activeChannel.id}/templates`);
      setTemplates(res.data);
    } catch (err) { console.error('Erro:', err); }
    finally { setLoadingTemplates(false); }
  };

  const selectTemplate = (t: any) => {
    setSelectedTemplate(t);
    setTemplateParams(new Array(t.parameters.length).fill(''));
  };

  const updateParam = (index: number, value: string) => {
    const newParams = [...templateParams];
    newParams[index] = value;
    setTemplateParams(newParams);
  };

  const getPreview = () => {
    if (!selectedTemplate) return '';
    let text = selectedTemplate.body;
    templateParams.forEach((p, i) => {
      text = text.replace(`{{${i + 1}}}`, p || `[Variável ${i + 1}]`);
    });
    return text;
  };

  const handleNewChat = async () => {
    if (!newChatPhone.trim() || !newChatName.trim() || !activeChannel || !selectedTemplate) return;
    setSendingTemplate(true);
    try {
      const phone = newChatPhone.replace(/\D/g, '');
      await api.post('/send/template', {
        to: phone,
        template_name: selectedTemplate.name,
        language: selectedTemplate.language,
        channel_id: activeChannel.id,
        parameters: templateParams.length > 0 ? templateParams : [],
        contact_name: newChatName,
      });
      setShowNewChat(false);
      setNewChatPhone('');
      setNewChatName('');
      setSelectedTemplate(null);
      setTemplateParams([]);
      await loadContacts();
    } catch (err) {
      console.error('Erro:', err);
    } finally {
      setSendingTemplate(false);
    }
  };

  const searchExactLeads = async (query: string) => {
    if (query.length < 2) {
      setExactLeadResults([]);
      setShowLeadSuggestions(false);
      return;
    }
    setSearchingLeads(true);
    try {
      const res = await api.get('/exact-leads', { params: { search: query, limit: 8 } });
      setExactLeadResults(res.data);
      setShowLeadSuggestions(true);
    } catch (err) {
      console.error('Erro ao buscar leads:', err);
    } finally {
      setSearchingLeads(false);
    }
  };

  const handleSearchChange = (value: string) => {
    setSearch(value);
    searchExactLeads(value);
  };

  const selectExactLead = (lead: ExactLeadResult) => {
    setShowLeadSuggestions(false);
    setSearch('');
    setNewChatPhone(lead.phone1 || '');
    setNewChatName(lead.name || '');
    setShowNewChat(true);
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
    const mtag = tagFilter.length === 0 || c.tags.some(t => tagFilter.includes(t.id));
    const mur = !unreadFilter || c.unread > 0;
    const mai = aiFilter === 'all' || (aiFilter === 'on' ? c.ai_active : !c.ai_active);
    return ms && mst && mtag && mur && mai;
  });

  const hasActiveFilters = tagFilter.length > 0 || unreadFilter || aiFilter !== 'all';

  const clearAllFilters = () => {
    setStatusFilter('todos');
    setTagFilter([]);
    setUnreadFilter(false);
    setAiFilter('all');
    setShowFilters(false);
  };

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

        {/* SIDEBAR CONTATOS */}
        <div className={`${selectedContact ? 'hidden lg:flex' : 'flex'} w-full lg:w-[350px] flex-col border-r border-gray-100 bg-white flex-shrink-0`}>

          <div className="px-4 pt-4 pb-3 space-y-3">

            {/* Channel Selector */}
            <div className="relative">
              <button
                onClick={() => setShowChannelMenu(!showChannelMenu)}
                className="w-full flex items-center justify-between px-3 py-2.5 bg-[#0f1b2d] rounded-xl text-left transition-all hover:bg-[#162538]"
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 bg-[#2A658F]/30 rounded-lg flex items-center justify-center">
                    <Radio className="w-3.5 h-3.5 text-[#4d9fd4]" />
                  </div>
                  <div>
                    <p className="text-[13px] font-medium text-white leading-tight">{activeChannel?.name || 'Selecionar canal'}</p>
                    <p className="text-[11px] text-gray-500 leading-tight">
                      {activeChannel ? `+${activeChannel.phone_number.replace(/(\d{2})(\d{2})(\d{5})(\d{4})/, '$1 $2 $3-$4')}` : 'Nenhum canal'}
                    </p>
                  </div>
                </div>
                <ChevronDown className={`w-4 h-4 text-gray-500 transition-transform duration-200 ${showChannelMenu ? 'rotate-180' : ''}`} />
              </button>

              {showChannelMenu && (
                <div className="absolute top-full left-0 right-0 mt-1.5 bg-white rounded-xl border border-gray-200 shadow-xl z-20 overflow-hidden">
                  {channels.map(ch => (
                    <button
                      key={ch.id}
                      onClick={() => { setActiveChannel(ch); setShowChannelMenu(false); setSelectedContact(null); setLoading(true); }}
                      className={`w-full flex items-center gap-3 px-3 py-2.5 hover:bg-gray-50 transition-colors text-left ${activeChannel?.id === ch.id ? 'bg-[#2A658F]/5' : ''}`}
                    >
                      <div className={`w-2 h-2 rounded-full ${activeChannel?.id === ch.id ? 'bg-[#2A658F]' : 'bg-gray-300'}`} />
                      <div>
                        <p className="text-sm font-medium text-gray-800">{ch.name}</p>
                        <p className="text-[11px] text-gray-400">+{ch.phone_number}</p>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Search + Nova conversa */}
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input
                  type="text"
                  placeholder="Buscar contato..."
                  value={search}
                  onChange={(e) => handleSearchChange(e.target.value)}
                  onFocus={() => { if (exactLeadResults.length > 0) setShowLeadSuggestions(true); }}
                  onBlur={() => setTimeout(() => setShowLeadSuggestions(false), 200)}
                  className="w-full pl-9 pr-8 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder:text-gray-400 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 focus:bg-white transition-all outline-none"
                />
                {search && (
                  <button onClick={() => { setSearch(''); setExactLeadResults([]); setShowLeadSuggestions(false); }} className="absolute right-2.5 top-1/2 -translate-y-1/2">
                    <XCircle className="w-4 h-4 text-gray-300 hover:text-gray-500 transition-colors" />
                  </button>
                )}

                {showLeadSuggestions && exactLeadResults.length > 0 && (
                  <div className="absolute top-full left-0 right-0 mt-1.5 bg-white rounded-xl border border-gray-200 shadow-xl z-30 max-h-[300px] overflow-y-auto">
                    <div className="px-3 py-2 border-b border-gray-100">
                      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">Leads Pós (Exact Spotter)</p>
                    </div>
                    {exactLeadResults.map(lead => (
                      <button
                        key={lead.id}
                        onMouseDown={() => selectExactLead(lead)}
                        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-gray-50 transition-colors text-left border-b border-gray-50 last:border-0"
                      >
                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-500 to-emerald-600 flex items-center justify-center text-white text-[10px] font-semibold flex-shrink-0">
                          {lead.name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-800 truncate">{lead.name}</p>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-[11px] text-gray-500">{lead.phone1 || 'Sem telefone'}</span>
                            {lead.sub_source && <span className="text-[10px] px-1.5 py-0.5 bg-emerald-50 text-emerald-700 rounded">{lead.sub_source}</span>}
                          </div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              <button
                onClick={() => setShowNewChat(true)}
                className="flex items-center justify-center w-10 h-10 bg-[#2A658F] text-white rounded-xl hover:bg-[#1f5375] active:scale-95 transition-all flex-shrink-0"
                title="Nova conversa"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>

            {/* Status Filter */}
            <div className="flex gap-1.5 overflow-x-auto pb-0.5 -mx-1 px-1">
              <button
                onClick={() => setStatusFilter('todos')}
                className={`px-2.5 py-1.5 rounded-lg text-[11px] font-medium whitespace-nowrap transition-all ${
                  statusFilter === 'todos'
                    ? 'bg-[#0f1b2d] text-white'
                    : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                }`}
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
                    className={`px-2.5 py-1.5 rounded-lg text-[11px] font-medium whitespace-nowrap transition-all ${
                      statusFilter === s.value
                        ? `${s.bg} ${s.text}`
                        : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                    }`}
                  >
                    {s.label} ({count})
                  </button>
                );
              })}
            </div>

            {/* Filtros avançados toggle */}
            <div className="flex items-center justify-between">
              <button
                onClick={() => setShowFilters(!showFilters)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
                  showFilters || hasActiveFilters
                    ? 'bg-[#2A658F]/10 text-[#2A658F]'
                    : 'text-gray-400 hover:bg-gray-50'
                }`}
              >
                <SlidersHorizontal className="w-3.5 h-3.5" />
                Filtros
                {hasActiveFilters && (
                  <span className="w-4 h-4 bg-[#2A658F] text-white text-[9px] font-bold rounded-full flex items-center justify-center">
                    {(tagFilter.length > 0 ? 1 : 0) + (unreadFilter ? 1 : 0) + (aiFilter !== 'all' ? 1 : 0)}
                  </span>
                )}
              </button>
              <span className="text-[11px] text-gray-400 tabular-nums">
                {filteredContacts.length} contato{filteredContacts.length !== 1 ? 's' : ''}
              </span>
            </div>

            {/* Painel de filtros avançados */}
            {showFilters && (
              <div className="space-y-2.5 pb-1">
                {/* Tag filter */}
                {allTags.length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Tags</p>
                    <div className="flex flex-wrap gap-1.5">
                      {allTags.map(tag => {
                        const tc = getTagColorConfig(tag.color);
                        const isActive = tagFilter.includes(tag.id);
                        return (
                          <button
                            key={tag.id}
                            onClick={() => setTagFilter(prev => isActive ? prev.filter(id => id !== tag.id) : [...prev, tag.id])}
                            className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                              isActive ? `${tc.bg} ${tc.text}` : 'bg-gray-50 text-gray-400 hover:bg-gray-100'
                            }`}
                          >
                            <Hash className="w-2.5 h-2.5" />
                            {tag.name}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Quick filters */}
                <div className="flex gap-1.5 flex-wrap">
                  <button
                    onClick={() => setUnreadFilter(!unreadFilter)}
                    className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
                      unreadFilter ? 'bg-[#2A658F]/10 text-[#2A658F]' : 'bg-gray-50 text-gray-400 hover:bg-gray-100'
                    }`}
                  >
                    <MessageCircle className="w-3 h-3" />
                    Não lidos
                  </button>
                  <button
                    onClick={() => setAiFilter(aiFilter === 'on' ? 'all' : 'on')}
                    className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
                      aiFilter === 'on' ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-50 text-gray-400 hover:bg-gray-100'
                    }`}
                  >
                    <Bot className="w-3 h-3" />
                    IA ativa
                  </button>
                  <button
                    onClick={() => setAiFilter(aiFilter === 'off' ? 'all' : 'off')}
                    className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium transition-all ${
                      aiFilter === 'off' ? 'bg-red-50 text-red-600' : 'bg-gray-50 text-gray-400 hover:bg-gray-100'
                    }`}
                  >
                    <Bot className="w-3 h-3" />
                    IA off
                  </button>
                </div>

                {/* Clear all */}
                {hasActiveFilters && (
                  <button
                    onClick={clearAllFilters}
                    className="text-[11px] text-gray-400 hover:text-red-500 transition-colors"
                  >
                    ✕ Limpar filtros
                  </button>
                )}
              </div>
            )}

          </div>

          {/* Contacts List */}
          <div className="flex-1 overflow-y-auto border-t border-gray-100">
            {loading ? (
              <div className="space-y-0 p-1.5">
                {[...Array(8)].map((_, i) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-3" style={{ opacity: 1 - i * 0.08 }}>
                    <div className="w-11 h-11 bg-gray-100 rounded-full flex-shrink-0 animate-pulse" />
                    <div className="flex-1 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="h-3.5 bg-gray-100 rounded-md animate-pulse" style={{ width: `${70 + (i % 3) * 20}px` }} />
                        <div className="h-2.5 bg-gray-100 rounded-md animate-pulse w-10" />
                      </div>
                      <div className="h-3 bg-gray-50 rounded-md animate-pulse" style={{ width: `${100 + (i % 4) * 25}px` }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : filteredContacts.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-gray-400">
                <MessageCircle className="w-8 h-8 mb-2 text-gray-300" />
                <p className="text-sm text-gray-400">Nenhuma conversa</p>
              </div>
            ) : (
              <div className="p-1.5">
                {filteredContacts.map((contact) => {
                  const st = getStatusConfig(contact.lead_status);
                  const isSelected = selectedContact?.wa_id === contact.wa_id;
                  return (
                    <button
                      key={contact.wa_id}
                      onClick={() => setSelectedContact(contact)}
                      className={`w-full flex items-center gap-3 px-3 py-3 rounded-xl text-left transition-all duration-150 mb-0.5 ${
                        isSelected
                          ? 'bg-[#2A658F]/8 border border-[#2A658F]/10'
                          : 'hover:bg-gray-50 border border-transparent'
                      }`}
                    >
                      <div className="relative flex-shrink-0">
                        <div className={`w-11 h-11 rounded-full bg-gradient-to-br ${getAvatarColor(contact.name)} flex items-center justify-center text-white font-semibold text-xs shadow-sm`}>
                          {getInitials(contact.name || contact.wa_id)}
                        </div>
                        <div className={`absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 ${st.color} rounded-full border-2 border-white`} />
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <p className={`font-medium text-[13px] truncate ${isSelected ? 'text-[#2A658F]' : 'text-[#27273D]'}`}>
                            {contact.ai_active && "🤖 "}{contact.name || contact.wa_id}
                          </p>
                          {contact.last_message_time && (
                            <span className="text-[11px] text-gray-400 ml-2 flex-shrink-0 tabular-nums">
                              {formatTime(contact.last_message_time)}
                            </span>
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
                          <p className="text-[12px] text-gray-400 truncate">
                            {contact.direction === 'outbound' && '✓ '}
                            {contact.last_message || 'Sem mensagens'}
                          </p>
                        </div>
                      </div>

                      {contact.unread > 0 && (
                        <span className="min-w-[20px] h-5 px-1 bg-[#2A658F] text-white text-[10px] font-bold rounded-full flex items-center justify-center flex-shrink-0">
                          {contact.unread}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

        </div>

        {/* ÁREA DO CHAT */}
        <div className={`${selectedContact ? 'flex' : 'hidden lg:flex'} flex-1 flex-col min-w-0`}>
          {selectedContact ? (
            <>
              {/* Chat Header */}
              <div className="px-4 py-3 border-b border-gray-100 bg-white flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <button onClick={() => setSelectedContact(null)} className="lg:hidden p-1.5 hover:bg-gray-100 rounded-lg transition-colors">
                    <ArrowLeft className="w-5 h-5 text-gray-500" />
                  </button>

                  <div className={`w-10 h-10 rounded-full bg-gradient-to-br ${getAvatarColor(selectedContact.name)} flex items-center justify-center text-white font-semibold text-xs`}>
                    {getInitials(selectedContact.name || selectedContact.wa_id)}
                  </div>

                  <div>
                    <p className="font-semibold text-[14px] text-[#27273D]">{selectedContact.name || selectedContact.wa_id}</p>
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] text-gray-400">+{selectedContact.wa_id}</span>
                      <span className={`inline-flex items-center px-1.5 py-0.5 text-[10px] font-medium rounded-md ${getStatusConfig(selectedContact.lead_status).bg} ${getStatusConfig(selectedContact.lead_status).text}`}>
                        {getStatusConfig(selectedContact.lead_status).label}
                      </span>
                    </div>
                  </div>
                </div>

                {/* ✅ ALTERAÇÃO 1: Botão Ligar + botão CRM */}
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => {
                      const phone = selectedContact?.wa_id || '';
                      window.dispatchEvent(new CustomEvent('cenat-call', { detail: { phone } }));
                    }}
                    className="p-2 rounded-xl hover:bg-green-50 text-gray-400 hover:text-green-600 transition-all duration-200"
                    title="Ligar para o lead"
                  >
                    <Phone className="w-5 h-5" />
                  </button>

                  <button
                    onClick={() => setShowCRM(!showCRM)}
                    className={`p-2 rounded-xl transition-all duration-200 ${
                      showCRM
                        ? 'bg-[#2A658F]/10 text-[#2A658F]'
                        : 'hover:bg-gray-100 text-gray-400'
                    }`}
                    title="Painel CRM"
                  >
                    <User className="w-5 h-5" />
                  </button>
                </div>
              </div>

              <div className="flex flex-1 overflow-hidden">

                {/* Messages */}
                <div className="flex-1 flex flex-col min-w-0">
                  <div
                    className="flex-1 overflow-y-auto px-4 py-4 space-y-1 bg-[#eef0f3] relative"
                  >
                    {loadingMessages ? (
                      <div className="space-y-3 py-4">
                        {[
                          { dir: 'in', w: '55%' },
                          { dir: 'in', w: '35%' },
                          { dir: 'out', w: '45%' },
                          { dir: 'in', w: '60%' },
                          { dir: 'out', w: '40%' },
                          { dir: 'out', w: '50%' },
                        ].map((s, i) => (
                          <div key={i} className={`flex ${s.dir === 'out' ? 'justify-end' : 'justify-start'}`}>
                            <div
                              className={`rounded-2xl animate-pulse ${s.dir === 'out' ? 'bg-[#2A658F]/20' : 'bg-white/80'}`}
                              style={{ width: s.w, height: `${32 + (i % 3) * 12}px`, opacity: 1 - i * 0.1 }}
                            />
                          </div>
                        ))}
                      </div>
                    ) : (
                    <>
                    {groupedMessages.map((group) => (
                      <div key={group.date}>
                        <div className="flex justify-center my-3">
                          <span className="px-3 py-1 bg-white rounded-lg text-[11px] text-gray-500 shadow-sm font-medium">
                            {group.date}
                          </span>
                        </div>

                        {group.msgs.map((msg) => (
                          <div key={msg.id} className={`flex mb-1.5 ${msg.direction === 'outbound' ? 'justify-end' : 'justify-start'}`}>
                            <div className={`max-w-[70%] px-3.5 py-2 shadow-sm ${
                              msg.direction === 'outbound'
                                ? 'bg-[#2A658F] text-white rounded-2xl rounded-br-md'
                                : 'bg-white text-gray-800 rounded-2xl rounded-bl-md'
                            }`}>
                              {msg.type === 'image' && msg.content.startsWith('media:') ? (
                                <img
                                  src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api'}/media/${msg.content.split('|')[0].replace('media:', '')}?channel_id=${activeChannel?.id || 1}`}
                                  alt={msg.content.split('|')[2] || 'Imagem'}
                                  className="max-w-[250px] rounded-lg cursor-pointer hover:opacity-90 transition-opacity"
                                  onClick={() => window.open(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api'}/media/${msg.content.split('|')[0].replace('media:', '')}?channel_id=${activeChannel?.id || 1}`, '_blank')}
                                />
                              ) : msg.type === 'audio' && msg.content.startsWith('media:') ? (
                                <audio controls className="max-w-[250px]">
                                  <source src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api'}/media/${msg.content.split('|')[0].replace('media:', '')}?channel_id=${activeChannel?.id || 1}`} type={msg.content.split('|')[1] || 'audio/ogg'} />
                                </audio>
                              ) : msg.type === 'video' && msg.content.startsWith('media:') ? (
                                <video controls className="max-w-[250px] rounded-lg">
                                  <source src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api'}/media/${msg.content.split('|')[0].replace('media:', '')}?channel_id=${activeChannel?.id || 1}`} type={msg.content.split('|')[1] || 'video/mp4'} />
                                </video>
                              ) : msg.type === 'sticker' && msg.content.startsWith('media:') ? (
                                <img
                                  src={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api'}/media/${msg.content.split('|')[0].replace('media:', '')}?channel_id=${activeChannel?.id || 1}`}
                                  alt="Sticker"
                                  className="w-32 h-32"
                                />
                              ) : msg.type === 'document' && msg.content.startsWith('media:') ? (
                                <a
                                  href={`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api'}/media/${msg.content.split('|')[0].replace('media:', '')}?channel_id=${activeChannel?.id || 1}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className={`flex items-center gap-2 ${msg.direction === 'outbound' ? 'text-white/90' : 'text-[#2A658F]'} underline text-sm`}
                                >
                                  📄 {msg.content.split('|')[2] || 'Documento'}
                                </a>
                              ) : (
                                <p className="text-[13.5px] whitespace-pre-wrap break-words leading-relaxed">{msg.content}</p>
                              )}

                              <div className={`flex items-center justify-end gap-1 mt-0.5 ${msg.direction === 'outbound' ? 'text-white/50' : 'text-gray-400'}`}>
                                {msg.sent_by_ai && <span className="text-[10px] font-medium">🤖 Nat</span>}
                                <span className="text-[10px] tabular-nums">{formatTime(msg.timestamp)}</span>
                                {msg.direction === 'outbound' && getStatusIcon(msg.status)}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    ))}
                    <div ref={messagesEndRef} />
                    </>
                    )}
                  </div>

                  {/* Input */}
                  <div className="px-4 py-3 border-t border-gray-100 bg-white relative">
                    {/* Feedback de envio */}
                    {sendFeedback && (
                      <div className={`absolute -top-10 left-1/2 -translate-x-1/2 px-4 py-1.5 rounded-lg text-xs font-medium shadow-lg transition-all ${
                        sendFeedback === 'ok'
                          ? 'bg-emerald-500 text-white'
                          : 'bg-red-500 text-white'
                      }`}>
                        {sendFeedback === 'ok' ? '✓ Mensagem enviada' : '✕ Erro ao enviar'}
                      </div>
                    )}

                    {isRecording ? (
                      /* Modo gravação */
                      <div className="flex items-center gap-3">
                        <button
                          onClick={cancelRecording}
                          className="p-2 rounded-full hover:bg-red-50 text-red-500 transition-all"
                          title="Cancelar"
                        >
                          <Trash2 className="w-5 h-5" />
                        </button>
                        <div className="flex-1 flex items-center gap-3 px-4 py-2.5 bg-red-50 rounded-xl">
                          <div className="w-2.5 h-2.5 bg-red-500 rounded-full animate-pulse" />
                          <span className="text-sm font-medium text-red-600 tabular-nums">{formatRecordingTime(recordingTime)}</span>
                          <span className="text-xs text-red-400">Gravando...</span>
                        </div>
                        <button
                          onClick={stopRecording}
                          className="flex items-center justify-center w-10 h-10 bg-[#2A658F] rounded-xl text-white hover:bg-[#1f5375] active:scale-95 transition-all"
                          title="Enviar áudio"
                        >
                          <Send className="w-4 h-4" />
                        </button>
                      </div>
                    ) : (
                      /* Modo normal */
                      <div className="flex items-end gap-2">
                        {/* Botão anexar */}
                        <div className="relative" ref={attachMenuRef}>
                          <button
                            onClick={() => setShowAttachMenu(!showAttachMenu)}
                            className={`p-2.5 rounded-xl transition-all ${showAttachMenu ? 'text-[#2A658F] bg-[#2A658F]/10 rotate-45' : 'text-gray-400 hover:text-gray-600 hover:bg-gray-50'}`}
                            title="Anexar"
                          >
                            <Paperclip className="w-5 h-5 transition-transform" />
                          </button>
                          {showAttachMenu && (
                            <div className="absolute bottom-12 left-0 z-50 bg-white rounded-xl border border-gray-200 shadow-xl overflow-hidden min-w-[180px]">
                              <button
                                onClick={() => { imageInputRef.current?.click(); setShowAttachMenu(false); }}
                                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left"
                              >
                                <div className="w-8 h-8 bg-purple-100 rounded-full flex items-center justify-center">
                                  <ImageIcon className="w-4 h-4 text-purple-600" />
                                </div>
                                <span className="text-[13px] text-gray-700">Fotos e vídeos</span>
                              </button>
                              <button
                                onClick={() => { fileInputRef.current?.click(); setShowAttachMenu(false); }}
                                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left"
                              >
                                <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                                  <FileText className="w-4 h-4 text-blue-600" />
                                </div>
                                <span className="text-[13px] text-gray-700">Documento</span>
                              </button>
                              <button
                                onClick={() => { audioInputRef.current?.click(); setShowAttachMenu(false); }}
                                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left"
                              >
                                <div className="w-8 h-8 bg-green-100 rounded-full flex items-center justify-center">
                                  <Mic className="w-4 h-4 text-green-600" />
                                </div>
                                <span className="text-[13px] text-gray-700">Áudio</span>
                              </button>
                            </div>
                          )}
                          <input
                            ref={imageInputRef}
                            type="file"
                            accept="image/*,video/*"
                            className="hidden"
                            onChange={(e) => {
                              const file = e.target.files?.[0];
                              if (file) handleFileUpload(file, file.type.startsWith('video/') ? 'image' : 'image');
                              e.target.value = '';
                            }}
                          />
                          <input
                            ref={fileInputRef}
                            type="file"
                            accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.csv,.zip,.rar"
                            className="hidden"
                            onChange={(e) => {
                              const file = e.target.files?.[0];
                              if (file) handleFileUpload(file, 'document');
                              e.target.value = '';
                            }}
                          />
                          <input
                            ref={audioInputRef}
                            type="file"
                            accept=".mp3,.ogg,.opus,.m4a,.wav,audio/*"
                            className="hidden"
                            onChange={(e) => {
                              const file = e.target.files?.[0];
                              if (file) handleFileUpload(file, 'audio');
                              e.target.value = '';
                            }}
                          />
                        </div>

                        {/* Input de texto */}
                        <textarea
                          value={newMessage}
                          onChange={(e) => setNewMessage(e.target.value)}
                          onKeyDown={handleKeyPress}
                          placeholder="Digite uma mensagem..."
                          rows={1}
                          className="flex-1 px-4 py-2.5 bg-gray-50 border border-gray-100 rounded-xl text-sm text-gray-800 placeholder:text-gray-400 resize-none focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 focus:bg-white transition-all outline-none"
                        />

                        {/* Enviar ou Mic */}
                        {newMessage.trim() ? (
                          <button
                            onClick={handleSend}
                            disabled={sending}
                            className="flex items-center justify-center w-10 h-10 bg-[#2A658F] rounded-xl text-white hover:bg-[#1f5375] active:scale-95 transition-all disabled:opacity-40 disabled:active:scale-100 flex-shrink-0"
                          >
                            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                          </button>
                        ) : (
                          <button
                            onClick={startRecording}
                            className="flex items-center justify-center w-10 h-10 rounded-xl text-gray-400 hover:text-[#2A658F] hover:bg-[#2A658F]/10 transition-all flex-shrink-0"
                            title="Gravar áudio"
                          >
                            <Mic className="w-5 h-5" />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* CRM PANEL */}
                {showCRM && (
                  <div className="w-[300px] border-l border-gray-100 bg-white overflow-y-auto flex-shrink-0 hidden xl:block">
                    <div className="p-5 space-y-6">

                      {/* Perfil */}
                      <div className="text-center pb-5 border-b border-gray-100">
                        <div className={`w-16 h-16 rounded-2xl bg-gradient-to-br ${getAvatarColor(selectedContact.name)} flex items-center justify-center text-white font-bold text-xl shadow-md mx-auto`}>
                          {getInitials(selectedContact.name || selectedContact.wa_id)}
                        </div>
                        <p className="font-semibold text-[#27273D] mt-3 text-[15px]">{selectedContact.name || selectedContact.wa_id}</p>
                        <div className="flex items-center justify-center gap-1.5 mt-1.5 text-gray-400">
                          <Phone className="w-3.5 h-3.5" />
                          <span className="text-[12px]">+{selectedContact.wa_id}</span>
                        </div>
                        {selectedContact.created_at && (
                          <div className="flex items-center justify-center gap-1.5 mt-1 text-gray-400">
                            <Calendar className="w-3.5 h-3.5" />
                            <span className="text-[11px]">Desde {formatFullDate(selectedContact.created_at)}</span>
                          </div>
                        )}
                      </div>

                      {/* Toggle IA */}
                      <div className="pb-4 border-b border-gray-100">
                        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Agente IA (Nat)</p>
                        <button
                          onClick={toggleAI}
                          disabled={togglingAI}
                          className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl border transition-all ${
                            selectedContact.ai_active ? "border-emerald-200 bg-emerald-50" : "border-gray-200 bg-gray-50"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <span className="text-[16px]">{selectedContact.ai_active ? "🤖" : "👤"}</span>
                            <span className={`text-[13px] font-medium ${
                              selectedContact.ai_active ? "text-emerald-700" : "text-gray-500"
                            }`}>
                              {selectedContact.ai_active ? "IA Ativa" : "IA Desligada"}
                            </span>
                          </div>
                          <div className={`w-10 h-5 rounded-full transition-all ${selectedContact.ai_active ? "bg-emerald-500" : "bg-gray-300"} relative`}>
                            <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${selectedContact.ai_active ? "left-5" : "left-0.5"}`} />
                          </div>
                        </button>
                      </div>

                      {/* Status do Lead */}
                      <div>
                        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Status do Lead</p>
                        <div className="relative">
                          <button
                            onClick={() => setShowStatusMenu(!showStatusMenu)}
                            className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl border ${getStatusConfig(selectedContact.lead_status).border} ${getStatusConfig(selectedContact.lead_status).bg} transition-all hover:shadow-sm`}
                          >
                            <div className="flex items-center gap-2">
                              <div className={`w-2.5 h-2.5 rounded-full ${getStatusConfig(selectedContact.lead_status).color}`} />
                              <span className={`text-[13px] font-medium ${getStatusConfig(selectedContact.lead_status).text}`}>
                                {getStatusConfig(selectedContact.lead_status).label}
                              </span>
                            </div>
                            <ChevronDown className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${showStatusMenu ? 'rotate-180' : ''}`} />
                          </button>

                          {showStatusMenu && (
                            <div className="absolute top-full left-0 right-0 mt-1.5 bg-white rounded-xl border border-gray-200 shadow-lg z-10 overflow-hidden">
                              {leadStatuses.map(s => (
                                <button
                                  key={s.value}
                                  onClick={() => updateLeadStatus(s.value)}
                                  className="w-full flex items-center gap-2.5 px-3 py-2.5 hover:bg-gray-50 transition-colors text-left"
                                >
                                  <div className={`w-2.5 h-2.5 rounded-full ${s.color}`} />
                                  <span className="text-[13px] text-gray-700">{s.label}</span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Tags */}
                      <div>
                        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">Tags</p>
                        <div className="flex flex-wrap gap-1.5 mb-2">
                          {selectedContact.tags.map(tag => {
                            const tc = getTagColorConfig(tag.color);
                            return (
                              <span key={tag.id} className={`inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-medium rounded-lg ${tc.bg} ${tc.text}`}>
                                {tag.name}
                                <button onClick={() => removeTag(tag.id)} className="hover:opacity-60 transition-opacity">
                                  <X className="w-3 h-3" />
                                </button>
                              </span>
                            );
                          })}
                        </div>

                        <button onClick={() => setShowTagMenu(!showTagMenu)} className="flex items-center gap-1 text-[12px] text-[#2A658F] hover:text-[#1a4a6e] font-medium transition-colors">
                          <Plus className="w-3.5 h-3.5" /> Adicionar tag
                        </button>

                        {showTagMenu && (
                          <div className="mt-2 bg-gray-50 rounded-xl p-3 space-y-2 border border-gray-100">
                            {allTags.filter(t => !selectedContact.tags.find(ct => ct.id === t.id)).map(tag => {
                              const tc = getTagColorConfig(tag.color);
                              return (
                                <button
                                  key={tag.id}
                                  onClick={() => { addTag(tag.id); setShowTagMenu(false); }}
                                  className={`w-full text-left px-2.5 py-1.5 rounded-lg text-[11px] font-medium ${tc.bg} ${tc.text} hover:opacity-80 transition-opacity`}
                                >
                                  {tag.name}
                                </button>
                              );
                            })}

                            <div className="pt-2 border-t border-gray-200">
                              <p className="text-[10px] text-gray-400 uppercase font-semibold mb-1.5 tracking-wider">Criar nova tag</p>
                              <input
                                value={newTagName}
                                onChange={(e) => setNewTagName(e.target.value)}
                                placeholder="Nome da tag"
                                className="w-full px-2.5 py-1.5 text-[12px] text-gray-800 bg-white border border-gray-200 rounded-lg outline-none focus:border-[#2A658F] transition-colors"
                              />
                              <div className="flex gap-1.5 mt-2">
                                {tagColors.map(c => (
                                  <button
                                    key={c.value}
                                    onClick={() => setNewTagColor(c.value)}
                                    className={`w-5 h-5 rounded-full ${c.bg} transition-all ${newTagColor === c.value ? 'ring-2 ring-offset-1 ring-[#2A658F] scale-110' : 'hover:scale-105'}`}
                                  />
                                ))}
                              </div>
                              <button
                                onClick={() => { createTag(); setShowTagMenu(false); }}
                                disabled={!newTagName.trim()}
                                className="w-full mt-2.5 px-2.5 py-1.5 bg-[#2A658F] text-white text-[11px] font-medium rounded-lg disabled:opacity-40 hover:bg-[#1f5375] transition-colors"
                              >
                                Criar tag
                              </button>
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Notes */}
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Notas</p>
                          {!editingNotes && (
                            <button onClick={() => setEditingNotes(true)} className="text-[12px] text-[#2A658F] font-medium hover:text-[#1a4a6e] transition-colors">
                              Editar
                            </button>
                          )}
                        </div>

                        {editingNotes ? (
                          <div>
                            <textarea
                              value={notesValue}
                              onChange={(e) => setNotesValue(e.target.value)}
                              rows={4}
                              className="w-full px-3 py-2.5 text-[13px] text-gray-800 bg-gray-50 border border-gray-200 rounded-xl outline-none focus:border-[#2A658F] focus:bg-white resize-none transition-all"
                              placeholder="Adicione notas sobre este lead..."
                            />
                            <div className="flex gap-2 mt-2">
                              <button onClick={saveNotes} className="px-3.5 py-1.5 bg-[#2A658F] text-white text-[11px] font-medium rounded-lg hover:bg-[#1f5375] transition-colors">
                                Salvar
                              </button>
                              <button onClick={() => { setEditingNotes(false); setNotesValue(selectedContact.notes || ''); }} className="px-3.5 py-1.5 text-gray-500 text-[11px] font-medium rounded-lg hover:bg-gray-100 transition-colors">
                                Cancelar
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="bg-gray-50 rounded-xl p-3 min-h-[60px] border border-gray-100">
                            <p className="text-[13px] text-gray-500 whitespace-pre-wrap leading-relaxed">{selectedContact.notes || 'Sem notas'}</p>
                          </div>
                        )}
                      </div>

                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center bg-[#eef0f3]">
              <div className="w-20 h-20 bg-white rounded-2xl flex items-center justify-center mb-5 shadow-sm border border-gray-100">
                <MessageCircle className="w-9 h-9 text-gray-300" />
              </div>
              <p className="text-lg font-semibold text-[#27273D]">Cenat Hub</p>
              <p className="text-sm mt-1 text-gray-400">Selecione uma conversa para começar</p>
            </div>
          )}
        </div>

        {/* MODAL NOVA CONVERSA */}
        {showNewChat && (
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={() => setShowNewChat(false)}>
            <div className="bg-white rounded-2xl p-6 w-full max-w-lg shadow-2xl mx-4 max-h-[90vh] overflow-y-auto border border-gray-100" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-5">
                <h2 className="text-lg font-semibold text-[#27273D]">Nova Conversa</h2>
                <button onClick={() => { setShowNewChat(false); setSelectedTemplate(null); setTemplateParams([]); }} className="p-1.5 hover:bg-gray-100 rounded-xl transition-colors">
                  <X className="w-5 h-5 text-gray-400" />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-[13px] font-medium text-gray-500 mb-1.5">Telefone do lead</label>
                  <input
                    type="text"
                    value={newChatPhone}
                    onChange={e => setNewChatPhone(e.target.value)}
                    placeholder="5583988001234"
                    className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 placeholder:text-gray-400 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 focus:bg-white outline-none transition-all"
                  />
                  <p className="text-[11px] text-gray-400 mt-1">DDD + número com 9 (sem espaços)</p>
                </div>

                <div>
                  <label className="block text-[13px] font-medium text-gray-500 mb-1.5">Nome do lead</label>
                  <input
                    type="text"
                    value={newChatName}
                    onChange={e => setNewChatName(e.target.value)}
                    placeholder="Maria Silva"
                    className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 placeholder:text-gray-400 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 focus:bg-white outline-none transition-all"
                  />
                </div>

                {/* Seletor de Template */}
                <div>
                  <label className="block text-[13px] font-medium text-gray-500 mb-1.5">Template da mensagem</label>
                  {loadingTemplates ? (
                    <div className="flex items-center justify-center py-4">
                      <Loader2 className="w-5 h-5 text-[#2A658F] animate-spin" />
                    </div>
                  ) : templates.length === 0 ? (
                    <button
                      onClick={loadTemplates}
                      className="w-full py-2.5 border border-dashed border-gray-300 rounded-xl text-sm text-gray-400 hover:border-[#2A658F] hover:text-[#2A658F] transition-colors"
                    >
                      Carregar templates disponíveis
                    </button>
                  ) : (
                    <div className="space-y-2">
                      {templates.map((t: any) => (
                        <button
                          key={t.name}
                          onClick={() => selectTemplate(t)}
                          className={`w-full text-left px-3.5 py-2.5 rounded-xl border text-sm transition-all ${
                            selectedTemplate?.name === t.name
                              ? 'border-[#2A658F] bg-[#2A658F]/5 text-[#2A658F]'
                              : 'border-gray-100 text-gray-700 hover:border-gray-200 hover:bg-gray-50'
                          }`}
                        >
                          <p className="font-medium text-[13px]">{t.name.replace(/_/g, ' ')}</p>
                          <p className="text-[11px] text-gray-400 mt-0.5">{t.language} • {t.parameters.length} variáveis</p>
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Parâmetros do template */}
                {selectedTemplate && selectedTemplate.parameters.length > 0 && (
                  <div className="space-y-3 pt-1">
                    <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Preencher variáveis</p>
                    {selectedTemplate.parameters.map((p: string, i: number) => (
                      <div key={i}>
                        <label className="block text-[11px] text-gray-500 mb-1">{p} ({'{{'}{i + 1}{'}}'})</label>
                        <input
                          type="text"
                          value={templateParams[i] || ''}
                          onChange={e => updateParam(i, e.target.value)}
                          placeholder={`Valor para ${p}`}
                          className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:border-[#2A658F] focus:bg-white outline-none transition-all"
                        />
                      </div>
                    ))}
                  </div>
                )}

                {/* Preview */}
                {selectedTemplate && (
                  <div className="bg-[#eef0f3] rounded-xl p-4">
                    <p className="text-[10px] font-semibold text-gray-400 uppercase mb-2 tracking-wider">Prévia da mensagem</p>
                    <div className="bg-white rounded-xl px-3.5 py-2.5 shadow-sm border border-gray-100">
                      <p className="text-[13px] text-gray-800 whitespace-pre-wrap leading-relaxed">{getPreview()}</p>
                    </div>
                  </div>
                )}
              </div>

              <button
                onClick={handleNewChat}
                disabled={sendingTemplate || !newChatPhone.trim() || !newChatName.trim() || !selectedTemplate}
                className="w-full mt-6 py-3 bg-[#2A658F] text-white font-medium rounded-xl hover:bg-[#1f5375] hover:shadow-lg hover:shadow-[#2A658F]/20 active:scale-[0.98] transition-all disabled:opacity-40 disabled:active:scale-100 flex items-center justify-center gap-2"
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

      </div>
    </AppLayout>
  );
}