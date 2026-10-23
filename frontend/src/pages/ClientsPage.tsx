import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Building2, Plus, Search, Eye, Edit2 } from 'lucide-react';
import { clientsService } from '../services/clients';
import { Client, BusinessType, ClientCreateInput, ClientUpdateInput } from '../types';
import { Table, Column } from '../components/common/Table';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Input } from '../components/common/Input';
import { Select } from '../components/common/Select';
import { DEFAULT_TIMEZONE, timezoneOptions } from '../constants/timezones';
import { Modal } from '../components/common/Modal';
import { StatusBadge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';

const BUSINESS_TYPES: { value: BusinessType; label: string }[] = [
  { value: 'CLINIC', label: 'Clinic' },
  { value: 'HOSPITAL', label: 'Hospital' },
  { value: 'SALON', label: 'Salon' },
  { value: 'REAL_ESTATE', label: 'Real Estate' },
  { value: 'HOTEL', label: 'Hotel' },
  { value: 'RESTAURANT', label: 'Restaurant' },
  { value: 'CORPORATE', label: 'Corporate' },
  { value: 'COACHING', label: 'Coaching centre' },
  { value: 'OTHER', label: 'Other' },
];

export const ClientsPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [clients, setClients] = useState<Client[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [search, setSearch] = useState('');
  const [businessTypeFilter, setBusinessTypeFilter] = useState('');

  // Create Modal State
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createForm, setCreateForm] = useState<ClientCreateInput>({
    name: '',
    business_type: 'CLINIC',
    description: '',
    contact_name: '',
    contact_email: '',
    contact_phone: '',
    timezone: DEFAULT_TIMEZONE,
  });

  // Edit Modal State
  const [editingClient, setEditingClient] = useState<Client | null>(null);
  const [editForm, setEditForm] = useState<ClientUpdateInput>({});
  const [editError, setEditError] = useState<string | null>(null);

  const fetchClients = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await clientsService.list({
        search: search || undefined,
        business_type: businessTypeFilter || undefined,
      });
      setClients(res.items);
    } catch (err: any) {
      setError(err.message || 'Failed to load clients');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchClients();
  }, [businessTypeFilter]);

  useEffect(() => {
    if (searchParams.get('action') === 'create') {
      setIsCreateModalOpen(true);
      searchParams.delete('action');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchClients();
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);

    if (!createForm.name.trim()) {
      setCreateError('Business name is required.');
      return;
    }
    if (!createForm.business_type) {
      setCreateError('Business type is required.');
      return;
    }

    setIsSubmitting(true);
    try {
      const created = await clientsService.create(createForm);
      setIsCreateModalOpen(false);
      setCreateForm({
        name: '',
        business_type: 'CLINIC',
        description: '',
        contact_name: '',
        contact_email: '',
        contact_phone: '',
        timezone: DEFAULT_TIMEZONE,
      });
      navigate(`/clients/${created.id}`);
    } catch (err: any) {
      setCreateError(err.message || 'Failed to create client');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingClient) return;

    setEditError(null);
    setIsSubmitting(true);
    try {
      await clientsService.update(editingClient.id, editForm);
      setEditingClient(null);
      fetchClients();
    } catch (err: any) {
      setEditError(err.message || 'Failed to update client');
    } finally {
      setIsSubmitting(false);
    }
  };

  const openEditModal = (client: Client, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingClient(client);
    setEditForm({
      name: client.name,
      business_type: client.business_type,
      description: client.description || '',
      contact_name: client.contact_name || '',
      contact_email: client.contact_email || '',
      contact_phone: client.contact_phone || '',
      timezone: client.timezone,
      status: client.status,
    });
  };

  const columns: Column<Client>[] = [
    {
      key: 'name',
      header: 'Client',
      render: (c) => (
        <div>
          <div className="font-semibold text-slate-100 hover:text-[#00df8f] transition-colors">
            {c.name}
          </div>
          <div className="text-[11px] font-mono">
            {c.client_code && <span className="text-[#00df8f]">{c.client_code}</span>}
            {c.client_code && <span className="text-slate-600"> · </span>}
            <span className="text-slate-500">{c.id}</span>
          </div>
        </div>
      ),
    },
    {
      key: 'business_type',
      header: 'Business Type',
      render: (c) => (
        <span className="text-xs font-medium text-slate-300">
          {c.business_type}
        </span>
      ),
    },
    {
      key: 'agent_count',
      header: 'AI Employees',
      render: (c) => (
        <span className="inline-flex items-center gap-1.5 font-mono text-xs text-slate-300">
          <span className="font-semibold text-[#00df8f]">{c.agent_count}</span>
          <span className="text-slate-500">{c.agent_count === 1 ? 'employee' : 'employees'}</span>
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (c) => <StatusBadge status={c.status} />,
    },
    {
      key: 'created_at',
      header: 'Created',
      render: (c) => (
        <span className="text-xs text-slate-400 font-mono">
          {new Date(c.created_at).toLocaleDateString()}
        </span>
      ),
    },
    {
      key: 'actions',
      header: 'Actions',
      className: 'text-right',
      render: (c) => (
        <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => navigate(`/clients/${c.id}`)}
            leftIcon={<Eye className="h-3.5 w-3.5" />}
          >
            View
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={(e) => openEditModal(c, e)}
            leftIcon={<Edit2 className="h-3.5 w-3.5" />}
          >
            Edit
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-[#1a1e2b]">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100 flex items-center gap-2">
            Clients
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Manage enterprise business client accounts and their voice deployments
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          leftIcon={<Plus className="h-4 w-4" />}
          onClick={() => setIsCreateModalOpen(true)}
        >
          Create Client
        </Button>
      </div>

      {/* Filter / Search Bar */}
      <div className="flex flex-col sm:flex-row gap-3">
        <form onSubmit={handleSearchSubmit} className="flex-1 flex gap-2">
          <Input
            placeholder="Search by name or client ID (CL-10001)..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            leftIcon={<Search className="h-4 w-4" />}
          />
          <Button type="submit" variant="secondary" size="md">
            Search
          </Button>
        </form>
        <div className="w-full sm:w-56">
          <Select
            options={[
              { value: '', label: 'All Business Types' },
              ...BUSINESS_TYPES,
            ]}
            value={businessTypeFilter}
            onChange={(e) => setBusinessTypeFilter(e.target.value)}
          />
        </div>
      </div>

      {/* Table Content */}
      <Card noPadding>
        {isLoading ? (
          <LoadingState message="Fetching client directory..." />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchClients} />
        ) : (
          <Table
            columns={columns}
            data={clients}
            keyExtractor={(c) => c.id}
            onRowClick={(c) => navigate(`/clients/${c.id}`)}
            emptyState={
              <EmptyState
                icon={<Building2 className="h-6 w-6" />}
                title="No clients found."
                description={
                  search || businessTypeFilter
                    ? 'No clients matched your filter criteria.'
                    : 'Get started by creating your first client record.'
                }
                action={
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => setIsCreateModalOpen(true)}
                  >
                    Create Client
                  </Button>
                }
              />
            }
          />
        )}
      </Card>

      {/* CREATE CLIENT MODAL */}
      <Modal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        title="Create Business Client"
        description="Register a new enterprise client to configure custom voice employees."
        maxWidth="lg"
      >
        <form onSubmit={handleCreateSubmit} className="space-y-4">
          {createError && (
            <div className="rounded border border-rose-900/50 bg-rose-950/30 p-2.5 text-xs text-rose-300">
              {createError}
            </div>
          )}

          <Input
            label="Business Name"
            required
            placeholder="e.g. Apex Health Clinic"
            value={createForm.name}
            onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
          />

          <Select
            label="Business Type"
            required
            options={BUSINESS_TYPES}
            value={createForm.business_type}
            onChange={(e) => setCreateForm({ ...createForm, business_type: e.target.value as BusinessType })}
          />

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              Description
            </label>
            <textarea
              rows={3}
              className="block w-full rounded-md border border-[#153945] bg-[#06141a] p-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f]"
              placeholder="Operational context, business goals, or special requirements..."
              value={createForm.description || ''}
              onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Input
              label="Contact Name"
              placeholder="e.g. Dr. John Doe"
              value={createForm.contact_name || ''}
              onChange={(e) => setCreateForm({ ...createForm, contact_name: e.target.value })}
            />
            <Input
              label="Contact Email"
              type="email"
              placeholder="contact@business.com"
              value={createForm.contact_email || ''}
              onChange={(e) => setCreateForm({ ...createForm, contact_email: e.target.value })}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Input
              label="Contact Phone"
              placeholder="+1-555-010-9988"
              value={createForm.contact_phone || ''}
              onChange={(e) => setCreateForm({ ...createForm, contact_phone: e.target.value })}
            />
            <Select
              label="Timezone"
              options={timezoneOptions(createForm.timezone)}
              value={createForm.timezone || DEFAULT_TIMEZONE}
              onChange={(e) => setCreateForm({ ...createForm, timezone: e.target.value })}
            />
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#1b1f2d]">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setIsCreateModalOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              isLoading={isSubmitting}
            >
              Create Client
            </Button>
          </div>
        </form>
      </Modal>

      {/* EDIT CLIENT MODAL */}
      <Modal
        isOpen={!!editingClient}
        onClose={() => setEditingClient(null)}
        title="Edit Client"
        description={`Modify operational parameters for ${editingClient?.name}`}
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
              label="Business Type"
              options={BUSINESS_TYPES}
              value={editForm.business_type || 'OTHER'}
              onChange={(e) => setEditForm({ ...editForm, business_type: e.target.value as BusinessType })}
            />
            <Select
              label="Status"
              options={[
                { value: 'ACTIVE', label: 'Active' },
                { value: 'INACTIVE', label: 'Inactive' },
              ]}
              value={editForm.status || 'ACTIVE'}
              onChange={(e) => setEditForm({ ...editForm, status: e.target.value as any })}
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">
              Description
            </label>
            <textarea
              rows={3}
              className="block w-full rounded-md border border-[#153945] bg-[#06141a] p-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f]"
              value={editForm.description || ''}
              onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Input
              label="Contact Phone"
              value={editForm.contact_phone || ''}
              onChange={(e) => setEditForm({ ...editForm, contact_phone: e.target.value })}
            />
            <Select
              label="Timezone"
              options={timezoneOptions(editForm.timezone)}
              value={editForm.timezone || 'UTC'}
              onChange={(e) => setEditForm({ ...editForm, timezone: e.target.value })}
            />
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#1b1f2d]">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setEditingClient(null)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              isLoading={isSubmitting}
            >
              Save Changes
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
