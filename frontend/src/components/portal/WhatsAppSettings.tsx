import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Clock, Copy, MessageCircle, Unplug, XCircle } from 'lucide-react';
import { Button } from '../common/Button';
import { Input } from '../common/Input';
import { Badge } from '../common/Badge';
import { FollowupInput, TemplateStatus, WhatsAppFollowup, WhatsAppOverview, portalWhatsApp } from '../../services/whatsapp';

const copy = (text: string) => navigator.clipboard?.writeText(text);

const SEND_WHEN = [
  { id: 'qualified', label: 'The lead is qualified (your qualification rules)' },
  { id: 'interested', label: 'The lead is interested' },
  { id: 'callback', label: 'The lead asks for a callback' },
];

const fieldClass =
  'block w-full rounded-md border border-[#143c49] bg-[#06141a] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none';

const StatusBadge: React.FC<{ status: TemplateStatus; sending: boolean }> = ({ status, sending }) => {
  if (status === 'APPROVED')
    return (
      <Badge variant="green" size="sm">
        <CheckCircle2 className="mr-1 inline h-3 w-3" />
        Approved
      </Badge>
    );
  if (status === 'PENDING')
    return (
      <Badge variant="yellow" size="sm">
        <Clock className="mr-1 inline h-3 w-3" />
        {sending ? 'New version waiting for approval' : 'Waiting for WhatsApp approval'}
      </Badge>
    );
  if (status === 'REJECTED' || status === 'ERROR')
    return (
      <Badge variant="red" size="sm">
        <XCircle className="mr-1 inline h-3 w-3" />
        {status === 'ERROR' ? 'Not submitted' : 'Rejected'}
      </Badge>
    );
  return null;
};

const CopyField: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <div className="mb-1 text-[11px] text-slate-500">{label}</div>
    <div className="flex items-center gap-2 rounded-md border border-[#143c49] bg-[#040d12] px-2 py-1.5">
      <code className="flex-1 break-all text-[11px] text-slate-200">{value || 'Not set up yet (ask Choranta support)'}</code>
      {value && (
        <button type="button" aria-label={`Copy ${label}`} onClick={() => copy(value)} className="text-slate-500 hover:text-slate-200">
          <Copy className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  </div>
);

const ConnectForm: React.FC<{ overview: WhatsAppOverview; onDone: (o: WhatsAppOverview) => void }> = ({ overview, onDone }) => {
  const [wabaId, setWabaId] = useState(overview.account.waba_id || '');
  const [phoneId, setPhoneId] = useState(overview.account.phone_number_id || '');
  const [token, setToken] = useState('');
  const [secret, setSecret] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = async () => {
    setSaving(true);
    setError(null);
    try {
      onDone(await portalWhatsApp.connect({ waba_id: wabaId, phone_number_id: phoneId, access_token: token, app_secret: secret || undefined }));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-3">
      <ol className="list-decimal space-y-1 pl-5 text-xs text-slate-300">
        <li>
          In your Meta developer app, open <em>WhatsApp → API Setup</em> and copy the <em>WhatsApp Business Account ID</em> and the{' '}
          <em>Phone number ID</em> of the number to send from.
        </li>
        <li>
          In Meta Business settings, create a <em>System user</em> and generate a permanent token with the{' '}
          <code>whatsapp_business_messaging</code> and <code>whatsapp_business_management</code> permissions.
        </li>
        <li>
          In the app's <em>WhatsApp → Configuration</em>, set the webhook below and subscribe to <code>messages</code> and{' '}
          <code>message_template_status_update</code>. Copy the <em>App secret</em> from <em>App settings → Basic</em>.
        </li>
      </ol>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <CopyField label="Callback URL" value={overview.webhook_url} />
        <CopyField label="Verify token" value={overview.verify_token} />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Input label="WhatsApp Business Account ID" value={wabaId} onChange={(e) => setWabaId(e.target.value)} inputMode="numeric" />
        <Input label="Phone number ID" value={phoneId} onChange={(e) => setPhoneId(e.target.value)} inputMode="numeric" />
        <Input label="Permanent access token" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
        <Input
          label="App secret"
          type="password"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
          autoComplete="off"
          helperText={overview.account.has_app_secret ? 'Saved. Leave empty to keep it.' : 'Needed to receive delivery updates and replies.'}
        />
      </div>
      {error && (
        <p className="flex items-start gap-1.5 text-xs text-rose-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
        </p>
      )}
      <Button variant="primary" isLoading={saving} disabled={!wabaId.trim() || !phoneId.trim() || !token.trim()} onClick={connect}>
        Connect WhatsApp
      </Button>
    </div>
  );
};

const FollowupEditor: React.FC<{
  followup: WhatsAppFollowup;
  businessName: string;
  connected: boolean;
  onSaved: (f: WhatsAppFollowup) => void;
}> = ({ followup, businessName, connected, onSaved }) => {
  const [form, setForm] = useState<FollowupInput>({
    enabled: followup.configured ? followup.enabled : true,
    message: followup.message,
    language: followup.language,
    send_when: followup.send_when,
    button_text: followup.button_text,
    button_url: followup.button_url,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const set = (patch: Partial<FollowupInput>) => {
    setForm((f) => ({ ...f, ...patch }));
    setSaved(false);
  };

  const insert = (key: string) => {
    const el = textRef.current;
    const token = `{${key}}`;
    const start = el?.selectionStart ?? form.message.length;
    const end = el?.selectionEnd ?? form.message.length;
    set({ message: form.message.slice(0, start) + token + form.message.slice(end) });
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const preview = form.message.replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, (_, key: string) => {
    if (key === 'name') return 'Priya';
    if (key === 'centre') return businessName || 'your business';
    return `[${key.replace(/_/g, ' ')}]`;
  });

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      onSaved(await portalWhatsApp.saveFollowup(followup.agent_id, form));
      setSaved(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const toggleWhen = (id: string) =>
    set({ send_when: form.send_when.includes(id) ? form.send_when.filter((w) => w !== id) : [...form.send_when, id] });

  return (
    <div className="space-y-3 rounded-lg border border-[#102d38] bg-[#06141a]/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-sm font-medium text-slate-200">
          <input type="checkbox" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} className="accent-[#00df8f]" />
          {followup.agent_name}: send a WhatsApp message after the call
        </label>
        <StatusBadge status={followup.template_status} sending={followup.sending_version && !followup.sending_latest} />
      </div>

      {followup.template_detail && (
        <p className={`text-xs ${followup.template_status === 'REJECTED' || followup.template_status === 'ERROR' ? 'text-rose-300' : 'text-slate-400'}`}>
          {followup.template_detail}
        </p>
      )}
      {followup.template_status === 'PENDING' && followup.sending_version && !followup.sending_latest && (
        <p className="text-xs text-slate-400">Until WhatsApp approves the new version, leads get the previously approved one.</p>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-slate-300" htmlFor={`wa-msg-${followup.agent_id}`}>
            Message
          </label>
          <textarea
            id={`wa-msg-${followup.agent_id}`}
            ref={textRef}
            rows={6}
            maxLength={1024}
            value={form.message}
            onChange={(e) => set({ message: e.target.value })}
            placeholder="Hi {name}, thanks for your interest in {course} at {centre}. Fees: Rs 25,000. The next batch starts on 4 November. Reply here with any questions."
            className={fieldClass}
          />
          <div className="flex flex-wrap gap-1">
            {followup.placeholders.map((p) => (
              <button
                key={p.key}
                type="button"
                title={p.label}
                onClick={() => insert(p.key)}
                className="rounded-full border border-[#143c49] px-2 py-0.5 text-[11px] text-slate-300 hover:border-[#00df8f] hover:text-[#00df8f]"
              >
                {`{${p.key}}`}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-slate-500">{form.message.length}/1024. Start and end with words, not a placeholder.</p>
        </div>
        <div className="space-y-1.5">
          <div className="text-xs font-medium text-slate-300">Preview</div>
          <div className="min-h-[9rem] whitespace-pre-wrap rounded-lg bg-[#0b3b2e] p-3 text-sm text-emerald-50">
            {preview || <span className="text-emerald-200/50">Your message appears here.</span>}
            {form.button_url && form.button_text && (
              <div className="mt-3 border-t border-emerald-200/20 pt-2 text-center text-sky-300">{form.button_text}</div>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Input label="Button label (optional)" maxLength={25} value={form.button_text || ''} onChange={(e) => set({ button_text: e.target.value || null })} placeholder="View brochure" />
        <Input label="Button link" value={form.button_url || ''} onChange={(e) => set({ button_url: e.target.value || null })} placeholder="https://..." />
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-slate-300" htmlFor={`wa-lang-${followup.agent_id}`}>
            Message language
          </label>
          <select id={`wa-lang-${followup.agent_id}`} value={form.language} onChange={(e) => set({ language: e.target.value })} className={fieldClass}>
            {followup.languages.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-xs text-slate-300">
        <span className="text-slate-500">Send when:</span>
        {SEND_WHEN.map((w) => (
          <label key={w.id} className="flex items-center gap-1.5">
            <input type="checkbox" checked={form.send_when.includes(w.id)} onChange={() => toggleWhen(w.id)} className="accent-[#00df8f]" />
            {w.label}
          </label>
        ))}
      </div>

      {error && (
        <p className="flex items-start gap-1.5 text-xs text-rose-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
        </p>
      )}
      <div className="flex items-center gap-3">
        <Button variant="primary" size="sm" isLoading={saving} disabled={!form.message.trim() || form.send_when.length === 0} onClick={save}>
          {connected ? 'Save and submit to WhatsApp' : 'Save'}
        </Button>
        {saved && <span className="text-xs text-[#00df8f]">Saved</span>}
      </div>
    </div>
  );
};

/** The client's WhatsApp Business connection and each AI employee's follow-up message. */
export const WhatsAppSettings: React.FC = () => {
  const [overview, setOverview] = useState<WhatsAppOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reconnect, setReconnect] = useState(false);

  const load = useCallback(async () => {
    try {
      setOverview(await portalWhatsApp.overview());
    } catch (e: any) {
      setError(e.message || 'Could not load WhatsApp settings.');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const disconnect = async () => {
    if (!window.confirm('Disconnect WhatsApp? Follow-up messages stop until you connect again.')) return;
    try {
      setOverview(await portalWhatsApp.disconnect());
    } catch (e: any) {
      setError(e.message);
    }
  };

  const account = overview?.account;
  const showForm = overview && (!account?.connected || account.status === 'INVALID' || reconnect);

  return (
    <section className="space-y-4 rounded-lg border border-[#143c49] bg-[#091b22] p-4">
      <div>
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <MessageCircle className="h-4 w-4 text-[#00df8f]" /> WhatsApp follow-ups
        </h2>
        <p className="mt-1 text-xs text-slate-400">
          When a lead qualifies on a call, your AI employee sends them your message on WhatsApp from your own business number.
          Each message sent costs a few paise in credits.
        </p>
      </div>

      {error && <p className="text-xs text-rose-300">{error}</p>}
      {!overview && !error && <p className="text-xs text-slate-500">Loading…</p>}

      {account?.connected && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#102d38] bg-[#06141a]/60 p-3 text-xs">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2 text-slate-200">
              {account.verified_name || 'WhatsApp Business'} · {account.display_phone}
              {account.status === 'ACTIVE' ? (
                <Badge variant="green" size="sm">Connected</Badge>
              ) : (
                <Badge variant="red" size="sm">Needs reconnecting</Badge>
              )}
            </div>
            {account.status_detail && <div className="text-rose-300">{account.status_detail}</div>}
            {!account.has_app_secret && <div className="text-amber-300">Add your app secret to see delivery updates and replies.</div>}
          </div>
          <div className="flex gap-2">
            {account.status === 'ACTIVE' && (
              <Button variant="ghost" size="sm" onClick={() => setReconnect((r) => !r)}>
                {reconnect ? 'Cancel' : 'Update details'}
              </Button>
            )}
            <Button variant="ghost" size="sm" leftIcon={<Unplug className="h-3.5 w-3.5" />} onClick={disconnect}>
              Disconnect
            </Button>
          </div>
        </div>
      )}

      {showForm && (
        <ConnectForm
          overview={overview}
          onDone={(o) => {
            setOverview(o);
            setReconnect(false);
          }}
        />
      )}

      {overview && overview.followups.length === 0 && <p className="text-xs text-slate-500">You don't have an AI employee yet.</p>}
      {overview?.followups.map((f) => (
        <FollowupEditor
          key={f.agent_id}
          followup={f}
          businessName={account?.verified_name || ''}
          connected={!!account?.connected && account.status === 'ACTIVE'}
          onSaved={(saved) => setOverview((o) => o && { ...o, followups: o.followups.map((x) => (x.agent_id === saved.agent_id ? saved : x)) })}
        />
      ))}
    </section>
  );
};
