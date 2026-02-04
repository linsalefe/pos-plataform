'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/auth-context';
import { Eye, EyeOff, Loader2 } from 'lucide-react';

export default function LoginPage() {
  const { user, loading: authLoading, login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);
  useEffect(() => { if (!authLoading && user) router.push('/dashboard'); }, [user, authLoading, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      router.push('/dashboard');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao fazer login');
    } finally {
      setLoading(false);
    }
  };

  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#f8f9fb]">
        <Loader2 className="w-8 h-8 text-[#2A658F] animate-spin" />
      </div>
    );
  }

  if (user) return null;

  return (
    <div className="min-h-screen flex bg-[#0f1b2d]">
      {/* Lado esquerdo - Branding */}
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-center px-16 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-[#2A658F]/20 to-transparent" />
        <div className="absolute top-1/4 -left-20 w-96 h-96 bg-[#2A658F]/10 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-10 w-72 h-72 bg-[#4d9fd4]/10 rounded-full blur-3xl" />
        
        <div className={`relative z-10 transition-all duration-1000 ease-out ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}>
          <div className="flex items-center gap-3 mb-8">
            <img src="/[LOGO] Ícone - Branco.png" alt="Cenat" className="w-14 h-14 object-contain" />
            <span className="text-3xl font-bold text-white tracking-tight">Cenat</span>
          </div>
          <h1 className="text-5xl font-bold text-white leading-tight mb-2">
            Cenat Hub
          </h1>
          <p className="text-xl text-[#4d9fd4] font-medium mb-4">Central de Atendimento Integrado</p>
          <p className="text-lg text-gray-400 max-w-md leading-relaxed">
            Gerencie seus leads, acompanhe conversas e converta mais clientes com nossa plataforma de multiatendimento via WhatsApp Business API.
          </p>
          
          <div className="flex gap-8 mt-12">
            <div>
              <p className="text-3xl font-bold text-white">Multi</p>
              <p className="text-sm text-gray-500 mt-1">Números & Atendentes</p>
            </div>
            <div>
              <p className="text-3xl font-bold text-white">Real-time</p>
              <p className="text-sm text-gray-500 mt-1">Mensagens instantâneas</p>
            </div>
            <div>
              <p className="text-3xl font-bold text-white">CRM</p>
              <p className="text-sm text-gray-500 mt-1">Gestão de leads</p>
            </div>
          </div>
        </div>
      </div>

      {/* Lado direito - Form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center px-6">
        <div className={`w-full max-w-md transition-all duration-700 ease-out delay-300 ${mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}>
          {/* Logo mobile */}
          <div className="flex items-center gap-3 mb-8 lg:hidden">
            <img src="/[LOGO] Ícone - Branco.png" alt="Cenat" className="w-10 h-10 object-contain" />
            <span className="text-2xl font-bold text-white">Cenat Hub</span>
          </div>

          <div className="bg-white rounded-3xl p-8 shadow-2xl shadow-black/20">
            <div className="mb-6">
              <h2 className="text-2xl font-bold text-[#27273D]">Bem-vindo de volta</h2>
              <p className="text-gray-500 text-sm mt-1">Entre com suas credenciais para acessar o Hub</p>
            </div>

            {error && (
              <div className="mb-4 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-600 mb-1.5">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="seu@email.com"
                  required
                  className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 focus:border-[#2A658F] focus:ring-4 focus:ring-[#2A658F]/10 transition-all outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-600 mb-1.5">Senha</label>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                    className="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-800 focus:border-[#2A658F] focus:ring-4 focus:ring-[#2A658F]/10 transition-all outline-none pr-12"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 bg-gradient-to-r from-[#2A658F] to-[#3d7ba8] text-white font-medium rounded-xl hover:shadow-lg hover:shadow-[#2A658F]/30 hover:-translate-y-0.5 transition-all duration-200 disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-none flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Entrando...
                  </>
                ) : (
                  'Entrar'
                )}
              </button>
            </form>
          </div>

          <p className="text-center text-xs text-gray-600 mt-6">
            Cenat Hub © {new Date().getFullYear()} — Central de Atendimento Integrado
          </p>
        </div>
      </div>
    </div>
  );
}
