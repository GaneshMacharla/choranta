import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2, Download, FileSpreadsheet, Globe, Plus, Search, Trash2, Upload } from 'lucide-react';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { Input } from '../common/Input';
import { Select } from '../common/Select';
import { MultiSelect } from '../common/MultiSelect';
import { clientsService } from '../../services/clients';
import { timezoneOptions } from '../../constants/timezones';
import {
  Campaign,
  CampaignKind,
  CampaignOptions,
  CampaignsApi,
  CsvPreview,
  DAY_LABELS,
  LeadOption,
  SAMPLE_CSV,
  minutesToTime,
  timeToMinutes,
} from '../../services/campaigns';

interface CampaignWizardModalProps {
  isOpen: boolean;
  onClose: () => void;
  api: CampaignsApi;
  onSaved: (campaign: Campaign) => void;
  /** Admin only: preselect a client */
  defaultClientId?: string;
  /** Edit an existing website-lead campaign instead of creating one */
  editCampaign?: Campaign | null;
  /** New campaigns: BULK (Campaigns tab) or TRIGGER (Instant Outbound tab) */
  kind?: CampaignKind;
}

const STEPS = [
  { id: 'agent', title: 'Agent' },
  { id: 'recipients', title: 'Recipients' },
  { id: 'schedule', title: 'Schedule' },
  { id: 'review', title: 'Review & Launch' },
] as const;

const CUSTOM_NAME = '__custom__';
const NAME_PRESETS: Record<CampaignKind, string[]> = {
  TRIGGER: ['Website enquiries', 'New lead callback', 'Missed call callback', 'Form submission follow-up', 'Demo request'],
  BULK: ['Lead follow-up', 'Payment reminder', 'Appointment reminder', 'Feedback survey', 'Product promotion', 'Event invitation', 'Renewal reminder'],
};

const EARLIEST = 9 * 60;
const LATEST = 21 * 60;
const DAY_END = '24:00';
const ALL_DAYS = [0, 1, 2, 3, 4, 5, 6];
const DEFAULT_WINDOWS: WindowDraft[] = [{ start: '10:00', end: '19:00' }];
const DEFAULT_DAYS = [0, 1, 2, 3, 4, 5];
const AVG_CALL_MIN = 2;

interface WindowDraft {
  start: string;
  end: string;
}

const panel = 'rounded-lg border border-[#143c49] bg-[#06141a]/60 p-4';
const pill = (active: boolean) =>
  `rounded-full px-3 py-1 text-xs font-medium transition-colors ${
    active ? 'bg-[#00df8f] text-[#04110c]' : 'text-slate-300 hover:text-slate-100'
  }`;

export const CampaignWizardModal: React.FC<CampaignWizardModalProps> = ({
  isOpen,
  onClose,
  api,
  onSaved,
  defaultClientId,
  editCampaign,
  kind: initialKind = 'BULK',
}) => {
  const isAdmin = api.scope === 'admin';
  const isEdit = !!editCampaign;
  const [kind, setKind] = useState<CampaignKind>(initialKind);
  const [webhookUrl, setWebhookUrl] = useState('');
  const prefill = useRef<Campaign | null>(null);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<'draft' | 'launch' | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [recipientsImported, setRecipientsImported] = useState(false);

  // Step 1: agent & connection
  const [clients, setClients] = useState<Array<{ id: string; name: string }>>([]);
  const [clientId, setClientId] = useState(defaultClientId || '');
  const [options, setOptions] = useState<CampaignOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [name, setName] = useState('');
  const [customName, setCustomName] = useState(false);
  const [agentId, setAgentId] = useState('');
  const [versionId, setVersionId] = useState('');
  const [connection, setConnection] = useState('exotel');
  const [numberMode, setNumberMode] = useState<'number' | 'group'>('number');
  const [numberIds, setNumberIds] = useState<string[]>([]);

  // Step 2: recipients
  const [source, setSource] = useState<'csv' | 'leads'>('csv');
  const [csvText, setCsvText] = useState('');
  const [csvFileName, setCsvFileName] = useState('');
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const [leadSearch, setLeadSearch] = useState('');
  const [leads, setLeads] = useState<LeadOption[]>([]);
  const [leadTotal, setLeadTotal] = useState(0);
  const [leadsLoading, setLeadsLoading] = useState(false);
  const [selectedLeads, setSelectedLeads] = useState<Set<string>>(new Set());

  // Step 3: schedule
  const [startMode, setStartMode] = useState<'now' | 'later'>('now');
  const [startAt, setStartAt] = useState('');
  const [timezone, setTimezone] = useState('Asia/Kolkata');
  const [windows, setWindows] = useState<WindowDraft[]>([{ start: '10:00', end: '19:00' }]);
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4, 5]);
  const [allDay, setAllDay] = useState(false);
  const [maxConcurrent, setMaxConcurrent] = useState(1);
  const [retryEnabled, setRetryEnabled] = useState(true);
  const [retryMax, setRetryMax] = useState(2);
  const [retryIntervals, setRetryIntervals] = useState<number[]>([30, 60]);

  // Step 4: review
  const [purpose, setPurpose] = useState<'SERVICE' | 'PROMOTIONAL'>('SERVICE');
  const [consent, setConsent] = useState(false);
  const [details, setDetails] = useState<Record<string, string>>({});

  const effectiveClientId = isAdmin ? clientId : options?.client_id || '';

  useEffect(() => {
    if (!isOpen) return;
    setStep(0);
    setError(null);
    setCreatedId(null);
    setRecipientsImported(false);
    prefill.current = editCampaign || null;
    setCustomName(!!editCampaign && !NAME_PRESETS[editCampaign.kind].includes(editCampaign.name));
    if (!editCampaign) {
      chooseKind(initialKind);
      setName('');
      setWebhookUrl('');
      setConsent(false);
      setDetails({});
    }
    if (editCampaign) {
      const c = editCampaign;
      setKind(c.kind);
      setName(c.name);
      setPurpose(c.purpose);
      setConnection(c.provider || 'exotel');
      setWindows(c.windows.map((w) => ({ start: minutesToTime(w.start_min), end: minutesToTime(w.end_min) })));
      setDays(c.days);
      setAllDay(c.kind === 'TRIGGER' && c.days.length === 7 && c.windows.length === 1 && c.windows[0].start_min === 0 && c.windows[0].end_min >= 1439);
      setMaxConcurrent(c.max_concurrent);
      setRetryEnabled(c.retry_max > 0);
      setRetryMax(Math.max(1, c.retry_max));
      setRetryIntervals(c.retry_intervals_min.length ? c.retry_intervals_min : [5, 30]);
      setWebhookUrl(c.webhook_url || '');
      setDetails(c.variables || {});
      setConsent(true);
      if (isAdmin) setClientId(c.client_id);
    }
    if (isAdmin) {
      clientsService
        .list({ limit: 100 })
        .then((res) => setClients(res.items.map((c) => ({ id: c.id, name: c.name }))))
        .catch(() => setClients([]));
    } else {
      loadOptions();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  useEffect(() => {
    if (isOpen && isAdmin && clientId) loadOptions(clientId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  const loadOptions = async (forClient?: string) => {
    setOptionsLoading(true);
    try {
      const opts = await api.options(forClient);
      setOptions(opts);
      const editing = prefill.current;
      setTimezone(editing?.timezone || opts.timezone || 'Asia/Kolkata');
      setAgentId(editing?.agent_id || '');
      setVersionId(editing?.agent_version_id || '');
      setNumberIds(editing ? editing.caller_number_ids : opts.numbers.filter((n) => n.usable).slice(0, 1).map((n) => n.id));
      setSelectedLeads(new Set());
      setLeads([]);
    } catch (e: any) {
      setError(e.message || 'Could not load agents and numbers.');
    } finally {
      setOptionsLoading(false);
    }
  };

  const agent = options?.agents.find((a) => a.id === agentId);
  const campaignInputs = agent?.versions.find((v) => v.id === versionId)?.campaign_inputs || [];

  // Leads for the picker
  useEffect(() => {
    if (!isOpen || step !== 1 || source !== 'leads' || !effectiveClientId) return;
    const timer = setTimeout(async () => {
      setLeadsLoading(true);
      try {
        const res = await api.leads({ client_id: effectiveClientId, search: leadSearch, limit: 200 });
        setLeads(res.items);
        setLeadTotal(res.total);
      } catch {
        setLeads([]);
      } finally {
        setLeadsLoading(false);
      }
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, step, source, leadSearch, effectiveClientId]);

  const handleFile = (file: File) => {
    setCsvFileName(file.name);
    setPreview(null);
    const reader = new FileReader();
    reader.onload = async () => {
      const text = String(reader.result || '');
      setCsvText(text);
      setPreviewing(true);
      setError(null);
      try {
        setPreview(await api.previewCsv(text));
      } catch (e: any) {
        setError(e.message || 'Could not read the CSV file.');
      } finally {
        setPreviewing(false);
      }
    };
    reader.readAsText(file);
  };

  const downloadSample = () => {
    const url = URL.createObjectURL(new Blob([SAMPLE_CSV], { type: 'text/csv' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'campaign-recipients-sample.csv';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const isTrigger = kind === 'TRIGGER';
  const recipientCount = source === 'csv' ? preview?.valid || 0 : selectedLeads.size;
  const setRoundTheClock = (on: boolean) => {
    setAllDay(on);
    setWindows(on ? [{ start: '00:00', end: DAY_END }] : DEFAULT_WINDOWS);
    setDays(on ? ALL_DAYS : DEFAULT_DAYS);
  };

  const chooseKind = (next: CampaignKind) => {
    setKind(next);
    setRoundTheClock(next === 'TRIGGER');
    setRetryEnabled(true);
    setRetryMax(2);
    setRetryIntervals(next === 'TRIGGER' ? [5, 30] : [30, 60]);
  };
  const cap = options?.concurrency_cap ?? null;
  const windowMinutes = windows.reduce((sum, w) => sum + Math.max(0, timeToMinutes(w.end) - timeToMinutes(w.start)), 0);

  const stepError = useMemo((): string | null => {
    switch (STEPS[step].id) {
      case 'agent':
        if (!name.trim()) return isTrigger ? 'Enter a name.' : 'Enter a campaign name.';
        if (isAdmin && !clientId) return 'Choose a client.';
        if (!agentId || !versionId) return 'Choose an AI Employee and version.';
        if (numberIds.length === 0) return 'Choose at least one phone number to call from.';
        for (const input of campaignInputs) {
          if (input.required && !details[input.name]?.trim()) return `Enter ${input.description.toLowerCase()}.`;
        }
        return null;
      case 'recipients':
        if (isTrigger) return null;
        if (recipientCount === 0) return source === 'csv' ? 'Upload a CSV with at least one valid number.' : 'Select at least one lead.';
        return null;
      case 'schedule':
        for (const w of windows) {
          const s = timeToMinutes(w.start);
          const e = timeToMinutes(w.end);
          if (s >= e) return 'Each calling window must end after it starts.';
          if (!isTrigger && (s < EARLIEST || e > LATEST)) return 'Calling windows must be between 09:00 and 21:00.';
        }
        if (days.length === 0) return 'Choose at least one calling day.';
        if (maxConcurrent < 1) return 'Concurrent calls must be at least 1.';
        if (cap !== null && maxConcurrent > cap) return `The plan allows up to ${cap} concurrent campaign call(s).`;
        if (webhookUrl.trim() && !webhookUrl.trim().startsWith('https://')) return 'The results webhook URL must start with https://';
        if (startMode === 'later' && !isTrigger) {
          if (!startAt) return 'Choose when to start.';
          if (new Date(startAt).getTime() < Date.now()) return 'The start time is in the past.';
        }
        return null;
      default:
        return null;
    }
  }, [step, name, isAdmin, clientId, agentId, versionId, numberIds, campaignInputs, details, recipientCount, source, windows, days, maxConcurrent, cap, startMode, startAt, isTrigger, webhookUrl]);

  const settingsPayload = () => ({
    name: name.trim(),
    purpose,
    kind,
    agent_id: agentId,
    agent_version_id: versionId,
    provider: connection,
    caller_number_ids: numberIds,
    timezone,
    windows: windows.map((w) => ({ start_min: timeToMinutes(w.start), end_min: timeToMinutes(w.end) })),
    days: [...days].sort(),
    start_at: startMode === 'later' && startAt && !isTrigger ? new Date(startAt).toISOString() : null,
    max_concurrent: maxConcurrent,
    retry_max: retryEnabled ? retryMax : 0,
    retry_intervals_min: retryEnabled ? retryIntervals.slice(0, Math.max(1, retryMax)) : [],
    retry_on: retryEnabled ? ['no-answer', 'busy', 'failed'] : [],
    webhook_url: webhookUrl.trim() || (isEdit ? '' : null),
    // Only the selected agent's campaign details (switching agents leaves stale ones behind)
    variables: Object.fromEntries(
      campaignInputs.map((input) => [input.name, (details[input.name] || '').trim()]).filter(([, v]) => v),
    ),
  });

  const save = async (mode: 'draft' | 'launch') => {
    setSaving(mode);
    setError(null);
    try {
      let campaign: Campaign;
      if (editCampaign) {
        const { kind: _kind, ...changes } = settingsPayload();
        campaign = await api.update(editCampaign.id, changes);
        onSaved(campaign);
        onClose();
        return;
      }
      if (createdId) {
        campaign = await api.update(createdId, settingsPayload());
      } else {
        campaign = await api.create({ ...settingsPayload(), client_id: isAdmin ? clientId : undefined });
        setCreatedId(campaign.id);
      }
      if (!recipientsImported && !isTrigger) {
        if (source === 'csv') await api.importCsv(campaign.id, csvText);
        else await api.importLeads(campaign.id, Array.from(selectedLeads));
        setRecipientsImported(true);
      }
      if (mode === 'launch') campaign = await api.launch(campaign.id, consent);
      else campaign = await api.get(campaign.id);
      onSaved(campaign);
      onClose();
    } catch (e: any) {
      setError(e.message || 'Could not save the campaign.');
    } finally {
      setSaving(null);
    }
  };

  const etaText = () => {
    if (!recipientCount) return '—';
    const minutes = Math.ceil(recipientCount / Math.max(1, maxConcurrent)) * AVG_CALL_MIN;
    const perDay = windowMinutes || 1;
    if (minutes <= perDay) return minutes < 60 ? `about ${minutes} min` : `about ${(minutes / 60).toFixed(1)} h`;
    return `about ${Math.ceil(minutes / perDay)} calling day(s)`;
  };

  // ------------------------------------------------------------------ steps

  const renderAgent = () => (
    <div className="space-y-5">
      <div className="space-y-2">
        <Select
          label={isTrigger ? 'Name' : 'Campaign name'}
          required
          placeholder={isTrigger ? 'Select a name' : 'Select a campaign name'}
          value={customName ? CUSTOM_NAME : NAME_PRESETS[kind].includes(name) ? name : ''}
          onChange={(e) => {
            const v = e.target.value;
            setCustomName(v === CUSTOM_NAME);
            setName(v === CUSTOM_NAME ? '' : v);
          }}
          options={[...NAME_PRESETS[kind].map((n) => ({ value: n, label: n })), { value: CUSTOM_NAME, label: 'Custom…' }]}
        />
        {customName && (
          <Input
            autoFocus
            placeholder={isTrigger ? 'e.g. Website enquiries' : 'Enter campaign name'}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        )}
      </div>

      {isAdmin && (
        <Select
          label="Client"
          required
          placeholder="Select a client"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          options={clients.map((c) => ({ value: c.id, label: c.name }))}
        />
      )}

      <div className="space-y-1.5">
        <label className="block text-xs font-medium text-slate-300">
          Select agent <span className="text-red-400">*</span>
        </label>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Select
            placeholder={optionsLoading ? 'Loading...' : options && options.agents.length === 0 ? 'No published agents' : 'Select an agent'}
            value={agentId}
            disabled={!options || options.agents.length === 0}
            onChange={(e) => {
              setAgentId(e.target.value);
              const picked = options?.agents.find((a) => a.id === e.target.value);
              setVersionId(picked?.versions[0]?.id || '');
            }}
            options={(options?.agents || []).map((a) => ({ value: a.id, label: a.name }))}
          />
          <Select
            placeholder="Version"
            value={versionId}
            disabled={!agent}
            onChange={(e) => setVersionId(e.target.value)}
            options={(agent?.versions || []).map((v, i) => ({
              value: v.id,
              label: `v${v.version_number}${i === 0 ? ' (latest)' : ''}`,
            }))}
          />
        </div>
        {options && options.agents.length === 0 && (
          <p className="text-xs text-amber-400">Publish an AI Employee before creating a campaign.</p>
        )}
      </div>

      {campaignInputs.length > 0 && (
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-slate-300">Campaign details</label>
          <p className="text-xs text-slate-500">The AI Employee tells every person called about these, and answers questions from them only.</p>
          <div className={`${panel} grid grid-cols-1 gap-4 sm:grid-cols-2`}>
            {campaignInputs.map((input) => (
              <Input
                key={input.name}
                id={`campaign-${input.name}`}
                label={input.description}
                required={input.required}
                placeholder={input.example ? `e.g. ${input.example}` : undefined}
                value={details[input.name] || ''}
                onChange={(e) => setDetails((d) => ({ ...d, [input.name]: e.target.value }))}
              />
            ))}
          </div>
        </div>
      )}

      <div className="space-y-1.5">
        <label className="block text-xs font-medium text-slate-300">
          Connections <span className="text-red-400">*</span>
        </label>
        <div className={`${panel} grid grid-cols-1 gap-4 sm:grid-cols-2`}>
          <Select
            label="Connection"
            value={connection}
            onChange={(e) => setConnection(e.target.value)}
            options={(options?.connections || [{ id: 'exotel', name: 'Exotel' }]).map((c) => ({ value: c.id, label: c.name }))}
          />
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-300">Phone numbers</span>
              <div className="flex rounded-full bg-[#0a2028] p-0.5">
                <button type="button" className={pill(numberMode === 'number')} onClick={() => setNumberMode('number')}>
                  By number
                </button>
                <button type="button" className={`${pill(false)} cursor-not-allowed opacity-50`} title="Number groups are coming soon" disabled>
                  By group
                </button>
              </div>
            </div>
            <MultiSelect
              placeholder={!connection ? 'Select a connection first' : 'Select phone numbers'}
              disabled={!connection || !options}
              value={numberIds}
              onChange={setNumberIds}
              options={(options?.numbers || []).map((n) => ({
                value: n.id,
                label: n.phone_number,
                disabled: !n.usable,
                hint: n.usable ? undefined : n.reason || 'Unavailable',
              }))}
              helperText={numberIds.length > 1 ? 'Calls rotate across the selected numbers.' : undefined}
            />
          </div>
        </div>
        {options && options.numbers.length === 0 && (
          <p className="text-xs text-amber-400">This client has no phone numbers. Buy a number before running a campaign.</p>
        )}
      </div>
    </div>
  );

  const renderLeadSource = () => (
    <div className="space-y-4 text-sm text-slate-300">
      <div className={`${panel} flex items-start gap-3`}>
        <Globe className="mt-0.5 h-5 w-5 shrink-0 text-[#00df8f]" />
        <div className="space-y-2">
          <p className="font-medium text-slate-100">Leads arrive from your website</p>
          <p className="text-xs text-slate-400">
            When someone submits your website form, your website's server sends it to Choranta's leads API with your API key.
            The AI Employee calls them within seconds during calling hours; submissions outside the hours are called when the
            window opens. Every form field (e.g. <code>course_enquired</code>) is passed to the agent as a variable.
          </p>
          <p className="text-xs text-slate-400">
            {isAdmin
              ? "The client creates an API key and finds the connection guide in their portal under API & integrations."
              : 'After launching, create an API key and follow the guide under API & integrations.'}
          </p>
        </div>
      </div>
      <p className="text-xs text-slate-500">
        Each submission must include the person's consent to be called. The same number submitted again within 24 hours is
        ignored, and numbers on your do-not-call list are never called.
      </p>
    </div>
  );

  const renderRecipients = () => (
    <div className="space-y-4">
      <div className="flex w-fit rounded-full bg-[#0a2028] p-0.5">
        <button type="button" className={pill(source === 'csv')} onClick={() => setSource('csv')}>
          Upload CSV
        </button>
        <button type="button" className={pill(source === 'leads')} onClick={() => setSource('leads')}>
          Pick leads
        </button>
      </div>

      {source === 'csv' ? (
        <div className="space-y-4">
          <div
            className={`${panel} flex flex-col items-center gap-3 border-dashed py-8 text-center`}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const file = e.dataTransfer.files?.[0];
              if (file) handleFile(file);
            }}
          >
            <FileSpreadsheet className="h-8 w-8 text-[#00df8f]" />
            <div className="text-sm text-slate-200">{csvFileName || 'Drop a CSV file here'}</div>
            <p className="max-w-md text-xs text-slate-400">
              One column must hold the phone number (<code>phone</code>, <code>mobile</code> or <code>number</code>). A{' '}
              <code>name</code> column and every other column are passed to the agent as variables, e.g.{' '}
              <code>{'{{course_enquired}}'}</code>.
            </p>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" leftIcon={<Upload className="h-3.5 w-3.5" />} onClick={() => fileInput.current?.click()}>
                Choose file
              </Button>
              <Button variant="ghost" size="sm" leftIcon={<Download className="h-3.5 w-3.5" />} onClick={downloadSample}>
                Sample CSV
              </Button>
            </div>
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFile(file);
                e.target.value = '';
              }}
            />
          </div>

          {previewing && <p className="text-xs text-slate-400">Checking the file...</p>}
          {preview && (
            <div className={`${panel} space-y-3`}>
              <div className="flex flex-wrap gap-4 text-xs">
                <span className="text-[#00df8f]">{preview.valid.toLocaleString()} valid</span>
                {preview.invalid_count > 0 && <span className="text-rose-400">{preview.invalid_count} invalid</span>}
                {preview.duplicates > 0 && <span className="text-amber-400">{preview.duplicates} duplicates removed</span>}
                {preview.phone_column && <span className="text-slate-400">Phone column: {preview.phone_column}</span>}
              </div>
              {preview.variable_names.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
                  Variables for the agent:
                  {preview.variable_names.map((v) => (
                    <code key={v} className="rounded bg-[#0a2028] px-1.5 py-0.5 text-[#00df8f]">{`{{${v}}}`}</code>
                  ))}
                </div>
              )}
              <table className="w-full text-left text-xs">
                <thead className="text-slate-500">
                  <tr>
                    <th className="py-1 pr-3 font-medium">Phone</th>
                    <th className="py-1 pr-3 font-medium">Name</th>
                    <th className="py-1 font-medium">Variables</th>
                  </tr>
                </thead>
                <tbody className="text-slate-300">
                  {preview.sample.map((r) => (
                    <tr key={r.phone} className="border-t border-[#102d38]">
                      <td className="py-1 pr-3 font-mono">{r.phone}</td>
                      <td className="py-1 pr-3">{r.name || '—'}</td>
                      <td className="truncate py-1 text-slate-400">
                        {Object.entries(r.variables)
                          .filter(([k]) => k !== 'user_name')
                          .map(([k, v]) => `${k}: ${v}`)
                          .join(' · ') || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.invalid.length > 0 && (
                <details className="text-xs text-slate-400">
                  <summary className="cursor-pointer text-rose-300">Rows that will be skipped</summary>
                  <ul className="mt-1 space-y-0.5">
                    {preview.invalid.slice(0, 10).map((r, i) => (
                      <li key={i}>
                        Line {r.line}: "{r.value}" — {r.reason}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <Input
            placeholder="Search leads by name, phone or source"
            leftIcon={<Search className="h-4 w-4" />}
            value={leadSearch}
            onChange={(e) => setLeadSearch(e.target.value)}
          />
          <div className="max-h-72 overflow-y-auto rounded-lg border border-[#143c49]">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-[#091b22] text-slate-500">
                <tr>
                  <th className="w-8 px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label="Select all"
                      checked={leads.length > 0 && leads.every((l) => selectedLeads.has(l.id))}
                      onChange={(e) => {
                        const next = new Set(selectedLeads);
                        leads.forEach((l) => (e.target.checked ? next.add(l.id) : next.delete(l.id)));
                        setSelectedLeads(next);
                      }}
                    />
                  </th>
                  <th className="px-2 py-2 font-medium">Name</th>
                  <th className="px-2 py-2 font-medium">Phone</th>
                  <th className="px-2 py-2 font-medium">Source</th>
                  <th className="px-2 py-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="text-slate-300">
                {leadsLoading && (
                  <tr>
                    <td colSpan={5} className="px-3 py-4 text-center text-slate-500">Loading leads...</td>
                  </tr>
                )}
                {!leadsLoading && leads.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-3 py-4 text-center text-slate-500">No leads found.</td>
                  </tr>
                )}
                {!leadsLoading &&
                  leads.map((l) => {
                    const dnc = l.call_disposition === 'DO_NOT_CALL';
                    return (
                      <tr key={l.id} className={`border-t border-[#102d38] ${dnc ? 'opacity-50' : ''}`}>
                        <td className="px-3 py-1.5">
                          <input
                            type="checkbox"
                            aria-label={`Select ${l.name}`}
                            disabled={dnc}
                            checked={selectedLeads.has(l.id)}
                            onChange={(e) => {
                              const next = new Set(selectedLeads);
                              if (e.target.checked) next.add(l.id);
                              else next.delete(l.id);
                              setSelectedLeads(next);
                            }}
                          />
                        </td>
                        <td className="px-2 py-1.5">{l.name}</td>
                        <td className="px-2 py-1.5 font-mono">{l.phone}</td>
                        <td className="px-2 py-1.5 text-slate-400">{l.lead_source || '—'}</td>
                        <td className="px-2 py-1.5 text-slate-400">{dnc ? 'Do not call' : l.status || '—'}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-slate-400">
            {selectedLeads.size} selected{leadTotal > leads.length ? ` · showing ${leads.length} of ${leadTotal}; search to find more` : ''}
          </p>
        </div>
      )}
    </div>
  );

  const renderSchedule = () => (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {isTrigger ? (
          <div className="space-y-1.5 text-xs text-slate-400">
            <span className="block font-medium text-slate-300">Start</span>
            Always on once launched. Pause it any time.
          </div>
        ) : (
        <div className="space-y-1.5">
          <span className="block text-xs font-medium text-slate-300">Start</span>
          <div className="flex w-fit rounded-full bg-[#0a2028] p-0.5">
            <button type="button" className={pill(startMode === 'now')} onClick={() => setStartMode('now')}>
              When launched
            </button>
            <button type="button" className={pill(startMode === 'later')} onClick={() => setStartMode('later')}>
              Later
            </button>
          </div>
          {startMode === 'later' && (
            <input
              type="datetime-local"
              aria-label="Start at"
              value={startAt}
              onChange={(e) => setStartAt(e.target.value)}
              className="mt-2 w-full rounded-md border border-[#153945] bg-[#06141a] px-3 py-2 text-sm text-slate-100 [color-scheme:dark]"
            />
          )}
        </div>
        )}
        <Select
          label="Timezone"
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
          options={timezoneOptions(timezone)}
          helperText="Calling windows use this timezone."
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="block text-xs font-medium text-slate-300">Calling windows</span>
          {isTrigger && (
            <label className="flex cursor-pointer items-center gap-2 text-xs text-slate-300">
              <input type="checkbox" className="accent-[#00df8f]" checked={allDay} onChange={(e) => setRoundTheClock(e.target.checked)} />
              Call 24/7
            </label>
          )}
        </div>
        {allDay ? (
          <p className={`${panel} text-xs text-slate-300`}>
            Every day, around the clock: each lead is called within seconds of submitting the form, whatever the time.
          </p>
        ) : (
        <>
        {windows.map((w, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              type="time"
              aria-label="Window start"
              value={w.start}
              min={isTrigger ? undefined : '09:00'}
              max={isTrigger ? undefined : '21:00'}
              onChange={(e) => setWindows(windows.map((x, j) => (j === i ? { ...x, start: e.target.value } : x)))}
              className="rounded-md border border-[#153945] bg-[#06141a] px-3 py-1.5 text-sm text-slate-100 [color-scheme:dark]"
            />
            <span className="text-xs text-slate-500">to</span>
            <input
              type="time"
              aria-label="Window end"
              value={w.end}
              min={isTrigger ? undefined : '09:00'}
              max={isTrigger ? undefined : '21:00'}
              onChange={(e) => setWindows(windows.map((x, j) => (j === i ? { ...x, end: e.target.value } : x)))}
              className="rounded-md border border-[#153945] bg-[#06141a] px-3 py-1.5 text-sm text-slate-100 [color-scheme:dark]"
            />
            {windows.length > 1 && (
              <button
                type="button"
                aria-label="Remove window"
                className="rounded p-1 text-slate-500 hover:text-rose-400"
                onClick={() => setWindows(windows.filter((_, j) => j !== i))}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        ))}
        {windows.length < 3 && (
          <button
            type="button"
            className="flex items-center gap-1 text-xs text-[#00df8f] hover:underline"
            onClick={() => setWindows([...windows, { start: '17:00', end: '20:00' }])}
          >
            <Plus className="h-3.5 w-3.5" /> Add window
          </button>
        )}
        <div className="flex flex-wrap gap-1.5 pt-1">
          {DAY_LABELS.map((label, d) => {
            const on = days.includes(d);
            return (
              <button
                key={label}
                type="button"
                onClick={() => setDays(on ? days.filter((x) => x !== d) : [...days, d])}
                className={`rounded-md border px-2.5 py-1 text-xs ${
                  on ? 'border-[#00df8f] bg-[#00df8f]/10 text-[#00df8f]' : 'border-[#153945] text-slate-400'
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
        <p className="text-xs text-slate-500">
          {isTrigger
            ? 'Leads submitted outside the window are called when it next opens.'
            : 'Calls are only placed between 09:00 and 21:00. Paused outside the window, they resume in the next one.'}
        </p>
        </>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input
          label="Max concurrent calls"
          type="number"
          min={1}
          max={cap ?? 100}
          value={maxConcurrent}
          onChange={(e) => setMaxConcurrent(Math.max(1, parseInt(e.target.value || '1', 10)))}
          helperText={cap !== null ? `Plan limit: ${cap} (one line kept free for incoming calls)` : 'The next call starts as soon as one ends.'}
        />
        <div className="space-y-1.5">
          <label className="flex items-center gap-2 text-xs font-medium text-slate-300">
            <input type="checkbox" checked={retryEnabled} onChange={(e) => setRetryEnabled(e.target.checked)} />
            Retry unanswered, busy and failed calls
          </label>
          {retryEnabled && (
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <select
                aria-label="Retries"
                value={retryMax}
                onChange={(e) => {
                  const n = parseInt(e.target.value, 10);
                  setRetryMax(n);
                  setRetryIntervals(Array.from({ length: n }, (_, i) => retryIntervals[i] ?? 60 * (i + 1)));
                }}
                className="rounded-md border border-[#153945] bg-[#06141a] px-2 py-1 text-slate-100"
              >
                {[1, 2, 3].map((n) => (
                  <option key={n} value={n}>
                    {n} {n === 1 ? 'retry' : 'retries'}
                  </option>
                ))}
              </select>
              after
              {retryIntervals.slice(0, retryMax).map((m, i) => (
                <span key={i} className="flex items-center gap-1">
                  <input
                    type="number"
                    aria-label={`Retry ${i + 1} delay in minutes`}
                    min={5}
                    max={1440}
                    value={m}
                    onChange={(e) =>
                      setRetryIntervals(retryIntervals.map((x, j) => (j === i ? Math.max(5, parseInt(e.target.value || '5', 10)) : x)))
                    }
                    className="w-16 rounded-md border border-[#153945] bg-[#06141a] px-2 py-1 text-slate-100"
                  />
                  min{i < retryMax - 1 ? ',' : ''}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <Input
        label="Results webhook (optional)"
        placeholder="https://your-crm.example.com/choranta-results"
        value={webhookUrl}
        onChange={(e) => setWebhookUrl(e.target.value)}
        helperText="After each person's calls finish, Choranta POSTs the outcome, summary and collected answers here (signed with a secret shown on the campaign page)."
      />
    </div>
  );

  const renderReview = () => {
    const numbers = options?.numbers.filter((n) => numberIds.includes(n.id)).map((n) => n.phone_number) || [];
    const rows: Array<[string, string]> = [
      ['Campaign', name],
      ...(isAdmin ? ([['Client', clients.find((c) => c.id === clientId)?.name || '']] as Array<[string, string]>) : []),
      ['AI Employee', `${agent?.name || ''} · v${agent?.versions.find((v) => v.id === versionId)?.version_number ?? ''}`],
      ...campaignInputs
        .filter((input) => details[input.name]?.trim())
        .map((input) => [input.description, details[input.name].trim()] as [string, string]),
      ['Calling from', `${numbers.join(', ')} (${connection === 'exotel' ? 'Exotel' : connection})`],
      isTrigger
        ? ['Recipients', 'Website form submissions (leads API), called within seconds']
        : ['Recipients', `${recipientCount.toLocaleString()} ${source === 'csv' ? `from ${csvFileName}` : 'leads'}`],
      ['Start', isTrigger ? 'Always on' : startMode === 'now' ? 'As soon as launched' : new Date(startAt).toLocaleString()],
      [
        'Windows',
        allDay
          ? '24/7, every day'
          : `${windows.map((w) => `${w.start}–${w.end}`).join(', ')} · ${[...days].sort().map((d) => DAY_LABELS[d]).join(', ')} (${timezone})`,
      ],
      ['Concurrency', `${maxConcurrent} at a time`],
      ['Retries', retryEnabled ? `${retryMax} × after ${retryIntervals.slice(0, retryMax).join(' / ')} min` : 'Off'],
      ...(isTrigger ? [] : ([['Estimated time', etaText()]] as Array<[string, string]>)),
      ['Results webhook', webhookUrl.trim() || 'None'],
    ];
    return (
      <div className="space-y-4">
        <dl className={`${panel} grid grid-cols-[140px_1fr] gap-x-4 gap-y-2 text-xs`}>
          {rows.map(([k, v]) => (
            <React.Fragment key={k}>
              <dt className="text-slate-500">{k}</dt>
              <dd className="text-slate-200">{v}</dd>
            </React.Fragment>
          ))}
        </dl>

        <Select
          label="Purpose"
          value={purpose}
          onChange={(e) => setPurpose(e.target.value as 'SERVICE' | 'PROMOTIONAL')}
          options={[
            { value: 'SERVICE', label: 'Service / transactional (enquiry follow-up, reminders)' },
            { value: 'PROMOTIONAL', label: 'Promotional (offers, marketing)' },
          ]}
        />
        {purpose === 'PROMOTIONAL' && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-800/50 bg-amber-950/30 p-3 text-xs text-amber-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            TRAI rules apply to AI calls too: promotional calls must not go to numbers on the national DND (NCPR) list. Scrub this
            list against the DND registry before launching.
          </div>
        )}
        <label className="flex items-start gap-2 text-xs text-slate-300">
          <input type="checkbox" className="mt-0.5" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          I confirm these people agreed to be contacted by {isAdmin ? 'this business' : 'us'}, and that anyone who asks not to be
          called will be added to the do-not-call list.
        </label>
      </div>
    );
  };

  const isLast = step === STEPS.length - 1;

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={isTrigger ? (isEdit ? 'Edit instant outbound' : 'New instant outbound') : isEdit ? 'Edit campaign' : 'Schedule campaign'} maxWidth="3xl">
      <div className="space-y-5">
        <ol className="grid grid-cols-4 gap-2">
          {STEPS.map((s, i) => (
            <li key={s.id}>
              <button
                type="button"
                disabled={i > step}
                onClick={() => i < step && setStep(i)}
                className="w-full text-center text-xs disabled:cursor-default"
              >
                <span className={i === step ? 'font-semibold text-slate-100' : i < step ? 'text-slate-300' : 'text-slate-500'}>
                  {s.id === 'recipients' && isTrigger ? 'Lead source' : s.title}
                </span>
                <span className={`mt-2 block h-1 rounded-full ${i <= step ? 'bg-[#00df8f]' : 'bg-[#143c49]'}`} />
              </button>
            </li>
          ))}
        </ol>

        <div className="min-h-[320px]">{[renderAgent, isTrigger ? renderLeadSource : renderRecipients, renderSchedule, renderReview][step]()}</div>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-rose-800/50 bg-rose-950/40 p-3 text-xs text-rose-200">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#102d38] pt-4">
          <span className="text-xs text-slate-500">
            Step {step + 1} of {STEPS.length}
            {stepError && <span className="ml-3 text-amber-400">{stepError}</span>}
          </span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={step === 0 ? onClose : () => setStep(step - 1)}>
              {step === 0 ? 'Cancel' : 'Back'}
            </Button>
            {isLast && isEdit ? (
              <Button variant="primary" isLoading={saving === 'draft'} disabled={!!saving} onClick={() => save('draft')}>
                Save changes
              </Button>
            ) : isLast ? (
              <>
                <Button variant="secondary" isLoading={saving === 'draft'} disabled={!!saving} onClick={() => save('draft')}>
                  Save draft
                </Button>
                <Button
                  variant="primary"
                  isLoading={saving === 'launch'}
                  disabled={!!saving || !consent}
                  leftIcon={<CheckCircle2 className="h-4 w-4" />}
                  onClick={() => save('launch')}
                >
                  Launch
                </Button>
              </>
            ) : (
              <Button variant="primary" disabled={!!stepError} onClick={() => setStep(step + 1)}>
                Next
              </Button>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
};

