import { Link } from 'react-router-dom';
import React, { useState, useEffect } from 'react';
import {
  Radio,
  Phone,
  Plus,
  Copy,
  Check,
  ShieldAlert,
  ShieldCheck,
  RefreshCw,
  Trash2,
  Edit2,
  AlertCircle,
  Activity,
  CheckCircle2,
  PhoneOutgoing,
} from 'lucide-react';
import {
  telephonyService,
  PhoneNumber,
  TelephonyOverview,
  PhoneNumberReadiness,
} from '../services/telephony';
import { clientsService } from '../services/clients';
import { agentsService } from '../services/agents';
import { Client, Agent } from '../types';
import { Card } from '../components/common/Card';
import { Badge } from '../components/common/Badge';
import { Button } from '../components/common/Button';
import { Modal } from '../components/common/Modal';
import { Input } from '../components/common/Input';
import { Select } from '../components/common/Select';
import { LoadingState } from '../components/common/LoadingState';
import { EmptyState } from '../components/common/EmptyState';
import { ErrorState } from '../components/common/ErrorState';

const AGENT_SOURCE_PREFIX = 'agent:';

export const TelephonyPage: React.FC = () => {
  const [overview, setOverview] = useState<TelephonyOverview | null>(null);
  const [phoneNumbers, setPhoneNumbers] = useState<PhoneNumber[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [readinessMap, setReadinessMap] = useState<Record<string, PhoneNumberReadiness>>({});

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedWebhook, setCopiedWebhook] = useState(false);

  // Modal states
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isAssignModalOpen, setIsAssignModalOpen] = useState(false);
  const [isDialModalOpen, setIsDialModalOpen] = useState(false);
  const [selectedNumber, setSelectedNumber] = useState<PhoneNumber | null>(null);

  // Form states
  const [newPhoneNumber, setNewPhoneNumber] = useState('');
  const [selectedClientId, setSelectedClientId] = useState('');
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Outbound call states
  const [dialSourceNumberId, setDialSourceNumberId] = useState('');
  const [dialDestinationNumber, setDialDestinationNumber] = useState('');
  const [dialSuccessMessage, setDialSuccessMessage] = useState<string | null>(null);
  const [dialing, setDialing] = useState(false);


  // Current webhook URL
  const webhookUrl = `${window.location.origin}/api/telephony/vobiz/answer`;

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [overviewData, numbersData, clientsRes, agentsRes] = await Promise.all([
        telephonyService.getOverview().catch(() => null),
        telephonyService.getPhoneNumbers(),
        clientsService.list({ limit: 100 }).catch(() => ({ items: [], total: 0 })),
        agentsService.list({ limit: 100 }).catch(() => ({ items: [], total: 0 })),
      ]);

      setOverview(overviewData);
      setPhoneNumbers(numbersData);
      setClients(clientsRes.items || []);
      setAgents(agentsRes.items || []);

      // Check readiness for numbers in parallel
      const readinessChecks: Record<string, PhoneNumberReadiness> = {};
      await Promise.all(
        numbersData.map(async (pn: PhoneNumber) => {
          try {
            const res = await telephonyService.checkReadiness(pn.id);
            readinessChecks[pn.id] = res;
          } catch {
            // ignore
          }
        })
      );
      setReadinessMap(readinessChecks);
    } catch (err: any) {
      setError(err?.message || 'Failed to load telephony data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleCopyWebhook = () => {
    navigator.clipboard.writeText(webhookUrl);
    setCopiedWebhook(true);
    setTimeout(() => setCopiedWebhook(false), 2500);
  };

  const handleCreateNumber = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPhoneNumber || !selectedClientId) {
      setFormError('Phone number and Client are required');
      return;
    }

    try {
      setSaving(true);
      setFormError(null);
      await telephonyService.createPhoneNumber({
        phone_number: newPhoneNumber.trim(),
        client_id: selectedClientId,
        agent_id: selectedAgentId || undefined,
        provider: 'vobiz',
      });
      setIsAddModalOpen(false);
      setNewPhoneNumber('');
      setSelectedClientId('');
      setSelectedAgentId('');
      fetchData();
    } catch (err: any) {
      setFormError(err?.message || 'Failed to create phone number');
    } finally {
      setSaving(false);
    }
  };

  const handleUpdateAssignment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedNumber) return;

    try {
      setSaving(true);
      setFormError(null);
      await telephonyService.updatePhoneNumber(selectedNumber.id, {
        agent_id: selectedAgentId || undefined,
      });
      setIsAssignModalOpen(false);
      setSelectedNumber(null);
      fetchData();
    } catch (err: any) {
      setFormError(err?.message || 'Failed to update phone number assignment');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteNumber = async (id: string, numberStr: string) => {
    if (!confirm(`Are you sure you want to delete phone number ${numberStr}? Active calls on this number will be rejected.`)) {
      return;
    }
    try {
      await telephonyService.deletePhoneNumber(id);
      fetchData();
    } catch (err: any) {
      alert(err?.message || 'Failed to delete phone number');
    }
  };

  const handleToggleStatus = async (pn: PhoneNumber) => {
    const nextStatus = pn.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE';
    try {
      await telephonyService.updatePhoneNumber(pn.id, { status: nextStatus });
      fetchData();
    } catch (err: any) {
      alert(err?.message || 'Failed to toggle status');
    }
  };

  const openAssignModal = (pn: PhoneNumber) => {
    setSelectedNumber(pn);
    setSelectedAgentId(pn.agent_id || '');
    setFormError(null);
    setIsAssignModalOpen(true);
  };

  const handleInitiateOutboundCall = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!dialSourceNumberId || !dialDestinationNumber) {
      setFormError('Please choose who is calling and enter a recipient number.');
      return;
    }
    setDialing(true);
    setFormError(null);
    setDialSuccessMessage(null);
    try {
      let source: { phone_number_id: string } | { agent_id: string; agent_version_id: string };
      if (dialSourceNumberId.startsWith(AGENT_SOURCE_PREFIX)) {
        // Call directly as an agent using its latest published version (caller ID: VOBIZ_CALLER_ID)
        const agentId = dialSourceNumberId.slice(AGENT_SOURCE_PREFIX.length);
        const versions = await agentsService.getVersions(agentId);
        const published = versions
          .filter((v) => v.status === 'PUBLISHED')
          .sort((a, b) => b.version_number - a.version_number)[0];
        if (!published) {
          throw new Error('This agent has no published version yet. Publish a version first.');
        }
        source = { agent_id: agentId, agent_version_id: published.id };
      } else {
        source = { phone_number_id: dialSourceNumberId };
      }
      const res = await telephonyService.initiateOutboundCall({
        ...source,
        destination_number: dialDestinationNumber.trim(),
      });
      setDialSuccessMessage(
        `Outbound call dispatched successfully (Call ID: ${res.id}, Status: ${res.status}). Vobiz will dial ${dialDestinationNumber} shortly.`
      );
      fetchData();
    } catch (err: any) {
      setFormError(err?.message || 'Failed to dispatch outbound call.');
    } finally {
      setDialing(false);
    }
  };

  // Filter agents by chosen client in add modal
  const filteredAgents = selectedClientId
    ? agents.filter((a) => a.client_id === selectedClientId)
    : agents;

  if (loading) {
    return <LoadingState message="Loading Telephony management..." />;
  }

  if (error) {
    return <ErrorState message={error} onRetry={fetchData} />;
  }

  return (
    <div className="p-8 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Radio className="h-6 w-6 text-[#00df8f]" />
            <h1 className="text-2xl font-semibold text-slate-100">Telephony & Numbers</h1>
          </div>
          <p className="text-sm text-slate-400 mt-1">
            Routing for each client's numbers: which AI employee answers, readiness and test calls. Buy, assign and release
            numbers under <Link to="/numbers" className="text-[#00df8f] hover:underline">Phone Numbers</Link>.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="secondary" onClick={fetchData} className="gap-2">
            <RefreshCw className="h-4 w-4" />
            Refresh
          </Button>
          <Button
            variant="secondary"
            onClick={() => {
              setFormError(null);
              setDialSuccessMessage(null);
              const firstAssigned = phoneNumbers.find((p) => p.agent_id && p.status === 'ACTIVE');
              setDialSourceNumberId(firstAssigned?.id || '');
              setDialDestinationNumber('');
              setIsDialModalOpen(true);
            }}
            className="gap-2 border-[#00df8f]/40 hover:border-[#00df8f] text-[#00df8f]"
          >
            <PhoneOutgoing className="h-4 w-4" />
            Make Outbound Call
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              setFormError(null);
              setNewPhoneNumber('');
              setSelectedClientId(clients[0]?.id || '');
              setSelectedAgentId('');
              setIsAddModalOpen(true);
            }}
            className="gap-2"
          >
            <Plus className="h-4 w-4" />
            Provision Number
          </Button>
        </div>
      </div>


      {/* Metrics Banner */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="p-4 bg-[#091b22] border-[#143c49]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Total Numbers</span>
            <Phone className="h-4 w-4 text-[#00df8f]" />
          </div>
          <div className="text-2xl font-bold text-slate-100 mt-2">
            {overview?.total_phone_numbers ?? phoneNumbers.length}
          </div>
          <span className="text-xs text-slate-500 mt-1 block">
            {overview?.assigned_phone_numbers ?? 0} routed to AI agents
          </span>
        </Card>

        <Card className="p-4 bg-[#11141f] border-[#1d2232]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Active Numbers</span>
            <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-slate-100 mt-2">
            {overview?.active_phone_numbers ?? 0}
          </div>
          <span className="text-xs text-slate-500 mt-1 block">Ready for inbound PSTN calls</span>
        </Card>

        <Card className="p-4 bg-[#11141f] border-[#1d2232]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Active Inbound Calls</span>
            <Activity className="h-4 w-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-slate-100 mt-2 flex items-center gap-2">
            {overview?.active_calls_now ?? 0}
            {(overview?.active_calls_now ?? 0) > 0 && (
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500"></span>
              </span>
            )}
          </div>
          <span className="text-xs text-slate-500 mt-1 block">Real-time active media sessions</span>
        </Card>

        <Card className="p-4 bg-[#11141f] border-[#1d2232]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Telephony Provider</span>
            <Radio className="h-4 w-4 text-purple-400" />
          </div>
          <div className="text-lg font-bold text-slate-100 mt-2 capitalize flex items-center gap-2">
            {overview?.provider ?? 'Vobiz'}
            <Badge
              variant={overview?.provider_status === 'CONFIGURED' ? 'green' : 'yellow'}
              size="sm"
            >
              {overview?.provider_status ?? 'READY'}
            </Badge>
          </div>
          <span className="text-xs text-slate-500 mt-1 block">Bidirectional TwiML Streaming</span>
        </Card>
      </div>

      {/* Vobiz Answer URL Callout */}
      <Card className="p-5 bg-gradient-to-r from-[#052b20]/40 via-[#091b22] to-[#0a1e27] border-[#0a4d39]/60">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-[#00df8f]">
                Vobiz Answer URL
              </span>
            </div>
            <p className="text-xs text-slate-300">
              In your Vobiz XML application, set the Answer URL to this endpoint (method POST, append ?token=VOBIZ_WEBHOOK_SECRET):
            </p>
            <div className="flex items-center gap-2 mt-2 font-mono text-xs bg-black/50 px-3 py-1.5 rounded border border-[#0a4d39]/60 text-[#00df8f] break-all select-all">
              <span>{webhookUrl}</span>
            </div>
          </div>
          <div className="shrink-0 flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={handleCopyWebhook}
              className="gap-1.5 text-xs"
            >
              {copiedWebhook ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
              {copiedWebhook ? 'Copied' : 'Copy URL'}
            </Button>
          </div>
        </div>
      </Card>

      {/* Phone Numbers Table */}
      <Card className="bg-[#0f121d] border-[#1b1f2e] overflow-hidden">
        <div className="p-4 border-b border-[#1b1f2e] flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-200">Provisioned Phone Numbers</h2>
          <span className="text-xs text-slate-500">
            {phoneNumbers.length} registered {phoneNumbers.length === 1 ? 'number' : 'numbers'}
          </span>
        </div>

        {phoneNumbers.length === 0 ? (
          <EmptyState
            icon={<Phone className="h-6 w-6 text-slate-400" />}
            title="No Phone Numbers Provisioned"
            description="Add an E.164 phone number from your Vobiz account to assign it to an AI Employee."
            action={
              <Button variant="primary" onClick={() => setIsAddModalOpen(true)}>
                Provision Number
              </Button>
            }
          />
        ) : (
          <div className="w-full overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="border-b border-[#1f2433] bg-[#0c0d14] text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-5 py-3 font-medium">Phone Number</th>
                  <th className="px-5 py-3 font-medium">Client</th>
                  <th className="px-5 py-3 font-medium">Assigned AI Employee</th>
                  <th className="px-5 py-3 font-medium">Status</th>
                  <th className="px-5 py-3 font-medium">Readiness</th>
                  <th className="px-5 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1b1f2b]">
                {phoneNumbers.map((pn) => {
                  const readiness = readinessMap[pn.id];
                  const isReady = readiness?.ready ?? false;

                  return (
                    <tr key={pn.id} className={`hover:bg-[#131620] transition-colors ${pn.status === 'RELEASED' ? 'opacity-50' : ''}`}>
                      <td className="px-5 py-3.5">
                        <span className="font-mono text-slate-200 font-medium">{pn.metadata?.released_number || pn.phone_number}</span>
                        {pn.monthly_rent_inr != null && (
                          <span className={`block text-[11px] ${pn.rental_status === 'PAST_DUE' ? 'text-rose-400' : 'text-slate-500'}`}>
                            ₹{pn.monthly_rent_inr}/mo
                            {pn.rental_status === 'PAST_DUE' && ' · rent due'}
                            {pn.rental_status === 'ACTIVE' && pn.current_period_end &&
                              ` · ${pn.cancel_at_period_end ? 'ends' : 'renews'} ${new Date(pn.current_period_end).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`}
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-slate-300">
                        {pn.client_name || <span className="text-slate-600">—</span>}
                      </td>
                      <td className="px-5 py-3.5">
                        {pn.agent_name ? (
                          <div className="flex items-center gap-1.5">
                            <span className="text-slate-200 text-xs font-medium">{pn.agent_name}</span>
                            {pn.agent_version_number && (
                              <Badge variant="blue" size="sm">
                                v{pn.agent_version_number}
                              </Badge>
                            )}
                          </div>
                        ) : (
                          <span className="text-slate-600 text-xs">Unassigned (Rejects Calls)</span>
                        )}
                      </td>
                      <td className="px-5 py-3.5">
                        <button
                          onClick={() => handleToggleStatus(pn)}
                          title="Click to toggle status"
                          className="cursor-pointer"
                        >
                          <Badge variant={pn.status === 'ACTIVE' ? 'green' : 'gray'} size="sm" dot>
                            {pn.status}
                          </Badge>
                        </button>
                      </td>
                      <td className="px-5 py-3.5">
                        {readiness ? (
                          isReady ? (
                            <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400 font-medium">
                              <ShieldCheck className="h-3.5 w-3.5" />
                              Ready
                            </span>
                          ) : (
                            <span
                              className="inline-flex items-center gap-1 text-[11px] text-rose-400 font-medium cursor-help"
                              title={readiness.errors?.join('; ') || 'Not ready'}
                            >
                              <ShieldAlert className="h-3.5 w-3.5" />
                              {readiness.errors?.length || 1} Issue
                            </span>
                          )
                        ) : (
                          <span className="text-slate-600 text-xs">—</span>
                        )}
                      </td>
                      <td className="px-5 py-3.5 text-right space-x-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openAssignModal(pn)}
                          title="Assign or reassign agent"
                          className="h-8 w-8 p-0"
                        >
                          <Edit2 className="h-3.5 w-3.5 text-slate-400 hover:text-slate-200" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleDeleteNumber(pn.id, pn.phone_number)}
                          title="Delete number"
                          className="h-8 w-8 p-0 hover:bg-rose-950/30 text-slate-500 hover:text-rose-400"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Provision Phone Number Modal */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        title="Provision Inbound Phone Number"
        description="Add a Vobiz phone number to route calls directly into Choranta Voice Runtime."
      >
        <form onSubmit={handleCreateNumber} className="space-y-4">
          {formError && (
            <div className="p-3 bg-rose-950/40 border border-rose-800/50 rounded text-xs text-rose-300 flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{formError}</span>
            </div>
          )}

          <Input
            label="Phone Number (E.164 Format)"
            placeholder="+14155552671"
            value={newPhoneNumber}
            onChange={(e) => setNewPhoneNumber(e.target.value)}
            helperText="Include international country code with leading + (e.g. +14155552671)"
            required
          />

          <Select
            label="Assign to Client"
            value={selectedClientId}
            onChange={(e) => {
              setSelectedClientId(e.target.value);
              setSelectedAgentId('');
            }}
            options={[
              { value: '', label: 'Select a client...' },
              ...clients.map((c) => ({ value: c.id, label: `${c.name} (${c.business_type})` })),
            ]}
            required
          />

          <Select
            label="Assign AI Employee (Optional)"
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            options={[
              { value: '', label: 'None (Unassigned / Hold)' },
              ...filteredAgents.map((a) => ({ value: a.id, label: `${a.name} (${a.role})` })),
            ]}
            helperText="Automatically pins the latest published AgentVersion."
          />

          <div className="flex justify-end gap-3 pt-4 border-t border-[#1f2436]">
            <Button variant="secondary" type="button" onClick={() => setIsAddModalOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" isLoading={saving}>
              Provision Number
            </Button>
          </div>
        </form>
      </Modal>

      {/* Assign / Reassign Agent Modal */}
      <Modal
        isOpen={isAssignModalOpen}
        onClose={() => setIsAssignModalOpen(false)}
        title="Reassign AI Employee"
        description={`Update which AI Employee answers calls to ${selectedNumber?.phone_number}.`}
      >
        <form onSubmit={handleUpdateAssignment} className="space-y-4">
          {formError && (
            <div className="p-3 bg-rose-950/40 border border-rose-800/50 rounded text-xs text-rose-300 flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{formError}</span>
            </div>
          )}

          <div className="text-xs text-slate-400">
            Client: <span className="text-slate-200 font-medium">{selectedNumber?.client_name}</span>
          </div>

          <Select
            label="Select AI Employee"
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            options={[
              { value: '', label: 'Unassigned (Reject Calls)' },
              ...agents
                .filter((a) => a.client_id === selectedNumber?.client_id)
                .map((a) => ({ value: a.id, label: `${a.name} (${a.role})` })),
            ]}
            helperText="Selecting an agent automatically pins its latest published version."
          />

          <div className="flex justify-end gap-3 pt-4 border-t border-[#1f2436]">
            <Button variant="secondary" type="button" onClick={() => setIsAssignModalOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" isLoading={saving}>
              Save Assignment
            </Button>
          </div>
        </form>
      </Modal>

      {/* Outbound Call Modal */}
      <Modal
        isOpen={isDialModalOpen}
        onClose={() => setIsDialModalOpen(false)}
        title="Initiate Outbound Call"
        description="Dispatch an outbound call from your AI voice employee to a customer via Vobiz."
      >
        <form onSubmit={handleInitiateOutboundCall} className="space-y-4">
          {formError && (
            <div className="p-3 bg-rose-950/40 border border-rose-800/50 rounded text-xs text-rose-300 flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{formError}</span>
            </div>
          )}

          {dialSuccessMessage && (
            <div className="p-3 bg-emerald-950/40 border border-emerald-800/50 rounded text-xs text-emerald-300 flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
              <span>{dialSuccessMessage}</span>
            </div>
          )}

          <div className="p-3 rounded-lg bg-[#00df8f]/10 border border-[#00df8f]/20 text-xs text-slate-300 space-y-1">
            <p className="font-medium text-[#00df8f]">How Outbound Calling Works:</p>
            <p className="text-slate-400">
              Vobiz calls the recipient's phone number first. As soon as the customer answers, Vobiz connects them directly to your AI voice agent for full interactive conversation.
            </p>
          </div>

          <Select
            label="Calling From"
            value={dialSourceNumberId}
            onChange={(e) => setDialSourceNumberId(e.target.value)}
            options={[
              { value: '', label: 'Select a number or agent...' },
              ...phoneNumbers
                .filter((p) => p.agent_id && p.status === 'ACTIVE')
                .map((p) => ({
                  value: p.id,
                  label: `${p.phone_number} — ${p.agent_name || 'AI Agent'} (${p.client_name || 'Client'})`,
                })),
              ...agents.map((a) => ({
                value: `${AGENT_SOURCE_PREFIX}${a.id}`,
                label: `${a.name} — call as agent (default number)`,
              })),
            ]}
            helperText="A provisioned number uses its assigned agent. Calling as an agent uses its latest published version and the number in VOBIZ_CALLER_ID."
            required
          />

          <Input
            label="Recipient Phone Number"
            placeholder="+919876543210 or 09876543210"
            value={dialDestinationNumber}
            onChange={(e) => setDialDestinationNumber(e.target.value)}
            helperText="Enter 10-digit mobile number, or standard format with 0 prefix or +91."
            required
          />

          <div className="flex justify-end gap-3 pt-4 border-t border-[#1f2436]">
            <Button variant="secondary" type="button" onClick={() => setIsDialModalOpen(false)}>
              Close
            </Button>
            <Button variant="primary" type="submit" isLoading={dialing} className="gap-1.5">
              <PhoneOutgoing className="h-4 w-4" />
              Dial Customer
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};

