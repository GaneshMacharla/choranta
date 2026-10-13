import React, { useEffect, useState } from 'react';
import { NavLink, Navigate, Outlet } from 'react-router-dom';
import { LayoutDashboard, PhoneCall, Megaphone, KeyRound, Phone, Wallet, Building, LogOut, Layers, Zap, Bot } from 'lucide-react';
import { portalAgentRequestsService } from '../../services/agentRequests';
import { NotificationBell } from './NotificationBell';
import { useAuth } from '../../context/AuthContext';
import { LoadingState } from '../common/LoadingState';

const NAV = [
  { to: '/portal', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/portal/plans', label: 'Plans', icon: Layers, end: false },
  { to: '/portal/employees', label: 'AI Employees', icon: Bot, end: false },
  { to: '/portal/calls', label: 'Calls', icon: PhoneCall, end: false },
  { to: '/portal/campaigns', label: 'Campaigns', icon: Megaphone, end: false },
  { to: '/portal/instant-outbound', label: 'Instant Outbound', icon: Zap, end: false },
  { to: '/portal/integrations', label: 'API & integrations', icon: KeyRound, end: false },
  { to: '/portal/numbers', label: 'Phone numbers', icon: Phone, end: false },
  { to: '/portal/billing', label: 'Billing', icon: Wallet, end: false },
  { to: '/portal/inventory', label: 'Properties', icon: Building, end: false },
];

/** Shell for client accounts: only their own calls, billing and inventory. */
export const PortalLayout: React.FC = () => {
  const { isAuthenticated, isLoading, user, logout } = useAuth();
  const [account, setAccount] = useState<{ client_name: string; client_code: string | null } | null>(null);

  useEffect(() => {
    if (isAuthenticated && user?.role === 'CLIENT') portalAgentRequestsService.me().then(setAccount).catch(() => setAccount(null));
  }, [isAuthenticated, user?.role]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#040d12]">
        <LoadingState message="Loading your portal..." />
      </div>
    );
  }
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (user?.role !== 'CLIENT') return <Navigate to="/" replace />;

  return (
    <div className="flex min-h-screen flex-col bg-[#040d12] text-slate-100 md:flex-row">
      <aside className="flex shrink-0 flex-row items-center gap-1 border-b border-[#102d38] bg-[#071419] px-3 py-2 md:w-56 md:flex-col md:items-stretch md:border-b-0 md:border-r md:px-3 md:py-5">
        <div className="mr-3 flex items-center gap-2 md:mb-6 md:mr-0 md:px-2">
          <img src="/logo.png" alt="Choranta" className="h-8 w-8 shrink-0 object-contain" />
          <div className="hidden md:block">
            <p className="text-sm font-semibold">Choranta</p>
            <p className="text-[11px] text-slate-500">Client Portal</p>
          </div>
          <div className="md:ml-auto">
            <NotificationBell />
          </div>
        </div>
        <nav className="flex flex-1 gap-1 overflow-x-auto md:flex-col">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-xs font-medium ${
                  isActive ? 'bg-[#00df8f]/10 text-[#00df8f]' : 'text-slate-400 hover:bg-[#0c2129] hover:text-slate-200'
                }`
              }
            >
              <Icon className="h-4 w-4" /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden border-t border-[#102d38] pt-3 md:block md:px-2">
          {account && (
            <div className="mb-2">
              <p className="truncate text-xs font-semibold text-slate-200">{account.client_name}</p>
              {account.client_code && (
                <p className="text-[11px] text-slate-500">
                  Client ID <span className="font-mono text-[#00df8f]">{account.client_code}</span>
                </p>
              )}
            </div>
          )}
          <p className="truncate text-xs text-slate-300">{user.name}</p>
          <p className="truncate text-[11px] text-slate-500">{user.email}</p>
        </div>
        <button onClick={logout} className="ml-2 flex items-center gap-1.5 rounded-md px-3 py-2 text-xs text-slate-400 hover:text-slate-200 md:ml-0 md:mt-2">
          <LogOut className="h-4 w-4" /> <span className="hidden md:inline">Sign out</span>
        </button>
      </aside>
      <main className="flex-1 overflow-y-auto p-4 md:p-8">
        <Outlet />
      </main>
    </div>
  );
};
