import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Building2,
  Bot,
  Plus,
  ArrowUpRight,
  Clock,
  Sparkles,
  CheckCircle2,
  Radio,
} from 'lucide-react';
import { dashboardService } from '../services/dashboard';
import { DashboardSummary } from '../types';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { StatusBadge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';

export const OverviewPage: React.FC = () => {
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSummary = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const summary = await dashboardService.getSummary();
      setData(summary);
    } catch (err: any) {
      setError(err.message || 'Failed to load dashboard metrics');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSummary();
  }, []);

  if (isLoading) {
    return <LoadingState message="Loading platform overview..." />;
  }

  if (error) {
    return <ErrorState message={error} onRetry={fetchSummary} />;
  }

  const summary = data || {
    total_clients: 0,
    active_clients: 0,
    total_agents: 0,
    active_agents: 0,
    recent_clients: [],
    recent_agents: [],
  };

  return (
    <div className="space-y-8 max-w-7xl mx-auto">
      {/* Top Banner / Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-[#102d38]">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100 flex items-center gap-2">
            Operations Console
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Real-time management of clients and autonomous voice employees
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<Building2 className="h-3.5 w-3.5" />}
            onClick={() => navigate('/clients?action=create')}
          >
            Create Client
          </Button>
          <Button
            variant="primary"
            size="sm"
            leftIcon={<Bot className="h-3.5 w-3.5" />}
            onClick={() => navigate('/agents?action=create')}
          >
            Create AI Employee
          </Button>
        </div>
      </div>

      {/* Real Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Clients */}
        <Card className="relative overflow-hidden border-l-4 border-l-[#00df8f]">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-medium uppercase tracking-wider text-[11px]">Total Clients</span>
            <Building2 className="h-4 w-4 text-[#00df8f]" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-100">
            {summary.total_clients}
          </div>
          <div className="mt-2 text-[11px] text-slate-500 flex items-center gap-1.5">
            <span>Registered enterprise client accounts</span>
          </div>
        </Card>

        {/* Active Clients */}
        <Card className="relative overflow-hidden border-l-4 border-l-[#00df8f]">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-medium uppercase tracking-wider text-[11px]">Active Clients</span>
            <CheckCircle2 className="h-4 w-4 text-[#00df8f]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#00df8f]">
            {summary.active_clients}
          </div>
          <div className="mt-2 text-[11px] text-slate-500">
            <span>Clients currently active on platform</span>
          </div>
        </Card>

        {/* Total AI Employees */}
        <Card className="relative overflow-hidden border-l-4 border-l-[#22d3ee]">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-medium uppercase tracking-wider text-[11px]">Total AI Employees</span>
            <Bot className="h-4 w-4 text-[#22d3ee]" />
          </div>
          <div className="text-2xl font-bold font-mono text-slate-100">
            {summary.total_agents}
          </div>
          <div className="mt-2 text-[11px] text-slate-500">
            <span>Configured voice agents across all clients</span>
          </div>
        </Card>

        {/* Active AI Employees */}
        <Card className="relative overflow-hidden border-l-4 border-l-[#00df8f]">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
            <span className="font-medium uppercase tracking-wider text-[11px]">Active AI Employees</span>
            <Radio className="h-4 w-4 text-[#00df8f]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#00df8f]">
            {summary.active_agents}
          </div>
          <div className="mt-2 text-[11px] text-slate-500">
            <span>Ready or Deployed voice employees</span>
          </div>
        </Card>
      </div>

      {/* Two-Column Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Clients */}
        <Card
          title="Recent Clients"
          subtitle="Latest client businesses registered in the system"
          action={
            <Link
              to="/clients"
              className="text-xs text-[#00df8f] hover:text-[#00f59b] font-medium inline-flex items-center gap-1"
            >
              View all <ArrowUpRight className="h-3 w-3" />
            </Link>
          }
          noPadding
        >
          {summary.recent_clients.length === 0 ? (
            <div className="p-8">
              <EmptyState
                icon={<Building2 className="h-5 w-5" />}
                title="No clients yet."
                description="Create your first client account to begin deploying AI voice employees."
                action={
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => navigate('/clients?action=create')}
                  >
                    Create Client
                  </Button>
                }
              />
            </div>
          ) : (
            <div className="divide-y divide-[#102d38]">
              {summary.recent_clients.map((client) => (
                <div
                  key={client.id}
                  onClick={() => navigate(`/clients/${client.id}`)}
                  className="flex items-center justify-between p-4 hover:bg-[#0c242e] cursor-pointer transition-colors"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-slate-200">
                        {client.name}
                      </span>
                      <StatusBadge status={client.status} />
                    </div>
                    <div className="text-[11px] text-slate-400">
                      Type: <span className="font-medium text-slate-300">{client.business_type}</span> &bull; {client.agent_count} {client.agent_count === 1 ? 'employee' : 'employees'}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] text-slate-500 font-mono">
                      {new Date(client.created_at).toLocaleDateString()}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Recent AI Employees */}
        <Card
          title="Recent AI Employees"
          subtitle="Latest configured voice agents"
          action={
            <Link
              to="/agents"
              className="text-xs text-[#00df8f] hover:text-[#00f59b] font-medium inline-flex items-center gap-1"
            >
              View all <ArrowUpRight className="h-3 w-3" />
            </Link>
          }
          noPadding
        >
          {summary.recent_agents.length === 0 ? (
            <div className="p-8">
              <EmptyState
                icon={<Bot className="h-5 w-5" />}
                title="No AI employees yet."
                description="Assign an AI employee with customized role and voice specifications to a client."
                action={
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => navigate('/agents?action=create')}
                  >
                    Create AI Employee
                  </Button>
                }
              />
            </div>
          ) : (
            <div className="divide-y divide-[#102d38]">
              {summary.recent_agents.map((agent) => (
                <div
                  key={agent.id}
                  onClick={() => navigate(`/agents/${agent.id}`)}
                  className="flex items-center justify-between p-4 hover:bg-[#0c242e] cursor-pointer transition-colors"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-slate-200">
                        {agent.name}
                      </span>
                      <StatusBadge status={agent.status} />
                    </div>
                    <div className="text-[11px] text-slate-400">
                      <span className="text-[#00df8f]">{agent.role}</span> &bull; {agent.client_name || 'Client'}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] font-mono text-slate-500">
                      {agent.id}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};
