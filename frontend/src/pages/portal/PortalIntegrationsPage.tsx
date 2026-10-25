import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, CheckCircle2, Copy, KeyRound, Plus, ShieldAlert, Trash2, Zap } from 'lucide-react';
import { Button } from '../../components/common/Button';
import { Input } from '../../components/common/Input';
import { Modal } from '../../components/common/Modal';
import { Badge } from '../../components/common/Badge';
import { ApiKey, CreatedApiKey, IntegrationsInfo, portalApiKeys } from '../../services/apiKeys';
import { WhatsAppSettings } from '../../components/portal/WhatsAppSettings';

const copy = (text: string) => navigator.clipboard?.writeText(text);

const CodeBlock: React.FC<{ code: string }> = ({ code }) => (
  <div className="relative">
    <pre className="overflow-x-auto rounded-md border border-[#143c49] bg-[#040d12] p-3 text-[11px] leading-relaxed text-slate-200">
      {code}
    </pre>
    <button
      type="button"
      aria-label="Copy code"
      onClick={() => copy(code)}
      className="absolute right-2 top-2 rounded p-1 text-slate-500 hover:bg-[#0f2c38] hover:text-slate-200"
    >
      <Copy className="h-3.5 w-3.5" />
    </button>
  </div>
);

const TABS = ['curl', 'Node.js', 'PHP / WordPress', 'Zapier / Google Forms'] as const;

export const PortalIntegrationsPage: React.FC = () => {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [info, setInfo] = useState<IntegrationsInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('Website form');
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>('curl');

  const load = useCallback(async () => {
    try {
      const [k, i] = await Promise.all([portalApiKeys.list(), portalApiKeys.info()]);
      setKeys(k);
      setInfo(i);
    } catch (e: any) {
      setError(e.message || 'Could not load API keys.');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const create = async () => {
    setCreating(true);
    setError(null);
    try {
      setCreated(await portalApiKeys.create(newName));
      setCreateOpen(false);
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (key: ApiKey) => {
    if (!window.confirm(`Revoke "${key.name}"? Websites using it will stop sending leads immediately.`)) return;
    try {
      await portalApiKeys.revoke(key.id);
      load();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const url = info?.leads_url || 'https://<your-choranta-domain>/api/public/leads';
  const running = info?.trigger_campaigns.filter((c) => c.status === 'RUNNING') || [];
  const examples: Record<(typeof TABS)[number], string> = {
    curl: `curl -X POST ${url} \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "phone": "9876543210",
    "name": "Priya Reddy",
    "consent": true,
    "source": "website-contact-form",
    "course_enquired": "NEET 2027"
  }'`,
    'Node.js': `// On your server (e.g. the route that handles your form). Never in browser code.
app.post('/enquiry', async (req, res) => {
  const { name, phone, course, agreed } = req.body;
  await fetch('${url}', {
    method: 'POST',
    headers: { 'X-API-Key': process.env.CHORANTA_API_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, name, consent: agreed === 'on', source: 'website', course_enquired: course }),
  });
  res.redirect('/thank-you');
});`,
    'PHP / WordPress': `// functions.php: after a Contact Form 7 form is sent (or any form plugin's "after submit" hook)
add_action('wpcf7_mail_sent', function ($form) {
  $data = WPCF7_Submission::get_instance()->get_posted_data();
  wp_remote_post('${url}', [
    'headers' => ['X-API-Key' => CHORANTA_API_KEY, 'Content-Type' => 'application/json'],
    'body'    => wp_json_encode([
      'phone'   => $data['your-phone'],
      'name'    => $data['your-name'],
      'consent' => !empty($data['call-consent']),
      'source'  => 'wordpress',
      'course_enquired' => $data['course'] ?? '',
    ]),
    'timeout' => 5,
  ]);
});
// In wp-config.php: define('CHORANTA_API_KEY', 'YOUR_API_KEY');`,
    'Zapier / Google Forms': `Zapier (works with Google Forms, Typeform, Facebook Lead Ads, etc.):
  1. Trigger: "New Form Response" (or your form app's trigger).
  2. Action: Webhooks by Zapier → POST.
     URL:      ${url}
     Payload:  JSON
     Data:     phone → (phone question), name → (name question), consent → true*,
               source → google-form, course_enquired → (course question)
     Headers:  X-API-Key → YOUR_API_KEY
  * Only send consent=true if your form asks "May we call you?" and the person agreed.

Google Forms without Zapier: Extensions → Apps Script, add an onFormSubmit trigger that calls
UrlFetchApp.fetch('${url}', {method: 'post', contentType: 'application/json',
  headers: {'X-API-Key': PropertiesService.getScriptProperties().getProperty('CHORANTA_API_KEY')},
  payload: JSON.stringify({phone: ..., name: ..., consent: true, source: 'google-form'})});`,
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">API & integrations</h1>
          <p className="text-xs text-slate-400">Send website enquiries to Choranta so your AI Employee calls them within seconds.</p>
        </div>
        <Button variant="primary" leftIcon={<Plus className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>
          Create API key
        </Button>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/60 bg-rose-950/40 p-3 text-xs text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      {info && running.length === 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-800/50 bg-amber-950/30 p-3 text-xs text-amber-200">
          <span className="flex items-center gap-2">
            <Zap className="h-4 w-4" />
            {info.trigger_campaigns.length === 0
              ? 'No instant outbound set up yet: leads will be rejected until you create one.'
              : 'Your instant outbound is not running: leads are queued and called once it runs.'}
          </span>
          <Link to="/portal/instant-outbound" className="text-[#00df8f] hover:underline">
            {info.trigger_campaigns.length === 0 ? 'Set up instant outbound' : 'Open instant outbound'}
          </Link>
        </div>
      )}

      <WhatsAppSettings />

      {/* API keys */}
      <section className="space-y-3 rounded-lg border border-[#143c49] bg-[#091b22] p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <KeyRound className="h-4 w-4 text-[#00df8f]" /> API keys
        </h2>
        {keys.length === 0 ? (
          <p className="text-xs text-slate-500">No API keys yet.</p>
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="text-slate-500">
              <tr>
                <th className="py-1.5 font-medium">Name</th>
                <th className="py-1.5 font-medium">Key</th>
                <th className="py-1.5 font-medium">Created</th>
                <th className="py-1.5 font-medium">Last used</th>
                <th className="py-1.5 font-medium" />
              </tr>
            </thead>
            <tbody className="text-slate-300">
              {keys.map((k) => (
                <tr key={k.id} className="border-t border-[#102d38]">
                  <td className="py-2">{k.name}</td>
                  <td className="py-2 font-mono text-slate-400">{k.prefix}…</td>
                  <td className="py-2">{new Date(k.created_at + 'Z').toLocaleDateString()}</td>
                  <td className="py-2">{k.last_used_at ? new Date(k.last_used_at + 'Z').toLocaleString() : 'Never'}</td>
                  <td className="py-2 text-right">
                    {k.revoked_at ? (
                      <Badge variant="gray" size="sm">
                        Revoked
                      </Badge>
                    ) : (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 text-slate-400 hover:text-rose-400"
                        onClick={() => revoke(k)}
                      >
                        <Trash2 className="h-3.5 w-3.5" /> Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* How to connect */}
      <section className="space-y-4 rounded-lg border border-[#143c49] bg-[#091b22] p-4">
        <h2 className="text-sm font-semibold text-slate-200">How to connect your website</h2>

        <div className="flex items-start gap-2 rounded-lg border border-rose-800/50 bg-rose-950/30 p-3 text-xs text-rose-200">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Never put your API key in browser JavaScript or HTML, where anyone can copy it. Send leads from your website's
            server, your form plugin, or a tool like Zapier.
          </span>
        </div>

        <ol className="list-decimal space-y-1.5 pl-5 text-xs text-slate-300">
          <li>Create an API key above and store it as a secret on your server.</li>
          <li>
            Add a checkbox to your form such as <em>"Yes, call me about my enquiry"</em>, and send <code>consent: true</code> only
            when it is ticked.
          </li>
          <li>
            After the form is submitted, POST the lead to <code className="text-[#00df8f]">{url}</code> with the header{' '}
            <code>X-API-Key</code>.
          </li>
          <li>The AI Employee calls within seconds during your campaign's calling hours; night enquiries are called when the window opens.</li>
        </ol>

        <div className="grid grid-cols-1 gap-2 text-xs text-slate-400 sm:grid-cols-2">
          <div>
            <span className="font-medium text-slate-300">Fields: </span>
            <code>phone</code> (required), <code>consent</code> (required, true), <code>name</code>, <code>source</code>,{' '}
            <code>campaign_id</code> (if you have several), and any other field, e.g. <code>course_enquired</code>, which the
            agent can use as <code>{'{{course_enquired}}'}</code>.
          </div>
          <div>
            <span className="font-medium text-slate-300">Responses: </span>
            <code>202</code> accepted (or <code>"status": "duplicate"</code> if the number was sent in the last 24 h),{' '}
            <code>400</code> missing phone/consent, <code>401</code> bad key, <code>409</code> no website-lead campaign,{' '}
            <code>429</code> more than {info?.rate_limit_per_minute ?? 60} leads a minute.
          </div>
        </div>

        <div className="flex flex-wrap gap-1 rounded-full bg-[#0a2028] p-0.5 text-xs sm:w-fit">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`rounded-full px-3 py-1 font-medium ${tab === t ? 'bg-[#00df8f] text-[#04110c]' : 'text-slate-300 hover:text-slate-100'}`}
            >
              {t}
            </button>
          ))}
        </div>
        <CodeBlock code={examples[tab]} />
      </section>

      <Modal isOpen={createOpen} onClose={() => setCreateOpen(false)} title="Create API key" maxWidth="md">
        <div className="space-y-4">
          <Input label="Name" value={newName} onChange={(e) => setNewName(e.target.value)} helperText="Where it's used, e.g. Website form" />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" isLoading={creating} disabled={!newName.trim()} onClick={create}>
              Create
            </Button>
          </div>
        </div>
      </Modal>

      <Modal isOpen={!!created} onClose={() => setCreated(null)} title="Your new API key" maxWidth="lg">
        {created && (
          <div className="space-y-4 text-xs">
            <div className="flex items-start gap-2 rounded-lg border border-amber-800/50 bg-amber-950/30 p-3 text-amber-200">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              Copy it now: for your security it won't be shown again. If you lose it, revoke it and create a new one.
            </div>
            <div className="flex items-center gap-2 rounded-md border border-[#143c49] bg-[#040d12] p-3">
              <code className="flex-1 break-all text-slate-100">{created.key}</code>
              <Button size="sm" variant="secondary" leftIcon={<Copy className="h-3.5 w-3.5" />} onClick={() => copy(created.key)}>
                Copy
              </Button>
            </div>
            <div className="flex justify-end">
              <Button variant="primary" leftIcon={<CheckCircle2 className="h-4 w-4" />} onClick={() => setCreated(null)}>
                I've saved it
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
