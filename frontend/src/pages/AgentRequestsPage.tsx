import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertTriangle, Inbox, Loader2, Pause, Play, RefreshCw, Wand2, XCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Button } from '../components/common/Button';
import { Badge } from '../components/common/Badge';
import { Modal } from '../components/common/Modal';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { useVoicePreview } from '../components/voice/useVoicePreview';
import {
  AgentRequest,
  agentRequestsService as api,
  REQUEST_STATUS_LABELS,
  REQUEST_STATUS_VARIANT,
} from '../services/agentRequests';

const FILTERS = [
  { value: 'OPEN', label: 'To do' },
  { value: 'COMPLETED', label: 'Done' },
  { value: 'REJECTED', label: 'Declined' },
  { value: '', label: 'All' },
];

/** Admin queue: AI employees clients asked for (name + voice), built here with the agent wizard. */
export const AgentRequestsPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const navigate = useNavigate();
  const [filter, setFilter] = useState('OPEN');
  const [rows, setRows] = useState<AgentRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<AgentRequest | null>(null);
  const [note, setNote] = useState('');
  const preview = useVoicePreview(api.preview);

  const load = useCallback(async () => {
    try {
      setRows(await api.list(filter || undefined));
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Could not load requests.');
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  const build = async (r: AgentRequest) => {
    setBusy(r.id);
    try {
      if (r.status === 'PENDING') await api.start(r.id);
      navigate(`/agents/new?request=${r.id}`);
    } catch (e: any) {
      setError(e.message);
      setBusy(null);
    }
  };

  const reject = async () => {
    if (!rejecting) return;
    setBusy(rejecting.id);
    try {
      await api.reject(rejecting.id, note.trim());
      setRejecting(null);
      setNote('');
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };

  if (rows === null && error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-8">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold text-slate-100">
            <Inbox className="h-6 w-6 text-[#00df8f]" /> Employee Requests
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Paying clients gave their company name, type of business and a name for their AI employee. Build each one with the agent wizard; it opens with these filled in.
          </p>
        </div>
        <Button variant="secondary" leftIcon={<RefreshCw className="h-4 w-4" />} onClick={load}>
          Refresh
        </Button>
      </div>

      <div className="flex w-fit rounded-full bg-[#0a2028] p-0.5">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setFilter(f.value)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${filter === f.value ? 'bg-[#00df8f] text-[#04110c]' : 'text-slate-300 hover:text-slate-100'}`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {(error || preview.error) && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/50 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error || preview.error}
        </div>
      )}

      {rows === null ? (
        <LoadingState message="Loading requests..." />
      ) : rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#143c49] p-10 text-center">
          <Inbox className="mx-auto h-8 w-8 text-slate-500" />
          <p className="mt-3 text-sm text-slate-300">{filter === 'OPEN' ? 'Nothing to build right now' : 'No requests'}</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[#143c49]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[#091b22] text-xs text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">AI employee</th>
                <th className="px-4 py-3 font-medium">Client</th>
                <th className="px-4 py-3 font-medium">Voice</th>
                <th className="px-4 py-3 font-medium">Requested</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const open = r.status === 'PENDING' || r.status === 'IN_PROGRESS';
                return (
                  <tr key={r.id} className="border-t border-[#102d38] align-top">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-100">{r.name}</div>
                      {(r.company_name || r.business_type_label) && (
                        <div className="mt-0.5 text-[11px] text-slate-400">
                          {[r.company_name, r.business_type_label].filter(Boolean).join(' · ')}
                        </div>
                      )}
                      {r.task_labels.length > 0 && (
                        <div className="mt-1 flex max-w-sm flex-wrap gap-1">
                          {r.task_labels.map((t) => (
                            <span key={t} className="rounded bg-[#0a2028] px-1.5 py-0.5 text-[10px] text-slate-300">{t}</span>
                          ))}
                        </div>
                      )}
                      {r.language_labels.length > 0 && (
                        <div className="mt-1 text-[11px] text-slate-400">Speaks {r.language_labels.join(', ')}</div>
                      )}
                      {r.notes && <div className="mt-0.5 max-w-sm whitespace-pre-line text-[11px] text-slate-400">{r.notes}</div>}
                      {r.admin_note && <div className="mt-0.5 max-w-xs text-[11px] text-rose-300">Declined: {r.admin_note}</div>}
                    </td>
                    <td className="px-4 py-3">
                      <Link to={`/clients/${r.client_id}`} className="text-slate-200 hover:underline">{r.client_name}</Link>
                      <div className="font-mono text-[11px] text-[#00df8f]">{r.client_code}</div>
                    </td>
                    <td className="px-4 py-3">
                      {!r.voice_id ? (
                        <span className="text-xs text-slate-500">Pick in wizard</span>
                      ) : (
                      <button
                        type="button"
                        onClick={() => preview.toggle(r.voice_id!)}
                        className="inline-flex items-center gap-1.5 rounded-full bg-[#0a2028] px-2.5 py-1 text-xs text-slate-200 hover:bg-[#0f3340]"
                      >
                        {preview.loading === r.voice_id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : preview.playing === r.voice_id ? (
                          <Pause className="h-3 w-3" />
                        ) : (
                          <Play className="h-3 w-3" />
                        )}
                        {r.voice_name}
                      </button>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">{new Date(r.created_at).toLocaleString('en-IN')}</td>
                    <td className="px-4 py-3">
                      <Badge variant={REQUEST_STATUS_VARIANT[r.status]} size="sm">{REQUEST_STATUS_LABELS[r.status]}</Badge>
                      {r.agent_id && (
                        <Link to={`/agents/${r.agent_id}`} className="mt-1 block text-[11px] text-[#00df8f] hover:underline">
                          {r.agent_name}
                        </Link>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {open && isAdmin && (
                        <div className="flex flex-wrap justify-end gap-1.5">
                          <Button size="sm" variant="primary" isLoading={busy === r.id} leftIcon={<Wand2 className="h-3.5 w-3.5" />} onClick={() => build(r)}>
                            {r.status === 'IN_PROGRESS' ? 'Continue' : 'Build agent'}
                          </Button>
                          <Button size="sm" variant="ghost" leftIcon={<XCircle className="h-3.5 w-3.5" />} onClick={() => setRejecting(r)}>
                            Decline
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        isOpen={rejecting !== null}
        onClose={() => setRejecting(null)}
        title={`Decline ${rejecting?.name ?? ''}`}
        description="The client sees this reason in their portal."
      >
        <div className="space-y-3 text-xs">
          <textarea
            rows={3}
            className="w-full rounded border border-[#232736] bg-[#10121a] p-2 text-slate-100"
            placeholder="e.g. Duplicate request, or please choose a different name"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setRejecting(null)}>Back</Button>
            <Button variant="primary" disabled={!note.trim()} isLoading={busy === rejecting?.id} onClick={reject}>
              Decline request
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
