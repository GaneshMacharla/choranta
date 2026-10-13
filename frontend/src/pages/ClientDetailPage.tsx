import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  Building2,
  Bot,
  ArrowLeft,
  Mail,
  Phone,
  Clock,
  Calendar,
  Plus,
  Edit2,
  UserCheck,
} from 'lucide-react';
import { clientsService } from '../services/clients';
import { agentsService } from '../services/agents';
import { Client, Agent, AgentCreateInput, ClientUpdateInput, BusinessType } from '../types';
import { Card } from '../components/common/Card';
import { PropertyInventoryCard } from '../components/inventory/PropertyInventoryCard';
import { ClientBillingCard } from '../components/billing/ClientBillingCard';
import { ClientPlanCard } from '../components/billing/ClientPlanCard';
import { Button } from '../components/common/Button';
import { StatusBadge, Badge } from '../components/common/Badge';
import { Table, Column } from '../components/common/Table';
import { Modal } from '../components/common/Modal';
import { Input } from '../components/common/Input';
import { Select } from '../components/common/Select';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';

export const ClientDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [client, setClient] = useState<Client | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [billingVersion, setBillingVersion] = useState(0);

  // Edit Client Modal
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editForm, setEditForm] = useState<ClientUpdateInput>({});
  const [editError, setEditError] = useState<string | null>(null);
  const [isSubmittingEdit, setIsSubmittingEdit] = useState(false);

  // Create Agent Modal
  const [isCreateAgentOpen, setIsCreateAgentOpen] = useState(false);
  const [agentForm, setAgentForm] = useState<AgentCreateInput>({
    client_id: '',
    name: '',
    role: '',
    description: '',
  });
  const [agentError, setAgentError] = useState<string | null>(null);
  const [isSubmittingAgent, setIsSubmittingAgent] = useState(false);

  const fetchClientData = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const [clientData, agentsData] = await Promise.all([
        clientsService.get(id),
        agentsService.list({ client_id: id }),
      ]);
      setClient(clientData);
      setAgents(agentsData.items);
      setAgentForm((prev) => ({ ...prev, client_id: id }));
      setEditForm({
        name: clientData.name,
        business_type: clientData.business_type,
        description: clientData.description || '',
        contact_name: clientData.contact_name || '',
        contact_email: clientData.contact_email || '',
        contact_phone: clientData.contact_phone || '',
        timezone: clientData.timezone,
        status: clientData.status,
      });
    } catch (err: any) {
      setError(err.message || 'Failed to load client profile');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchClientData();
  }, [id]);

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id) return;
    setEditError(null);
    setIsSubmittingEdit(true);
    try {
      const updated = await clientsService.update(id, editForm);
      setClient(updated);
      setIsEditModalOpen(false);
    } catch (err: any) {
      setEditError(err.message || 'Failed to update client');
    } finally {
      setIsSubmittingEdit(false);
    }
  };

  const handleCreateAgentSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id) return;
    setAgentError(null);

    if (!agentForm.name.trim()) {
      setAgentError('Agent name is required.');
      return;
    }
    if (!agentForm.role.trim()) {
      setAgentError('Agent role is required.');
      return;
    }

    setIsSubmittingAgent(true);
    try {
      const created = await agentsService.create({
        ...agentForm,
        client_id: id,
      });
      setIsCreateAgentOpen(false);
      setAgentForm({ client_id: id, name: '', role: '', description: '' });
      navigate(`/agents/${created.id}`);
    } catch (err: any) {
      setAgentError(err.message || 'Failed to create AI employee');
    } finally {
      setIsSubmittingAgent(false);
    }
  };

  if (isLoading) {
    return <LoadingState message="Loading client details..." />;
  }

  if (error || !client) {
    return (
      <ErrorState
        message={error || 'Client not found.'}
        onRetry={fetchClientData}
      />
    );
  }

  const agentColumns: Column<Agent>[] = [
    {
      key: 'name',
      header: 'Employee Name',
      render: (a) => (
        <div>
          <div className="font-semibold text-slate-100 hover:text-[#00df8f] transition-colors">
            {a.name}
          </div>
          <div className="text-[11px] font-mono text-slate-500">{a.id}</div>
        </div>
      ),
    },
    {
      key: 'role',
      header: 'Role',
      render: (a) => (
        <span className="text-xs font-medium text-[#00df8f]">{a.role}</span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (a) => <StatusBadge status={a.status} />,
    },
    {
      key: 'created_at',
      header: 'Created',
      render: (a) => (
        <span className="text-xs text-slate-400 font-mono">
          {new Date(a.created_at).toLocaleDateString()}
        </span>
      ),
    },
    {
      key: 'actions',
      header: 'Actions',
      className: 'text-right',
      render: (a) => (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => navigate(`/agents/${a.id}`)}
        >
          View Details
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Back button */}
      <div>
        <Link
          to="/clients"
          className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to Clients
        </Link>
      </div>

      {/* Client Profile Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-[#102d38]">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-100">{client.name}</h1>
            {client.client_code && (
              <span className="rounded border border-[#00df8f]/30 bg-[#081e26] px-2 py-0.5 font-mono text-xs font-semibold text-[#00df8f]">
                {client.client_code}
              </span>
            )}
            <StatusBadge status={client.status} />
            <Badge variant="blue">{client.business_type}</Badge>
          </div>
          <div className="text-xs text-slate-400 font-mono flex items-center gap-2">
            <span>ID: {client.id}</span>
            <span>&bull;</span>
            <span>Timezone: {client.timezone}</span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsEditModalOpen(true)}
            leftIcon={<Edit2 className="h-3.5 w-3.5" />}
          >
            Edit Client
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsCreateAgentOpen(true)}
            leftIcon={<Plus className="h-3.5 w-3.5" />}
          >
            + Create AI Employee
          </Button>
        </div>
      </div>

      {/* Client Information Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Contact Info */}
        <Card title="Primary Contact" className="md:col-span-1">
          <div className="space-y-3 text-xs">
            <div className="flex items-center gap-2 text-slate-300">
              <UserCheck className="h-4 w-4 text-slate-500 shrink-0" />
              <span>{client.contact_name || 'No contact name specified'}</span>
            </div>
            <div className="flex items-center gap-2 text-slate-300">
              <Mail className="h-4 w-4 text-slate-500 shrink-0" />
              <span>{client.contact_email || 'No email specified'}</span>
            </div>
            <div className="flex items-center gap-2 text-slate-300">
              <Phone className="h-4 w-4 text-slate-500 shrink-0" />
              <span>{client.contact_phone || 'No phone specified'}</span>
            </div>
          </div>
        </Card>

        {/* Operational Context */}
        <Card title="Operational Description" className="md:col-span-2">
          <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
            {client.description || 'No description provided for this client account.'}
          </p>
          <div className="mt-4 pt-3 border-t border-[#1b1f2d] flex items-center gap-4 text-[11px] text-slate-500">
            <span className="flex items-center gap-1">
              <Calendar className="h-3.5 w-3.5" /> Created {new Date(client.created_at).toLocaleDateString()}
            </span>
            <span className="flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" /> Updated {new Date(client.updated_at).toLocaleDateString()}
            </span>
          </div>
        </Card>
      </div>

      {/* AI Employees Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
              <Bot className="h-4 w-4 text-[#00df8f]" /> AI Employees ({agents.length})
            </h2>
            <p className="text-xs text-slate-400">
              Voice employees provisioned specifically for {client.name}
            </p>
          </div>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setIsCreateAgentOpen(true)}
            leftIcon={<Plus className="h-3.5 w-3.5" />}
          >
            + Create AI Employee
          </Button>
        </div>

        <Card noPadding>
          <Table
            columns={agentColumns}
            data={agents}
            keyExtractor={(a) => a.id}
            onRowClick={(a) => navigate(`/agents/${a.id}`)}
            emptyState={
              <EmptyState
                icon={<Bot className="h-6 w-6" />}
                title="No AI employees yet."
                description={`No autonomous agents have been built for ${client.name} yet.`}
                action={
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => setIsCreateAgentOpen(true)}
                  >
                    + Create AI Employee
                  </Button>
                }
              />
            }
          />
        </Card>
      </div>

      {/* PROPERTY INVENTORY (synced from Google Sheet / CRM) */}
      {id && <ClientPlanCard clientId={id} onChange={() => setBillingVersion((v) => v + 1)} />}
      {id && <ClientBillingCard key={billingVersion} clientId={id} />}

      {id && <PropertyInventoryCard clientId={id} />}

      {/* CREATE AI EMPLOYEE MODAL */}
      <Modal
        isOpen={isCreateAgentOpen}
        onClose={() => setIsCreateAgentOpen(false)}
        title="Create AI Employee"
        description={`Configure a new voice employee for ${client.name}.`}
        maxWidth="md"
      >
        <form onSubmit={handleCreateAgentSubmit} className="space-y-4">
          {agentError && (
            <div className="rounded border border-rose-900/50 bg-rose-950/30 p-2.5 text-xs text-rose-300">
              {agentError}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">Client</label>
            <div className="text-xs font-semibold text-slate-200 bg-[#0d0e14] px-3 py-2 rounded border border-[#1e2330]">
              {client.name}
            </div>
          </div>

          <Input
            label="Employee Name"
            required
            placeholder="e.g. Hospital Receptionist"
            value={agentForm.name}
            onChange={(e) => setAgentForm({ ...agentForm, name: e.target.value })}
            helperText="Internal display name for this AI agent"
          />

          <Input
            label="Role"
            required
            placeholder="e.g. AI Receptionist or Appointment Coordinator"
            value={agentForm.role}
            onChange={(e) => setAgentForm({ ...agentForm, role: e.target.value })}
            helperText="The business persona this agent performs"
          />

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              Description
            </label>
            <textarea
              rows={3}
              className="block w-full rounded-md border border-[#153945] bg-[#06141a] p-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f]"
              placeholder="Handles incoming patient calls, appointment inquiries, and doctor scheduling..."
              value={agentForm.description || ''}
              onChange={(e) => setAgentForm({ ...agentForm, description: e.target.value })}
            />
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#102d38]">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setIsCreateAgentOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              isLoading={isSubmittingAgent}
            >
              Create AI Employee
            </Button>
          </div>
        </form>
      </Modal>

      {/* EDIT CLIENT MODAL */}
      <Modal
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        title="Edit Client Profile"
        description={`Update settings for ${client.name}`}
        maxWidth="lg"
      >
        <form onSubmit={handleEditSubmit} className="space-y-4">
          {editError && (
            <div className="rounded border border-rose-900/50 bg-rose-950/30 p-2.5 text-xs text-rose-300">
              {editError}
            </div>
          )}

          <Input
            label="Business Name"
            required
            value={editForm.name || ''}
            onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
          />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Select
              label="Status"
              options={[
                { value: 'ACTIVE', label: 'Active' },
                { value: 'INACTIVE', label: 'Inactive' },
              ]}
              value={editForm.status || 'ACTIVE'}
              onChange={(e) => setEditForm({ ...editForm, status: e.target.value as any })}
            />
            <Input
              label="Timezone"
              value={editForm.timezone || 'UTC'}
              onChange={(e) => setEditForm({ ...editForm, timezone: e.target.value })}
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">Description</label>
            <textarea
              rows={3}
              className="block w-full rounded-md border border-[#153945] bg-[#06141a] p-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f]"
              value={editForm.description || ''}
              onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Input
              label="Contact Name"
              value={editForm.contact_name || ''}
              onChange={(e) => setEditForm({ ...editForm, contact_name: e.target.value })}
            />
            <Input
              label="Contact Email"
              type="email"
              value={editForm.contact_email || ''}
              onChange={(e) => setEditForm({ ...editForm, contact_email: e.target.value })}
            />
            <Input
              label="Contact Phone"
              value={editForm.contact_phone || ''}
              onChange={(e) => setEditForm({ ...editForm, contact_phone: e.target.value })}
            />
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#1b1f2d]">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setIsEditModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              isLoading={isSubmittingEdit}
            >
              Save Profile
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
