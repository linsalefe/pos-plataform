'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/auth-context';
import AppLayout from '@/components/AppLayout';
import api from '@/lib/api';
import { UserPlus, Shield, User, Mail, Loader2, Eye, EyeOff, X, AlertCircle, Lock, Users } from 'lucide-react';

interface UserInfo {
  id: number;
  name: string;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string | null;
}

export default function UsersPage() {
  const { user } = useAuth();
  const router = useRouter();
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newRole, setNewRole] = useState('atendente');
  const [showPassword, setShowPassword] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    if (user && user.role !== 'admin') router.push('/dashboard');
    if (user) loadUsers();
  }, [user]);

  const loadUsers = async () => {
    try {
      const res = await api.get('/auth/users');
      setUsers(res.data);
    } catch (err) {
      console.error('Erro:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!newName.trim() || !newEmail.trim() || !newPassword.trim()) return;
    setCreating(true);
    setError('');
    try {
      await api.post('/auth/register', {
        name: newName,
        email: newEmail,
        password: newPassword,
        role: newRole,
      });
      setShowModal(false);
      setNewName('');
      setNewEmail('');
      setNewPassword('');
      setNewRole('atendente');
      await loadUsers();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao criar usuário');
    } finally {
      setCreating(false);
    }
  };

  const toggleActive = async (u: UserInfo) => {
    try {
      await api.patch(`/auth/users/${u.id}`, { is_active: !u.is_active });
      await loadUsers();
    } catch (err) {
      console.error('Erro:', err);
    }
  };

  const getRoleLabel = (role: string) => role === 'admin' ? 'Administrador' : 'Atendente';
  const getRoleColor = (role: string) => role === 'admin' ? 'bg-purple-50 text-purple-700' : 'bg-blue-50 text-blue-700';
  const getInitials = (name: string) => name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
  const getAvatarColor = (name: string) => {
    const c = ['from-blue-500 to-blue-600','from-purple-500 to-purple-600','from-emerald-500 to-emerald-600','from-orange-500 to-orange-600','from-pink-500 to-pink-600'];
    return c[name.charCodeAt(0) % c.length];
  };

  const activeCount = users.filter(u => u.is_active).length;
  const adminCount = users.filter(u => u.role === 'admin').length;

  return (
    <AppLayout>
      <div className="space-y-6 max-w-4xl mx-auto h-full overflow-y-auto pb-6">

        {/* Header */}
        <div className={`flex items-center justify-between transition-all duration-700 ease-out ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-4'}`}>
          <div>
            <p className="text-sm text-gray-400 mb-0.5">Administração</p>
            <h1 className="text-2xl font-semibold text-[#27273D] tracking-tight">Usuários</h1>
          </div>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2 px-4 py-2.5 bg-[#2A658F] text-white text-[13px] font-medium rounded-xl hover:bg-[#1f5375] hover:shadow-lg hover:shadow-[#2A658F]/20 active:scale-[0.98] transition-all"
          >
            <UserPlus className="w-4 h-4" />
            Novo usuário
          </button>
        </div>

        {/* Stats resumo */}
        <div className={`grid grid-cols-3 gap-4 transition-all duration-700 ease-out delay-75 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          <div className="bg-white rounded-2xl p-4 border border-gray-100 flex items-center gap-3">
            <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center">
              <Users className="w-[18px] h-[18px] text-blue-600" />
            </div>
            <div>
              <p className="text-xl font-bold text-[#27273D] tabular-nums">{users.length}</p>
              <p className="text-[12px] text-gray-400">Total</p>
            </div>
          </div>
          <div className="bg-white rounded-2xl p-4 border border-gray-100 flex items-center gap-3">
            <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center">
              <User className="w-[18px] h-[18px] text-emerald-600" />
            </div>
            <div>
              <p className="text-xl font-bold text-[#27273D] tabular-nums">{activeCount}</p>
              <p className="text-[12px] text-gray-400">Ativos</p>
            </div>
          </div>
          <div className="bg-white rounded-2xl p-4 border border-gray-100 flex items-center gap-3">
            <div className="w-10 h-10 bg-purple-50 rounded-xl flex items-center justify-center">
              <Shield className="w-[18px] h-[18px] text-purple-600" />
            </div>
            <div>
              <p className="text-xl font-bold text-[#27273D] tabular-nums">{adminCount}</p>
              <p className="text-[12px] text-gray-400">Admins</p>
            </div>
          </div>
        </div>

        {/* Users List */}
        <div className={`bg-white rounded-2xl border border-gray-100 overflow-hidden transition-all duration-700 ease-out delay-150 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'}`}>
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-6 h-6 text-[#2A658F] animate-spin" />
            </div>
          ) : users.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-gray-400">
              <User className="w-10 h-10 mb-2 text-gray-300" />
              <p className="text-sm">Nenhum usuário cadastrado</p>
            </div>
          ) : (
            <div>
              {/* Table header */}
              <div className="hidden sm:grid grid-cols-[1fr_140px_100px_90px] px-6 py-3 border-b border-gray-100 bg-gray-50/50">
                <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Usuário</span>
                <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Função</span>
                <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">Status</span>
                <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider text-right">Ação</span>
              </div>

              {users.map((u) => (
                <div
                  key={u.id}
                  className="grid grid-cols-1 sm:grid-cols-[1fr_140px_100px_90px] items-center px-6 py-4 border-b border-gray-50 last:border-0 hover:bg-gray-50/50 transition-colors gap-3 sm:gap-0"
                >
                  {/* Info */}
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${getAvatarColor(u.name)} flex items-center justify-center text-white font-semibold text-xs shadow-sm flex-shrink-0 ${!u.is_active ? 'opacity-40' : ''}`}>
                      {getInitials(u.name)}
                    </div>
                    <div className="min-w-0">
                      <p className={`font-medium text-[13px] truncate ${u.is_active ? 'text-[#27273D]' : 'text-gray-400'}`}>
                        {u.name}
                        {u.id === user?.id && (
                          <span className="ml-1.5 text-[10px] text-gray-400 font-normal">(você)</span>
                        )}
                      </p>
                      <div className="flex items-center gap-1.5 mt-0.5">
                        <Mail className="w-3 h-3 text-gray-400 flex-shrink-0" />
                        <span className="text-[12px] text-gray-400 truncate">{u.email}</span>
                      </div>
                    </div>
                  </div>

                  {/* Role */}
                  <div>
                    <span className={`inline-flex items-center px-2 py-0.5 text-[11px] font-semibold rounded-md ${getRoleColor(u.role)}`}>
                      {getRoleLabel(u.role)}
                    </span>
                  </div>

                  {/* Status */}
                  <div>
                    <span className={`inline-flex items-center gap-1.5 text-[12px] font-medium ${u.is_active ? 'text-emerald-600' : 'text-gray-400'}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${u.is_active ? 'bg-emerald-500' : 'bg-gray-300'}`} />
                      {u.is_active ? 'Ativo' : 'Inativo'}
                    </span>
                  </div>

                  {/* Action */}
                  <div className="flex justify-end">
                    {u.id !== user?.id && (
                      <button
                        onClick={() => toggleActive(u)}
                        className={`px-3 py-1.5 text-[11px] font-medium rounded-lg transition-all ${
                          u.is_active
                            ? 'bg-red-50 text-red-600 hover:bg-red-100'
                            : 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100'
                        }`}
                      >
                        {u.is_active ? 'Desativar' : 'Ativar'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Modal */}
        {showModal && (
          <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50" onClick={() => setShowModal(false)}>
            <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-2xl mx-4 border border-gray-100" onClick={e => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-5">
                <h2 className="text-lg font-semibold text-[#27273D]">Novo Usuário</h2>
                <button onClick={() => setShowModal(false)} className="p-1.5 hover:bg-gray-100 rounded-xl transition-colors">
                  <X className="w-5 h-5 text-gray-400" />
                </button>
              </div>

              {error && (
                <div className="mb-5 flex items-center gap-2.5 px-4 py-3 bg-red-50 border border-red-100 rounded-xl">
                  <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
                  <span className="text-sm text-red-600">{error}</span>
                </div>
              )}

              <div className="space-y-4">
                <div>
                  <label className="block text-[13px] font-medium text-gray-500 mb-1.5">Nome</label>
                  <div className="relative">
                    <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                    <input
                      type="text"
                      value={newName}
                      onChange={e => setNewName(e.target.value)}
                      placeholder="Nome completo"
                      className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 placeholder:text-gray-400 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 focus:bg-white outline-none transition-all"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-[13px] font-medium text-gray-500 mb-1.5">Email</label>
                  <div className="relative">
                    <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                    <input
                      type="email"
                      value={newEmail}
                      onChange={e => setNewEmail(e.target.value)}
                      placeholder="email@exemplo.com"
                      className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 placeholder:text-gray-400 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 focus:bg-white outline-none transition-all"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-[13px] font-medium text-gray-500 mb-1.5">Senha</label>
                  <div className="relative">
                    <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                    <input
                      type={showPassword ? 'text' : 'password'}
                      value={newPassword}
                      onChange={e => setNewPassword(e.target.value)}
                      placeholder="Mínimo 6 caracteres"
                      className="w-full pl-10 pr-12 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 placeholder:text-gray-400 focus:border-[#2A658F] focus:ring-2 focus:ring-[#2A658F]/10 focus:bg-white outline-none transition-all"
                    />
                    <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors">
                      {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <div>
                  <label className="block text-[13px] font-medium text-gray-500 mb-1.5">Função</label>
                  <div className="flex gap-3">
                    <button
                      onClick={() => setNewRole('atendente')}
                      className={`flex-1 py-2.5 rounded-xl text-[13px] font-medium border transition-all ${
                        newRole === 'atendente' ? 'border-[#2A658F] bg-[#2A658F]/5 text-[#2A658F]' : 'border-gray-200 text-gray-400 hover:bg-gray-50'
                      }`}
                    >
                      Atendente
                    </button>
                    <button
                      onClick={() => setNewRole('admin')}
                      className={`flex-1 py-2.5 rounded-xl text-[13px] font-medium border transition-all ${
                        newRole === 'admin' ? 'border-purple-400 bg-purple-50 text-purple-700' : 'border-gray-200 text-gray-400 hover:bg-gray-50'
                      }`}
                    >
                      Administrador
                    </button>
                  </div>
                </div>
              </div>

              <button
                onClick={handleCreate}
                disabled={creating || !newName.trim() || !newEmail.trim() || !newPassword.trim()}
                className="w-full mt-6 py-3 bg-[#2A658F] text-white font-medium rounded-xl hover:bg-[#1f5375] hover:shadow-lg hover:shadow-[#2A658F]/20 active:scale-[0.98] transition-all disabled:opacity-40 disabled:active:scale-100 flex items-center justify-center gap-2"
              >
                {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
                {creating ? 'Criando...' : 'Criar usuário'}
              </button>
            </div>
          </div>
        )}
      </div>
    </AppLayout>
  );
}