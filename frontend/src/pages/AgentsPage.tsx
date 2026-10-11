import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Bot, Plus, Search, Eye, Edit2, Trash2, Building2, Sparkles, ArrowRight, ArrowLeft, Check, Layers, Wrench, Sliders, ShieldCheck } from 'lucide-react';
import { agentsService } from '../services/agents';
import { clientsService } from '../services/clients';
import { catalogsService } from '../services/catalogs';
import { Agent, Client, AgentCreateInput, AgentUpdateInput, AgentStatus, AgentTemplate } from '../types';
import { Table, Column } from '../components/common/Table';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Input } from '../components/common/Input';
import { Select } from '../components/common/Select';
import { Modal } from '../components/common/Modal';
import { StatusBadge, Badge } from '../components/common/Badge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';

const AGENT_STATUSES: { value: AgentStatus; label: string }[] = [
  { value: 'DRAFT', label: 'Draft' },
  { value: 'TESTING', label: 'Testing' },
  { value: 'READY', label: 'Ready' },
  { value: 'DEPLOYED', label: 'Deployed' },
  { value: 'PAUSED', label: 'Paused' },
  { value: 'ARCHIVED', label: 'Archived' },
];

const AGENT_ROLE_OPTIONS = [
  { value: 'Receptionist', label: 'Receptionist' },
  { value: 'Appointment Coordinator', label: 'Appointment Coordinator' },
  { value: 'Customer Support Specialist', label: 'Customer Support Specialist' },
  { value: 'Sales Assistant', label: 'Sales Assistant' },
  { value: 'Lead Qualification Specialist', label: 'Lead Qualification Specialist' },
  { value: 'Scheduling Coordinator', label: 'Scheduling Coordinator' },
  { value: 'Information Desk Assistant', label: 'Information Desk Assistant' },
  { value: 'Other', label: 'Other' },
];

export const AgentsPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [agents, setAgents] = useState<Agent[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [clientFilter, setClientFilter] = useState('');

  // Template and Creation Flow State
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<AgentTemplate | null>(null);
  const [previewTemplate, setPreviewTemplate] = useState<AgentTemplate | null>(null);
  const [creationStep, setCreationStep] = useState<'select_template' | 'configure'>('select_template');

  // Create Modal
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [createForm, setCreateForm] = useState<AgentCreateInput>({
    client_id: '',
    name: '',
    role: '',
    description: '',
  });

  // Edit Modal
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [editForm, setEditForm] = useState<AgentUpdateInput>({});
  const [editError, setEditError] = useState<string | null>(null);

  // Delete States
  const [deletingAgent, setDeletingAgent] = useState<Agent | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isDeleteAllModalOpen, setIsDeleteAllModalOpen] = useState(false);

  const fetchAgentsAndClients = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [agentsRes, clientsRes, tplsRes] = await Promise.all([
        agentsService.list({
          search: search || undefined,
          status: statusFilter || undefined,
          client_id: clientFilter || undefined,
        }),
        clientsService.list({ limit: 100 }),
        catalogsService.listTemplates().catch(() => []),
      ]);
      setAgents(agentsRes.items);
      setTotal(agentsRes.total);
      setClients(clientsRes.items);
      if (tplsRes && tplsRes.length > 0) {
        setTemplates(tplsRes);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load AI employees');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAgentsAndClients();
  }, [statusFilter, clientFilter]);

  const handleOpenCreateModal = () => {
    setCreationStep('select_template');
    setSelectedTemplate(null);
    setCreateError(null);
    setCreateForm({
      client_id: '',
      name: '',
      role: '',
      description: '',
      template_id: undefined,
    });
    setIsCreateModalOpen(true);
  };

  const handleSelectTemplate = (tpl: AgentTemplate) => {
    setSelectedTemplate(tpl);
    setCreateForm((prev) => ({
      ...prev,
      name: 'Real Estate Lead Qualification Assistant',
      role: tpl.recommended_role || 'Lead Qualification Specialist',
      description: tpl.description || '',
      template_id: tpl.id,
    }));
    setCreationStep('configure');
  };

  const handleSelectBlank = () => {
    setSelectedTemplate(null);
    setCreateForm((prev) => ({
      ...prev,
      name: '',
      role: '',
      description: '',
      template_id: undefined,
    }));
    setCreationStep('configure');
  };

  useEffect(() => {
    if (searchParams.get('action') === 'create') {
      handleOpenCreateModal();
      searchParams.delete('action');
      setSearchParams(searchParams, { replace: true });
    }
  }, [searchParams]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchAgentsAndClients();
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError(null);

    if (!createForm.client_id) {
      setCreateError('Please select a client business.');
      return;
    }
    if (!createForm.name.trim()) {
      setCreateError('Employee name is required.');
      return;
    }
    if (!createForm.role.trim()) {
      setCreateError('Role is required.');
      return;
    }

    setIsSubmitting(true);
    try {
      const created = await agentsService.create(createForm);
      setIsCreateModalOpen(false);
      setCreateForm({ client_id: '', name: '', role: '', description: '' });
      navigate(`/agents/${created.id}`);
    } catch (err: any) {
      setCreateError(err.message || 'Failed to create AI employee');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingAgent) return;
    setEditError(null);
    setIsSubmitting(true);
    try {
      await agentsService.update(editingAgent.id, editForm);
      setEditingAgent(null);
      fetchAgentsAndClients();
    } catch (err: any) {
      setEditError(err.message || 'Failed to update agent');
    } finally {
      setIsSubmitting(false);
    }
  };

  const openEditModal = (agent: Agent, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingAgent(agent);
    setEditForm({
      name: agent.name,
      role: agent.role,
      description: agent.description || '',
      status: agent.status,
    });
  };

  const handleDeleteAgent = async () => {
    if (!deletingAgent) return;
    setIsDeleting(true);
    try {
      await agentsService.delete(deletingAgent.id);
      setDeletingAgent(null);
      fetchAgentsAndClients();
    } catch (err: any) {
      alert(`Failed to delete AI employee: ${err.message || 'Error occurred'}`);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleDeleteAll = async () => {
    setIsDeleting(true);
    try {
      await agentsService.deleteAll();
      setIsDeleteAllModalOpen(false);
      fetchAgentsAndClients();
    } catch (err: any) {
      alert(`Failed to delete all AI employees: ${err.message || 'Error occurred'}`);
    } finally {
      setIsDeleting(false);
    }
  };

  const columns: Column<Agent>[] = [
    {
      key: 'name',
      header: 'Agent Name',
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
      key: 'client_name',
      header: 'Client',
      render: (a) => (
        <span
          className="text-xs font-medium text-slate-300 hover:text-[#00df8f] cursor-pointer transition-colors"
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/clients/${a.client_id}`);
          }}
        >
          {a.client_name || 'Client'}
        </span>
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
        <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => navigate(`/agents/${a.id}`)}
            leftIcon={<Eye className="h-3.5 w-3.5" />}
          >
            View
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={(e) => openEditModal(a, e)}
            leftIcon={<Edit2 className="h-3.5 w-3.5" />}
          >
            Edit
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={(e) => {
              e.stopPropagation();
              setDeletingAgent(a);
            }}
            className="text-red-400 hover:text-red-300 hover:bg-red-950/40"
            leftIcon={<Trash2 className="h-3.5 w-3.5" />}
          >
            Delete
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
            AI Employees
          </h1>
          <p className="text-xs text-slate-400 mt-0.5">
            Directory of autonomous AI voice employees across all business clients
          </p>
        </div>
        <div className="flex items-center gap-2">
          {agents.length > 0 && (
            <Button
              variant="danger"
              size="sm"
              leftIcon={<Trash2 className="h-3.5 w-3.5" />}
              onClick={() => setIsDeleteAllModalOpen(true)}
            >
              Remove All
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            leftIcon={<Plus className="h-4 w-4" />}
            onClick={handleOpenCreateModal}
          >
            + Create AI Employee
          </Button>
        </div>
      </div>

      {/* Filter / Search Bar */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        <form onSubmit={handleSearchSubmit} className="sm:col-span-2 flex gap-2">
          <Input
            placeholder="Search by agent name or role..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            leftIcon={<Search className="h-4 w-4" />}
          />
          <Button type="submit" variant="secondary" size="md">
            Search
          </Button>
        </form>

        <Select
          options={[
            { value: '', label: 'All Clients' },
            ...clients.map((c) => ({ value: c.id, label: c.name })),
          ]}
          value={clientFilter}
          onChange={(e) => setClientFilter(e.target.value)}
        />

        <Select
          options={[
            { value: '', label: 'All Statuses' },
            ...AGENT_STATUSES,
          ]}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        />
      </div>

      {/* Table Content */}
      <Card noPadding>
        {isLoading ? (
          <LoadingState message="Fetching AI employee directory..." />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchAgentsAndClients} />
        ) : (
          <Table
            columns={columns}
            data={agents}
            keyExtractor={(a) => a.id}
            onRowClick={(a) => navigate(`/agents/${a.id}`)}
            emptyState={
              <EmptyState
                icon={<Bot className="h-6 w-6" />}
                title="No AI employees found."
                description={
                  search || statusFilter || clientFilter
                    ? 'No agents matched your search filter criteria.'
                    : 'Start by creating your first AI employee for an onboarded client.'
                }
                action={
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={handleOpenCreateModal}
                  >
                    + Create AI Employee
                  </Button>
                }
              />
            }
          />
        )}
      </Card>

      {/* CREATE AI EMPLOYEE MODAL (WITH TEMPLATE SELECTION FLOW) */}
      <Modal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        title={
          creationStep === 'select_template'
            ? 'Create AI Employee — Choose Starting Blueprint'
            : selectedTemplate
            ? `New AI Employee: ${selectedTemplate.name}`
            : 'New AI Employee: Custom Blank'
        }
        description={
          creationStep === 'select_template'
            ? 'Choose a pre-configured enterprise blueprint or start from an empty canvas.'
            : 'Assign this AI employee to a client business workspace to initialize an independent draft.'
        }
        maxWidth={creationStep === 'select_template' ? '2xl' : 'lg'}
      >
        {creationStep === 'select_template' ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* CARD 1: REAL ESTATE LEAD QUALIFICATION (FEATURED TEMPLATE) */}
              <div className="relative flex flex-col justify-between rounded-xl border border-[#00df8f]/40 bg-gradient-to-b from-[#06191f] to-[#041014] p-5 shadow-lg shadow-emerald-950/20 hover:border-[#00df8f] transition-all">
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1.5 rounded-full bg-[#00df8f]/20 border border-[#00df8f]/40 px-2.5 py-0.5 text-[10px] font-bold text-[#00df8f]">
                      <Sparkles className="h-3 w-3" /> FEATURED TEMPLATE
                    </span>
                    <span className="rounded bg-emerald-950/80 border border-emerald-800/60 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                      🇮🇳 India Focused
                    </span>
                  </div>

                  <div>
                    <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
                      Real Estate Lead Qualification
                    </h3>
                    <p className="text-xs text-slate-300 mt-1 leading-relaxed">
                      An AI voice sales assistant that contacts property leads, understands their requirements, qualifies potential buyers, recommends matching properties, and arranges the next step with the sales team.
                    </p>
                  </div>

                  <div className="space-y-1.5 pt-2 border-t border-[#12313b]">
                    <span className="text-[10px] uppercase font-bold tracking-wider text-slate-400">
                      Included Blueprint Capabilities:
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="rounded bg-[#0c242c] border border-[#164352] px-2 py-0.5 text-[10px] text-slate-200">
                        Property Catalog Search
                      </span>
                      <span className="rounded bg-[#0c242c] border border-[#164352] px-2 py-0.5 text-[10px] text-slate-200">
                        Buyer Qualification
                      </span>
                      <span className="rounded bg-[#0c242c] border border-[#164352] px-2 py-0.5 text-[10px] text-slate-200">
                        Site Visit Calendar
                      </span>
                      <span className="rounded bg-[#0c242c] border border-[#164352] px-2 py-0.5 text-[10px] text-slate-200">
                        Cartesia Voice (Siya / en-IN, hi, te)
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center justify-between gap-2 pt-4 mt-4 border-t border-[#12313b]">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      const tpl = templates.find((t) => t.id === 'real_estate_lead_qualification') || {
                        id: 'real_estate_lead_qualification',
                        name: 'Real Estate Lead Qualification',
                        description: 'An AI voice sales assistant that contacts property leads...',
                        category: 'Real Estate / Sales',
                        supported_capabilities: [
                          'Caller identity confirmation',
                          'Budget, location, BHK qualification',
                          'Inventory property search',
                          'Site-visit slot checking',
                          'Structured lead record updates',
                        ],
                        is_featured: true,
                        recommended_role: 'Lead Qualification Specialist',
                      };
                      setPreviewTemplate(tpl);
                    }}
                    leftIcon={<Eye className="h-3.5 w-3.5" />}
                  >
                    Preview Blueprint
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      const tpl = templates.find((t) => t.id === 'real_estate_lead_qualification') || {
                        id: 'real_estate_lead_qualification',
                        name: 'Real Estate Lead Qualification',
                        description: 'An AI voice sales assistant that contacts property leads...',
                        category: 'Real Estate / Sales',
                        supported_capabilities: [],
                        is_featured: true,
                        recommended_role: 'Lead Qualification Specialist',
                      };
                      handleSelectTemplate(tpl);
                    }}
                    rightIcon={<ArrowRight className="h-3.5 w-3.5" />}
                  >
                    Use Template
                  </Button>
                </div>
              </div>

              {/* CARD 2: BLANK AGENT CANVAS */}
              <div className="relative flex flex-col justify-between rounded-xl border border-[#1b1f2d] bg-[#0c0e14] p-5 shadow-sm hover:border-slate-700 transition-all">
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1.5 rounded-full bg-[#1b1f2d] border border-[#2b3145] px-2.5 py-0.5 text-[10px] font-semibold text-slate-300">
                      <Bot className="h-3 w-3" /> CUSTOM BLUEPRINT
                    </span>
                  </div>

                  <div>
                    <h3 className="text-base font-bold text-slate-100 flex items-center gap-2">
                      Blank Voice Employee
                    </h3>
                    <p className="text-xs text-slate-400 mt-1 leading-relaxed">
                      Start from an empty slate. Manually author prompt instructions, create custom input/output variables, attach tools, and configure your own voice and language settings.
                    </p>
                  </div>

                  <div className="space-y-1.5 pt-2 border-t border-[#1b1f2d]">
                    <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500">
                      Custom Architecture:
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      <span className="rounded bg-[#151824] border border-[#232738] px-2 py-0.5 text-[10px] text-slate-400">
                        Custom Identity
                      </span>
                      <span className="rounded bg-[#151824] border border-[#232738] px-2 py-0.5 text-[10px] text-slate-400">
                        Manual Instructions
                      </span>
                      <span className="rounded bg-[#151824] border border-[#232738] px-2 py-0.5 text-[10px] text-slate-400">
                        Custom Tools
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center justify-end gap-2 pt-4 mt-4 border-t border-[#1b1f2d]">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={handleSelectBlank}
                    rightIcon={<ArrowRight className="h-3.5 w-3.5" />}
                  >
                    Start Blank
                  </Button>
                </div>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <Button type="button" variant="ghost" size="sm" onClick={() => setIsCreateModalOpen(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleCreateSubmit} className="space-y-4">
            {createError && (
              <div className="rounded border border-rose-900/50 bg-rose-950/30 p-2.5 text-xs text-rose-300">
                {createError}
              </div>
            )}

            {/* Template Info Banner */}
            <div className="flex items-center justify-between rounded-lg border border-[#143c49] bg-[#071922] p-3 text-xs">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-[#00df8f]" />
                <div>
                  <span className="text-slate-400">Selected Blueprint: </span>
                  <span className="font-semibold text-slate-100">
                    {selectedTemplate ? selectedTemplate.name : 'Blank Custom Employee'}
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setCreationStep('select_template')}
                className="text-xs text-[#00df8f] hover:underline font-medium"
              >
                Change Blueprint
              </button>
            </div>

            <Select
              label="Client Business Workspace"
              required
              placeholder="Select a client..."
              options={clients.map((c) => ({ value: c.id, label: `${c.name} (${c.business_type})` }))}
              value={createForm.client_id}
              onChange={(e) => setCreateForm({ ...createForm, client_id: e.target.value })}
              helperText="The created agent draft will be stored independently in this workspace."
            />

            <Input
              label="Employee Name"
              required
              placeholder="e.g. Real Estate Lead Qualification Assistant"
              value={createForm.name}
              onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
            />

            <Select
              label="Role"
              required
              placeholder="Select a role..."
              options={AGENT_ROLE_OPTIONS}
              value={createForm.role}
              onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}
              helperText="Primary business function and conversational objective."
            />

            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-300">Description</label>
              <textarea
                rows={3}
                className="block w-full rounded-md border border-[#153945] bg-[#06141a] p-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f]"
                placeholder="Operational responsibilities and conversation handling goals..."
                value={createForm.description || ''}
                onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
              />
            </div>

            <div className="flex items-center justify-between gap-3 pt-3 border-t border-[#102d38]">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setCreationStep('select_template')}
                leftIcon={<ArrowLeft className="h-3.5 w-3.5" />}
              >
                Back to Blueprints
              </Button>
              <div className="flex gap-2">
                <Button type="button" variant="ghost" onClick={() => setIsCreateModalOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" variant="primary" isLoading={isSubmitting}>
                  Create Draft &amp; Open Canvas
                </Button>
              </div>
            </div>
          </form>
        )}
      </Modal>

      {/* TEMPLATE PREVIEW MODAL */}
      <Modal
        isOpen={!!previewTemplate}
        onClose={() => setPreviewTemplate(null)}
        title="Template Blueprint Preview: Real Estate Lead Qualification"
        description="Inspect the persona, greeting placeholders, variables, and mock tool capabilities."
        maxWidth="2xl"
      >
        <div className="space-y-5 text-xs text-slate-300">
          {/* Persona & Objective */}
          <div className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-4 space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="font-semibold text-slate-100 text-sm">Agent Identity &amp; Persona</h4>
              <Badge variant="green">Role: Lead Qualification Specialist</Badge>
            </div>
            <p className="text-slate-300 leading-relaxed">
              A professional, friendly, and consultative AI sales assistant representing a real estate enterprise. Contacts property leads, understands their requirements, confirms budget and BHK preferences, searches approved property inventory, and arranges site visits.
            </p>
          </div>

          {/* Sample Greeting */}
          <div className="rounded-lg border border-[#12313b] bg-[#05151b] p-4 space-y-2">
            <span className="font-semibold text-[#00df8f] block">Configurable Initial Greeting</span>
            <div className="rounded border border-[#1b4e5f] bg-[#09222c] p-3 font-mono text-slate-100 text-[11px] leading-relaxed">
              &ldquo;Hello, am I speaking with <span className="text-[#00df8f] font-bold">&#123;&#123;user_name&#125;&#125;</span>? I&apos;m calling from <span className="text-[#00df8f] font-bold">&#123;&#123;company_name&#125;&#125;</span> regarding your property enquiry.&rdquo;
            </div>
            <p className="text-[11px] text-slate-400">
              &bull; Dynamic placeholders are substituted from CRM/lead records. If the caller name is missing, a natural greeting is used without speaking raw placeholder tokens.
            </p>
          </div>

          {/* Preconfigured Variables */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-3 space-y-2">
              <h5 className="font-bold text-slate-200 flex items-center gap-1.5">
                <Sliders className="h-3.5 w-3.5 text-[#00df8f]" /> Input Variables (2)
              </h5>
              <div className="flex flex-wrap gap-1 font-mono text-[10px]">
                {['user_name', 'company_name'].map((v) => (
                  <span key={v} className="rounded bg-[#151824] px-1.5 py-0.5 text-slate-300 border border-[#22283a]">
                    &#123;&#123;{v}&#125;&#125;
                  </span>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-3 space-y-2">
              <h5 className="font-bold text-slate-200 flex items-center gap-1.5">
                <Sliders className="h-3.5 w-3.5 text-purple-400" /> Output Variables (3)
              </h5>
              <div className="flex flex-wrap gap-1 font-mono text-[10px]">
                {[
                  'buyer_budget',
                  'buyer_location',
                  'lead_qualification_status',
                ].map((v) => (
                  <span key={v} className="rounded bg-purple-950/40 px-1.5 py-0.5 text-purple-300 border border-purple-900/50">
                    {v}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Logical Tools */}
          <div className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-3 space-y-2">
            <h5 className="font-bold text-slate-200 flex items-center gap-1.5">
              <Wrench className="h-3.5 w-3.5 text-emerald-400" /> Preconfigured Logical Tools (2)
            </h5>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
              <div className="rounded border border-[#1a2332] bg-[#0f1420] p-2">
                <span className="font-mono font-semibold text-emerald-300">search_properties</span>
                <p className="text-slate-400 text-[10px] mt-0.5">Filters approved properties by price, BHK, and location.</p>
              </div>
              <div className="rounded border border-[#1a2332] bg-[#0f1420] p-2">
                <span className="font-mono font-semibold text-emerald-300">update_lead_record</span>
                <p className="text-slate-400 text-[10px] mt-0.5">Saves confirmed preferences &amp; call disposition.</p>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#1b1f2d]">
            <Button type="button" variant="ghost" onClick={() => setPreviewTemplate(null)}>
              Close Preview
            </Button>
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                if (previewTemplate) {
                  handleSelectTemplate(previewTemplate);
                  setPreviewTemplate(null);
                  setIsCreateModalOpen(true);
                }
              }}
              rightIcon={<ArrowRight className="h-3.5 w-3.5" />}
            >
              Use This Blueprint
            </Button>
          </div>
        </div>
      </Modal>

      {/* EDIT AI EMPLOYEE MODAL */}
      <Modal
        isOpen={!!editingAgent}
        onClose={() => setEditingAgent(null)}
        title="Edit AI Employee"
        description={`Modify properties for ${editingAgent?.name}`}
        maxWidth="md"
      >
        <form onSubmit={handleEditSubmit} className="space-y-4">
          {editError && (
            <div className="rounded border border-rose-900/50 bg-rose-950/30 p-2.5 text-xs text-rose-300">
              {editError}
            </div>
          )}

          <Input
            label="Employee Name"
            required
            value={editForm.name || ''}
            onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
          />

          <Input
            label="Role"
            required
            value={editForm.role || ''}
            onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
          />

          <Select
            label="Lifecycle Status"
            options={AGENT_STATUSES}
            value={editForm.status || 'DRAFT'}
            onChange={(e) => setEditForm({ ...editForm, status: e.target.value as AgentStatus })}
          />

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

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#102d38]">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setEditingAgent(null)}
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

      {/* DELETE SINGLE AI EMPLOYEE MODAL */}
      <Modal
        isOpen={!!deletingAgent}
        onClose={() => setDeletingAgent(null)}
        title="Delete AI Employee"
        description="Are you sure you want to permanently delete this AI employee? All versions, configurations, and conversation logs will be removed."
        maxWidth="sm"
      >
        <div className="space-y-4">
          <div className="rounded-lg border border-red-900/40 bg-red-950/20 p-3 text-xs text-red-300">
            You are about to delete <span className="font-semibold text-white">{deletingAgent?.name}</span> ({deletingAgent?.id}). This action cannot be undone.
          </div>
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#102d38]">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setDeletingAgent(null)}
              disabled={isDeleting}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              className="bg-red-600 hover:bg-red-500 text-white"
              isLoading={isDeleting}
              onClick={handleDeleteAgent}
            >
              Confirm Delete
            </Button>
          </div>
        </div>
      </Modal>

      {/* DELETE ALL AI EMPLOYEES MODAL */}
      <Modal
        isOpen={isDeleteAllModalOpen}
        onClose={() => setIsDeleteAllModalOpen(false)}
        title="Delete All AI Employees"
        description="This will permanently delete all AI employees and their corresponding version histories and runtime logs."
        maxWidth="sm"
      >
        <div className="space-y-4">
          <div className="rounded-lg border border-red-900/40 bg-red-950/20 p-3 text-xs text-red-300">
            ⚠️ <strong>Warning:</strong> You are about to delete all {total} AI employees. This action cannot be undone.
          </div>
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#102d38]">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setIsDeleteAllModalOpen(false)}
              disabled={isDeleting}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              className="bg-red-600 hover:bg-red-500 text-white"
              isLoading={isDeleting}
              onClick={handleDeleteAll}
            >
              Delete All
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
