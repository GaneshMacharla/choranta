import React, { useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Building2,
  Bot,
  Settings,
  PhoneCall,
  Megaphone,
  Wrench,
  Puzzle,
  Radio,
  Cpu,
  DollarSign,
  Layers,
  Terminal,
  LogOut,
  ShieldCheck,
  Zap,
  Inbox,
  BadgeCheck,
} from 'lucide-react';
import { verificationsApi } from '../../pages/VerificationsPage';
import { agentRequestsService } from '../../services/agentRequests';
import { useAuth } from '../../context/AuthContext';
import { Badge } from '../common/Badge';

interface NavItem {
  name: string;
  path: string;
  icon: React.ComponentType<{ className?: string }>;
  count?: number;
}

export const Sidebar: React.FC = () => {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [pendingRequests, setPendingRequests] = useState(0);
  const [pendingVerifications, setPendingVerifications] = useState(0);

  // New AI employee requests waiting to be built; refreshed as the admin moves between pages
  useEffect(() => {
    agentRequestsService
      .pendingCount()
      .then((r) => setPendingRequests(r.pending))
      .catch(() => setPendingRequests(0));
    verificationsApi
      .pendingCount()
      .then((r) => setPendingVerifications(r.pending))
      .catch(() => setPendingVerifications(0));
  }, [location.pathname]);

  const navItems: NavItem[] = [
    { name: 'Overview', path: '/overview', icon: LayoutDashboard },
    { name: 'Clients', path: '/clients', icon: Building2 },
    { name: 'AI Employees', path: '/agents', icon: Bot },
    { name: 'Employee Requests', path: '/agent-requests', icon: Inbox, count: pendingRequests },
    { name: 'Verifications', path: '/verifications', icon: BadgeCheck, count: pendingVerifications },
    
    { name: 'Calls', path: '/calls', icon: PhoneCall },
    { name: 'Campaigns', path: '/campaigns', icon: Megaphone },
    { name: 'Instant Outbound', path: '/instant-outbound', icon: Zap },
    { name: 'Telephony', path: '/telephony', icon: Radio },
    
    { name: 'Tools', path: '/tools', icon: Wrench },
    { name: 'Integrations', path: '/integrations', icon: Puzzle },
    { name: 'AI Providers', path: '/providers', icon: Cpu },
    { name: 'Number Pricing', path: '/plans', icon: Layers },
    { name: 'Usage & Costs', path: '/usage', icon: DollarSign },
    { name: 'Errors / Logs', path: '/logs', icon: Terminal },
    
    { name: 'Settings', path: '/settings', icon: Settings },
  ];

  return (
    <aside className="w-64 shrink-0 bg-[#051116] border-r border-[#102731] flex flex-col h-screen select-none">
      {/* Brand Header */}
      <div className="p-4 border-b border-[#102731] flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <img src="/logo.png" alt="Choranta" className="h-8 w-8 shrink-0 object-contain" />
          <div>
            <div className="font-semibold text-sm tracking-wide text-slate-100 flex items-center gap-1.5">
              CHORANTA
            </div>
            <div className="text-[10px] text-slate-400 tracking-wider uppercase font-medium">
              Internal Studio
            </div>
          </div>
        </div>
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#081e26] text-[#00df8f] border border-[#00df8f]/30 font-semibold">
          v0.1
        </span>
      </div>

      {/* Navigation List */}
      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-0.5">
        <div className="px-3 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
          Management
        </div>

        {navItems.map((item) => {
          const Icon = item.icon;

          return (
            <NavLink
              key={item.name}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) => `
                flex items-center justify-between px-3 py-2 rounded text-xs font-medium transition-colors
                ${isActive
                  ? 'bg-[#00df8f]/10 text-[#00df8f] border border-[#00df8f]/25 font-semibold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-[#091e26]'}
              `}
            >
              <div className="flex items-center gap-2.5">
                <Icon className="h-4 w-4" />
                <span>{item.name}</span>
              </div>
              {!!item.count && (
                <span className="rounded-full bg-amber-400 px-1.5 text-[10px] font-bold text-[#1a1200]">{item.count}</span>
              )}
            </NavLink>
          );
        })}
      </div>

      {/* Internal User Profile & Sign Out */}
      <div className="p-3 border-t border-[#102731] bg-[#040e13]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5 overflow-hidden">
            <div className="h-8 w-8 rounded-full bg-[#0c232c] border border-[#163e4c] flex items-center justify-center text-xs font-medium text-slate-300 shrink-0">
              {user?.name ? user.name.charAt(0).toUpperCase() : 'U'}
            </div>
            <div className="overflow-hidden">
              <div className="text-xs font-medium text-slate-200 truncate">
                {user?.name || 'Operator'}
              </div>
              <div className="flex items-center gap-1.5">
                <Badge variant={user?.role === 'ADMIN' ? 'green' : 'gray'} size="sm">
                  {user?.role || 'OPERATOR'}
                </Badge>
              </div>
            </div>
          </div>
          <button
            onClick={logout}
            title="Sign out of Choranta"
            className="p-1.5 rounded text-slate-500 hover:text-rose-400 hover:bg-[#152328] transition-colors"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
  );
};
