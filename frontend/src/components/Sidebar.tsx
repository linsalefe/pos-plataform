'use client';

import { usePathname, useRouter } from 'next/navigation';
import Link from 'next/link';
import Image from 'next/image';
import { LayoutDashboard, MessageCircle, ChevronLeft, ChevronRight, LogOut } from 'lucide-react';
import { useState } from 'react';
import { useAuth } from '@/contexts/auth-context';

const menuItems = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/conversations', label: 'Conversas', icon: MessageCircle },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);

  const handleLogout = () => {
    logout();
    router.push('/login');
  };

  return (
    <aside className={`${collapsed ? 'w-[72px]' : 'w-[240px]'} h-screen bg-[#0f1b2d] flex flex-col transition-all duration-300 ease-in-out flex-shrink-0`}>
      {/* Logo */}
      <div className="h-16 flex items-center px-4 border-b border-white/5">
        <div className={`flex items-center gap-2.5 ${collapsed ? 'justify-center w-full' : ''}`}>
          <Image src="/[LOGO] Ícone - Branco.png" alt="Cenat" width={36} height={36} className="object-contain flex-shrink-0" />
          {!collapsed && (
            <span className="text-white font-semibold text-lg tracking-[0.2em] uppercase">Cenat</span>
          )}
        </div>
      </div>

      {/* Menu */}
      <nav className="flex-1 py-4 px-3 space-y-1">
        {menuItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 group
                ${isActive
                  ? 'bg-[#2A658F] text-white shadow-lg shadow-[#2A658F]/25'
                  : 'text-gray-400 hover:text-white hover:bg-white/5'
                }
                ${collapsed ? 'justify-center' : ''}
              `}
              title={collapsed ? item.label : ''}
            >
              <Icon className={`w-5 h-5 flex-shrink-0 ${isActive ? 'text-white' : 'text-gray-500 group-hover:text-white'}`} />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* User + Logout */}
      <div className="px-3 pb-4 space-y-1">
        {user && !collapsed && (
          <div className="px-3 py-2 mb-1">
            <p className="text-sm font-medium text-white truncate">{user.name}</p>
            <p className="text-[11px] text-gray-500 truncate">{user.email}</p>
          </div>
        )}
        {user && collapsed && (
          <div className="flex justify-center mb-1">
            <div className="w-8 h-8 rounded-full bg-[#2A658F] flex items-center justify-center text-white text-xs font-semibold">
              {user.name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)}
            </div>
          </div>
        )}
        <button
          onClick={handleLogout}
          className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-xl text-gray-500 hover:text-red-400 hover:bg-white/5 transition-all duration-200 text-sm ${collapsed ? 'justify-center' : ''}`}
          title={collapsed ? 'Sair' : ''}
        >
          <LogOut className="w-4 h-4 flex-shrink-0" />
          {!collapsed && <span>Sair</span>}
        </button>
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={`w-full flex items-center gap-2 px-3 py-2.5 rounded-xl text-gray-500 hover:text-white hover:bg-white/5 transition-all duration-200 text-sm ${collapsed ? 'justify-center' : ''}`}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : (
            <>
              <ChevronLeft className="w-4 h-4" />
              <span>Recolher</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
