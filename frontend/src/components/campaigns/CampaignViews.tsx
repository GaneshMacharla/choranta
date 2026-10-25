import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  AlertCircle,
  ArrowLeft,
  Ban,
  ChevronRight,
  Copy,
  Globe,
  Pencil,
  KeyRound,
  Download,
  Megaphone,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Search,
  Square,
  Trash2,
  XCircle,
  Zap,
} from 'lucide-react';
import { Badge } from '../common/Badge';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { Input } from '../common/Input';
import { Select } from '../common/Select';
import { LoadingState } from '../common/LoadingState';
import { ErrorState } from '../common/ErrorState';
import { CampaignWizardModal } from './CampaignWizardModal';
import { MockCallOutcomes } from './MockCallOutcomes';
import { CollectedAnswers } from './CollectedAnswers';
import { formatOutputValue } from '../calls/CallOutputsCard';
import { WhatsAppThread } from '../calls/WhatsAppThread';
import { QualificationBadge } from '../calls/QualificationBadge';
import {
  Campaign,
  CampaignKind,
  CampaignRecipient,
  CampaignScope,
  CampaignStatus,
  DAY_LABELS,
  DoNotCallEntry,
  RecipientStatus,
  campaignsApi,
  minutesToTime,
} from '../../services/campaigns';

const POLL_MS = 5000;
const LIVE: CampaignStatus[] = ['SCHEDULED', 'RUNNING', 'STOPPING'];

const STATUS_BADGE: Record<CampaignStatus, { label: string; variant: 'green' | 'yellow' | 'red' | 'gray' | 'blue' | 'purple'; dot?: boolean }> = {
  DRAFT: { label: 'Draft', variant: 'gray' },
  SCHEDULED: { label: 'Scheduled', variant: 'purple' },
  RUNNING: { label: 'Running', variant: 'green', dot: true },
  PAUSED: { label: 'Paused', variant: 'yellow' },
  STOPPING: { label: 'Stopping', variant: 'yellow', dot: true },
  COMPLETED: { label: 'Completed', variant: 'blue' },
  CANCELLED: { label: 'Cancelled', variant: 'red' },
};

const RECIPIENT_BADGE: Record<RecipientStatus, { label: string; variant: 'green' | 'yellow' | 'red' | 'gray' | 'blue' | 'purple' }> = {
  PENDING: { label: 'Pending', variant: 'gray' },
  DIALING: { label: 'On call', variant: 'green' },
  RETRY_WAIT: { label: 'Retry later', variant: 'yellow' },
  COMPLETED: { label: 'Answered', variant: 'blue' },
  FAILED: { label: 'Failed', variant: 'red' },
  SKIPPED: { label: 'Skipped', variant: 'gray' },
};

export const CampaignStatusBadge: React.FC<{ status: CampaignStatus }> = ({ status }) => {
  const b = STATUS_BADGE[status] || { label: status, variant: 'gray' as const };
  return (
    <Badge variant={b.variant} size="sm" dot={b.dot}>
      {b.label}
    </Badge>
  );
};

const KindBadge: React.FC<{ campaign: Campaign }> = ({ campaign }) =>
  campaign.kind === 'TRIGGER' ? (
    <Badge variant="purple" size="sm">
      Website leads
    </Badge>
  ) : null;

const ProgressBar: React.FC<{ campaign: Campaign }> = ({ campaign }) => {
  const { total, done, answered } = campaign.stats;
  if (campaign.kind === 'TRIGGER') {
    return (
      <div className="text-[11px] text-slate-500">
        {total.toLocaleString()} leads · {answered.toLocaleString()} answered · {(campaign.stats.pending + campaign.stats.retry_wait + campaign.stats.dialing).toLocaleString()} in progress
      </div>
    );
  }
  const pct = total ? Math.round((done / total) * 100) : 0;
  const answeredPct = total ? (answered / total) * 100 : 0;
  return (
    <div className="space-y-1">
      <div className="relative h-1.5 overflow-hidden rounded-full bg-[#143c49]">
        <div className="absolute inset-y-0 left-0 bg-[#00df8f]/40" style={{ width: `${pct}%` }} />
        <div className="absolute inset-y-0 left-0 bg-[#00df8f]" style={{ width: `${answeredPct}%` }} />
      </div>
      <div className="text-[11px] text-slate-500">
        {done.toLocaleString()} / {total.toLocaleString()} done · {answered.toLocaleString()} answered
      </div>
    </div>
  );
};

const scheduleSummary = (c: Campaign) =>
  `${c.windows.map((w) => `${minutesToTime(w.start_min)}–${minutesToTime(w.end_min)}`).join(', ')} · ${[...c.days]
    .sort()
    .map((d) => DAY_LABELS[d])
    .join(' ')}`;

function useCampaignActions(scope: CampaignScope, onChange: (c?: Campaign) => void, setError: (e: string | null) => void) {
  const api = useMemo(() => campaignsApi(scope), [scope]);
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (campaign: Campaign, action: 'pause' | 'resume' | 'stop' | 'cancel' | 'delete' | 'launch') => {
    if (action === 'stop' && !window.confirm('Stop this campaign? Calls in progress finish; nobody else will be called.')) return;
    if (action === 'delete' && !window.confirm(`Delete "${campaign.name}" and its results?`)) return;
    if (
      action === 'launch' &&
      !window.confirm('Launch now? I confirm these people agreed to be contacted, and opt-outs go on the do-not-call list.')
    )
      return;
    setBusy(`${campaign.id}:${action}`);
    setError(null);
    try {
      if (action === 'delete') {
        await api.remove(campaign.id);
        onChange();
      } else if (action === 'launch') {
        onChange(await api.launch(campaign.id, true));
      } else {
        onChange(await api.action(campaign.id, action));
      }
    } catch (e: any) {
      setError(e.message || 'Action failed.');
    } finally {
      setBusy(null);
    }
  };
  return { api, busy, run };
}

const ActionButtons: React.FC<{
  campaign: Campaign;
  busy: string | null;
  run: (c: Campaign, a: 'pause' | 'resume' | 'stop' | 'cancel' | 'delete' | 'launch') => void;
}> = ({ campaign: c, busy, run }) => {
  const is = (a: string) => busy === `${c.id}:${a}`;
  return (
    <div className="flex flex-wrap gap-1.5" onClick={(e) => e.stopPropagation()}>
      {c.status === 'DRAFT' && (
        <Button size="sm" variant="primary" isLoading={is('launch')} leftIcon={<Play className="h-3.5 w-3.5" />} onClick={() => run(c, 'launch')}>
          Launch
        </Button>
      )}
      {(c.status === 'RUNNING' || c.status === 'SCHEDULED') && (
        <Button size="sm" variant="secondary" isLoading={is('pause')} leftIcon={<Pause className="h-3.5 w-3.5" />} onClick={() => run(c, 'pause')}>
          Pause
        </Button>
      )}
      {c.status === 'PAUSED' && (
        <Button size="sm" variant="primary" isLoading={is('resume')} leftIcon={<Play className="h-3.5 w-3.5" />} onClick={() => run(c, 'resume')}>
          Resume
        </Button>
      )}
      {(c.status === 'RUNNING' || c.status === 'PAUSED') && (
        <Button size="sm" variant="ghost" isLoading={is('stop')} leftIcon={<Square className="h-3.5 w-3.5" />} onClick={() => run(c, 'stop')}>
          Stop
        </Button>
      )}
      {(c.status === 'DRAFT' || c.status === 'SCHEDULED') && (
        <Button size="sm" variant="ghost" isLoading={is('cancel')} leftIcon={<XCircle className="h-3.5 w-3.5" />} onClick={() => run(c, 'cancel')}>
          Cancel
        </Button>
      )}
      {(c.status === 'DRAFT' || c.status === 'CANCELLED' || c.status === 'COMPLETED') && (
        <Button size="sm" variant="ghost" isLoading={is('delete')} leftIcon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => run(c, 'delete')}>
          Delete
        </Button>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------- list

const LIST_COPY: Record<CampaignKind, { title: string; subtitle: string; create: string; empty: string; emptyHint: string; loading: string }> = {
  BULK: {
    title: 'Campaigns',
    subtitle: 'Have an AI Employee call a list of people inside set calling hours, with retries for unanswered calls.',
    create: 'Schedule campaign',
    empty: 'No campaigns yet',
    emptyHint: 'Upload a CSV or pick leads, choose calling hours, and launch.',
    loading: 'Loading campaigns...',
  },
  TRIGGER: {
    title: 'Instant Outbound',
    subtitle: 'Call every website form submission within seconds, during your calling hours.',
    create: 'New instant outbound',
    empty: 'No instant outbound yet',
    emptyHint: 'Pick an AI Employee and calling hours, then connect your website form with an API key.',
    loading: 'Loading instant outbound...',
  },
};

export const CampaignsList: React.FC<{ scope: CampaignScope; basePath: string; kind?: CampaignKind }> = ({
  scope,
  basePath,
  kind = 'BULK',
}) => {
  const copy = LIST_COPY[kind];
  const TitleIcon = kind === 'TRIGGER' ? Zap : Megaphone;
  const navigate = useNavigate();
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [wizardOpen, setWizardOpen] = useState(false);
  const [dncOpen, setDncOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setCampaigns(await campaignsApi(scope).list({ status: statusFilter || undefined, kind }));
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Could not load campaigns.');
    } finally {
      setLoading(false);
    }
  }, [scope, statusFilter, kind]);

  const { api, busy, run } = useCampaignActions(scope, () => load(), setError);

  useEffect(() => {
    load();
  }, [load]);

  const anyLive = campaigns.some((c) => LIVE.includes(c.status));
  useEffect(() => {
    if (!anyLive) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [anyLive, load]);

  if (loading) return <LoadingState message={copy.loading} />;
  if (error && campaigns.length === 0) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="flex items-center gap-2">
            <TitleIcon className="h-6 w-6 text-[#00df8f]" />
            <h1 className="text-2xl font-semibold text-slate-100">{copy.title}</h1>
          </div>
          <p className="mt-1 text-sm text-slate-400">{copy.subtitle}</p>
        </div>
        <div className="flex gap-2">
          {scope === 'portal' && (
            <Button variant="ghost" leftIcon={<Ban className="h-4 w-4" />} onClick={() => setDncOpen(true)}>
              Do-not-call list
            </Button>
          )}
          <Button variant="secondary" leftIcon={<RefreshCw className="h-4 w-4" />} onClick={load}>
            Refresh
          </Button>
          <Button variant="primary" leftIcon={<Plus className="h-4 w-4" />} onClick={() => setWizardOpen(true)}>
            {copy.create}
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/50 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      <div className="w-56">
        <Select
          size="sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          options={[{ value: '', label: 'All statuses' }, ...Object.entries(STATUS_BADGE).map(([v, b]) => ({ value: v, label: b.label }))]}
        />
      </div>

      {campaigns.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#143c49] p-10 text-center">
          <TitleIcon className="mx-auto h-8 w-8 text-slate-500" />
          <p className="mt-3 text-sm text-slate-300">{copy.empty}</p>
          <p className="mt-1 text-xs text-slate-500">{copy.emptyHint}</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[#143c49]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#091b22] text-xs text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">{kind === 'TRIGGER' ? 'Name' : 'Campaign'}</th>
                {scope === 'admin' && <th className="px-4 py-3 font-medium">Client</th>}
                <th className="px-4 py-3 font-medium">Agent</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="w-56 px-4 py-3 font-medium">Progress</th>
                <th className="px-4 py-3 font-medium">Answer rate</th>
                <th className="px-4 py-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => (
                <tr
                  key={c.id}
                  className="cursor-pointer border-t border-[#102d38] hover:bg-[#0b222b]"
                  onClick={() => navigate(`${basePath}/${c.id}`)}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 font-medium text-slate-100">
                      {c.name}
                    </div>
                    <div className="text-[11px] text-slate-500">{scheduleSummary(c)}</div>
                  </td>
                  {scope === 'admin' && <td className="px-4 py-3 text-slate-300">{c.client_name}</td>}
                  <td className="px-4 py-3 text-slate-300">
                    {c.agent_name} <span className="text-slate-500">v{c.agent_version_number}</span>
                  </td>
                  <td className="px-4 py-3">
                    <CampaignStatusBadge status={c.status} />
                    {c.status === 'PAUSED' && c.pause_reason && (
                      <div className="mt-1 max-w-[220px] truncate text-[11px] text-amber-400" title={c.pause_reason}>
                        {c.pause_reason}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <ProgressBar campaign={c} />
                  </td>
                  <td className="px-4 py-3 text-slate-300">
                    {c.stats.answer_rate === null ? '—' : `${Math.round(c.stats.answer_rate * 100)}%`}
                  </td>
                  <td className="px-4 py-3">
                    <ActionButtons campaign={c} busy={busy} run={run} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <CampaignWizardModal
        isOpen={wizardOpen}
        onClose={() => setWizardOpen(false)}
        api={api}
        kind={kind}
        onSaved={(c) => {
          load();
          navigate(`${basePath}/${c.id}`);
        }}
      />
      {scope === 'portal' && <DoNotCallModal isOpen={dncOpen} onClose={() => setDncOpen(false)} scope={scope} />}
    </div>
  );
};

// ---------------------------------------------------------------------------- detail

const RECIPIENT_FILTERS: Array<{ value: string; label: string }> = [
  { value: '', label: 'All recipients' },
  ...Object.entries(RECIPIENT_BADGE).map(([v, b]) => ({ value: v, label: b.label })),
];

const resultText = (r: CampaignRecipient) => {
  const parts: string[] = [];
  for (const [name, value] of Object.entries(r.result?.outputs || {})) {
    if (value !== null && value !== undefined && value !== '') parts.push(`${name.replace(/_/g, ' ')}: ${formatOutputValue(value)}`);
  }
  const lead = r.result?.lead;
  if (lead?.qualification_status) parts.push(lead.qualification_status);
  if (lead?.call_disposition) parts.push(lead.call_disposition);
  for (const a of r.result?.actions || []) parts.push(a.tool.replace(/_/g, ' '));
  return parts.join(' · ');
};

const humanize = (key: string) => key.replace(/_/g, ' ');

/** Everything Choranta learned from one person's call(s): the same data the results webhook sends. */
const RecipientResult: React.FC<{ recipient: CampaignRecipient; callHref: string | null }> = ({ recipient: r, callHref }) => {
  const outputs = Object.entries(r.result?.outputs || {}).filter(([, v]) => v !== null && v !== undefined && v !== '');
  const variables = Object.entries(r.variables || {}).filter(([k]) => k !== 'user_name');
  const lead = r.result?.lead;
  const actions = r.result?.actions || [];
  const field = (label: string, value: React.ReactNode) => (
    <div key={label}>
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-slate-200">{value}</div>
    </div>
  );
  return (
    <div className="space-y-4 text-xs">
      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Call summary</div>
        <QualificationBadge qualification={r.result?.qualification} />
        <p className="text-slate-200">{r.result?.summary || (r.status === 'PENDING' || r.status === 'DIALING' ? 'The call has not finished yet.' : 'No summary for this call.')}</p>
      </div>
      {outputs.length > 0 && (
        <div>
          <div className="mb-2 text-[11px] font-medium text-[#00df8f]">Collected answers</div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">{outputs.map(([k, v]) => field(humanize(k), formatOutputValue(v)))}</div>
        </div>
      )}
      {(lead?.qualification_status || lead?.call_disposition || lead?.next_action) && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {lead?.qualification_status && field('Qualification', lead.qualification_status)}
          {lead?.call_disposition && field('Disposition', lead.call_disposition)}
          {lead?.next_action && field('Next action', lead.next_action)}
        </div>
      )}
      {actions.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Actions taken</div>
          <ul className="space-y-0.5 text-slate-300">
            {actions.map((a, i) => (
              <li key={i}>
                {humanize(a.tool)}
                {Object.keys(a.arguments || {}).length > 0 && (
                  <span className="text-slate-500"> ({Object.entries(a.arguments).map(([k, v]) => `${humanize(k)}: ${formatOutputValue(v)}`).join(', ')})</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {variables.length > 0 && (
        <div>
          <div className="mb-2 text-[11px] font-medium text-slate-400">Submitted details</div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">{variables.map(([k, v]) => field(humanize(k), v))}</div>
        </div>
      )}
      {/* callHref is only set in the client portal, where the WhatsApp thread can be read */}
      {callHref && r.last_call_id && <WhatsAppThread callId={r.last_call_id} />}
      {callHref && r.last_call_id && (
        <Link to={callHref} className="inline-block text-[#00df8f] hover:underline">
          View call transcript &amp; recording →
        </Link>
      )}
    </div>
  );
};

export const CampaignDetail: React.FC<{ scope: CampaignScope; basePath: string }> = ({ scope, basePath }) => {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [recipients, setRecipients] = useState<CampaignRecipient[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editOpen, setEditOpen] = useState(false);
  const [showSecret, setShowSecret] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const pageSize = 50;

  const load = useCallback(async () => {
    const api = campaignsApi(scope);
    try {
      const [c, r] = await Promise.all([
        api.get(id),
        api.recipients(id, { status: statusFilter || undefined, search: search || undefined, skip: page * pageSize, limit: pageSize }),
      ]);
      setCampaign(c);
      setRecipients(r.items);
      setTotal(r.total);
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Could not load the campaign.');
    } finally {
      setLoading(false);
    }
  }, [scope, id, statusFilter, search, page]);

  const { api, busy, run } = useCampaignActions(
    scope,
    (c) => {
      if (!c) navigate(basePath);
      else {
        setCampaign(c);
        load();
      }
    },
    setError
  );

  useEffect(() => {
    const timer = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(timer);
  }, [load, search]);

  const live = campaign ? LIVE.includes(campaign.status) : false;
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [live, load]);

  if (loading) return <LoadingState message="Loading campaign..." />;
  if (!campaign) return <ErrorState message={error || 'Campaign not found.'} onRetry={load} />;

  const s = campaign.stats;
  const cards: Array<[string, string | number, string?]> = [
    ['Recipients', s.total.toLocaleString()],
    ['Pending', (s.pending + s.retry_wait).toLocaleString(), s.retry_wait ? `${s.retry_wait} waiting to retry` : undefined],
    ['On call now', s.dialing],
    ['Answered', s.answered.toLocaleString(), s.answer_rate !== null ? `${Math.round(s.answer_rate * 100)}% answer rate` : undefined],
    ['Not reached', (s.failed + s.skipped).toLocaleString(), s.skipped ? `${s.skipped} skipped` : undefined],
    ['Minutes', s.minutes, `${s.attempts} dials`],
  ];

  return (
    <div className="space-y-6">
      <Link to={basePath} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200">
        <ArrowLeft className="h-3.5 w-3.5" /> {campaign.kind === 'TRIGGER' ? 'All instant outbound' : 'All campaigns'}
      </Link>

      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold text-slate-100">{campaign.name}</h1>
            <CampaignStatusBadge status={campaign.status} />
            <KindBadge campaign={campaign} />
          </div>
          <p className="mt-1 text-sm text-slate-400">
            {scope === 'admin' && `${campaign.client_name} · `}
            {campaign.agent_name} v{campaign.agent_version_number} · from {campaign.caller_numbers.join(', ')} · {scheduleSummary(campaign)} (
            {campaign.timezone}) · {campaign.max_concurrent} at a time
            {campaign.retry_max ? ` · ${campaign.retry_max} retries` : ''}
          </p>
          {campaign.start_at && campaign.status === 'SCHEDULED' && (
            <p className="mt-1 text-xs text-purple-300">Starts {new Date(campaign.start_at + 'Z').toLocaleString()}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <ActionButtons campaign={campaign} busy={busy} run={run} />
          {campaign.kind === 'TRIGGER' && !['STOPPING', 'COMPLETED', 'CANCELLED'].includes(campaign.status) && (
            <Button size="sm" variant="secondary" leftIcon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditOpen(true)}>
              Edit
            </Button>
          )}
          <Button size="sm" variant="secondary" leftIcon={<Download className="h-3.5 w-3.5" />} onClick={() => api.exportCsv(campaign)}>
            Export results
          </Button>
        </div>
      </div>

      {scope === 'admin' && <MockCallOutcomes campaignId={campaign.id} onDone={load} />}

      {campaign.kind === 'TRIGGER' && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-purple-800/40 bg-purple-950/20 p-3 text-xs text-slate-300">
          <span className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-purple-300" />
            Website form submissions sent to the leads API are called within seconds during calling hours.
          </span>
          {scope === 'portal' ? (
            <Link to="/portal/integrations" className="flex items-center gap-1 text-[#00df8f] hover:underline">
              <KeyRound className="h-3.5 w-3.5" /> API keys & website setup
            </Link>
          ) : (
            <span className="text-slate-500">The client connects their website from the portal (API & integrations).</span>
          )}
        </div>
      )}

      {campaign.webhook_url && (
        <div className="space-y-1.5 rounded-lg border border-[#143c49] bg-[#091b22] p-3 text-xs">
          <div className="text-slate-400">
            Results webhook: <span className="font-mono text-slate-200">{campaign.webhook_url}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-slate-400">
            Signing secret:
            <code className="rounded bg-[#06141a] px-1.5 py-0.5 text-slate-200">
              {showSecret ? campaign.webhook_secret : '•••••••••••••••• '}
            </code>
            <button type="button" className="text-[#00df8f] hover:underline" onClick={() => setShowSecret(!showSecret)}>
              {showSecret ? 'Hide' : 'Reveal'}
            </button>
            {showSecret && campaign.webhook_secret && (
              <button
                type="button"
                aria-label="Copy secret"
                className="text-slate-400 hover:text-slate-200"
                onClick={() => navigator.clipboard?.writeText(campaign.webhook_secret || '')}
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            )}
            <button
              type="button"
              className="text-slate-500 hover:text-amber-300"
              onClick={async () => {
                if (!window.confirm('Create a new signing secret? Your receiver must be updated to the new one.')) return;
                try {
                  setCampaign(await api.action(campaign.id, 'webhook-secret'));
                  setShowSecret(true);
                } catch (e: any) {
                  setError(e.message);
                }
              }}
            >
              Rotate
            </button>
          </div>
          <p className="text-slate-500">
            Each request carries <code>X-Choranta-Timestamp</code> and <code>X-Choranta-Signature: sha256=HMAC(secret, timestamp + "." + body)</code>.
          </p>
        </div>
      )}

      {campaign.status === 'PAUSED' && campaign.pause_reason && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-800/50 bg-amber-950/30 p-3 text-xs text-amber-200">
          <Pause className="mt-0.5 h-4 w-4 shrink-0" /> Paused: {campaign.pause_reason}
        </div>
      )}
      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/50 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {cards.map(([label, value, hint]) => (
          <div key={label} className="rounded-lg border border-[#143c49] bg-[#091b22] p-4">
            <div className="text-xs text-slate-500">{label}</div>
            <div className="mt-1 text-xl font-semibold text-slate-100">{value}</div>
            {hint && <div className="mt-0.5 text-[11px] text-slate-500">{hint}</div>}
          </div>
        ))}
      </div>
      <ProgressBar campaign={campaign} />

      {Object.keys(s.collected || {}).length > 0 && (
        <div className="rounded-lg border border-[#143c49] bg-[#091b22] p-4">
          <div className="mb-3 text-xs font-semibold text-slate-300">Collected from answered calls</div>
          <CollectedAnswers collected={s.collected} />
        </div>
      )}

      <div className="flex flex-col gap-3 sm:flex-row">
        <div className="sm:w-64">
          <Input
            placeholder="Search phone or name"
            leftIcon={<Search className="h-4 w-4" />}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
          />
        </div>
        <div className="sm:w-56">
          <Select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(0);
            }}
            options={RECIPIENT_FILTERS}
          />
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-[#143c49]">
        <table className="w-full text-left text-xs">
          <thead className="bg-[#091b22] text-slate-500">
            <tr>
              <th className="px-3 py-2.5 font-medium">Phone</th>
              <th className="px-3 py-2.5 font-medium">Name</th>
              <th className="px-3 py-2.5 font-medium">Status</th>
              <th className="px-3 py-2.5 font-medium">Attempts</th>
              <th className="px-3 py-2.5 font-medium">Outcome</th>
              <th className="px-3 py-2.5 font-medium">Result</th>
            </tr>
          </thead>
          <tbody className="text-slate-300">
            {recipients.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-slate-500">No recipients match.</td>
              </tr>
            )}
            {recipients.map((r) => {
              const b = RECIPIENT_BADGE[r.status];
              return (
                <React.Fragment key={r.id}>
                <tr
                  className="cursor-pointer border-t border-[#102d38] hover:bg-[#0a2028]/60"
                  onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                >
                  <td className="px-3 py-2 font-mono">
                    <ChevronRight className={`mr-1 inline h-3.5 w-3.5 text-slate-500 transition-transform ${expanded === r.id ? 'rotate-90' : ''}`} />
                    {r.phone}
                  </td>
                  <td className="px-3 py-2">
                    {r.name || '—'}
                    {r.source && campaign.kind === 'TRIGGER' && <div className="text-[11px] text-slate-500">{r.source}</div>}
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant={b.variant} size="sm" dot={r.status === 'DIALING'}>
                      {b.label}
                    </Badge>
                    {r.status === 'RETRY_WAIT' && r.next_attempt_at && (
                      <div className="mt-0.5 text-[11px] text-slate-500">
                        at {new Date(r.next_attempt_at + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2">{r.attempts}</td>
                  <td className="px-3 py-2">
                    {r.outcome || '—'}
                    {r.error && (
                      <div className="max-w-[220px] truncate text-[11px] text-slate-500" title={r.error}>
                        {r.error}
                      </div>
                    )}
                  </td>
                  <td className="max-w-[260px] truncate px-3 py-2 text-slate-400" title={resultText(r)}>
                    {resultText(r) || '—'}
                  </td>
                </tr>
                {expanded === r.id && (
                  <tr className="bg-[#06141a]">
                    <td colSpan={6} className="px-4 py-4">
                      <RecipientResult recipient={r} callHref={scope === 'portal' ? `/portal/calls?call=${r.last_call_id}` : null} />
                    </td>
                  </tr>
                )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <CampaignWizardModal
        isOpen={editOpen}
        onClose={() => setEditOpen(false)}
        api={api}
        editCampaign={campaign}
        onSaved={(c) => {
          setCampaign(c);
          load();
        }}
      />

      {total > pageSize && (
        <div className="flex items-center justify-end gap-3 text-xs text-slate-400">
          {page * pageSize + 1}–{Math.min(total, (page + 1) * pageSize)} of {total.toLocaleString()}
          <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <Button size="sm" variant="ghost" disabled={(page + 1) * pageSize >= total} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------- do-not-call


export const DoNotCallModal: React.FC<{ isOpen: boolean; onClose: () => void; scope: CampaignScope; clientId?: string }> = ({
  isOpen,
  onClose,
  scope,
  clientId,
}) => {
  const api = useMemo(() => campaignsApi(scope), [scope]);
  const [entries, setEntries] = useState<DoNotCallEntry[]>([]);
  const [phone, setPhone] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      setEntries(await api.dncList(clientId));
    } catch (e: any) {
      setError(e.message);
    }
  }, [api, clientId]);

  useEffect(() => {
    if (isOpen) load();
  }, [isOpen, load]);

  const add = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.dncAdd(phone, undefined, clientId);
      setPhone('');
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Do-not-call list" description="Campaigns never call these numbers. Callers who ask not to be called are added automatically." maxWidth="lg">
      <div className="space-y-4">
        <div className="flex gap-2">
          <div className="flex-1">
            <Input placeholder="+91 98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
          <Button variant="primary" disabled={!phone.trim()} isLoading={saving} onClick={add}>
            Add
          </Button>
        </div>
        {error && <p className="text-xs text-rose-400">{error}</p>}
        <div className="max-h-72 overflow-y-auto rounded-lg border border-[#143c49]">
          {entries.length === 0 ? (
            <p className="p-4 text-center text-xs text-slate-500">No numbers yet.</p>
          ) : (
            <ul className="divide-y divide-[#102d38] text-xs">
              {entries.map((e) => (
                <li key={e.id} className="flex items-center justify-between px-3 py-2">
                  <span className="font-mono text-slate-200">{e.phone}</span>
                  <span className="text-slate-500">{e.source === 'caller_request' ? 'Caller asked' : 'Added manually'}</span>
                  <button
                    type="button"
                    aria-label={`Remove ${e.phone}`}
                    className="rounded p-1 text-slate-500 hover:text-rose-400"
                    onClick={async () => {
                      await api.dncRemove(e.id);
                      load();
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Modal>
  );
};
