import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, Copy, Eye, EyeOff, KeyRound, Mail, RefreshCw, Zap } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { InstantSetup, portalInstantSetup } from '../../services/apiKeys';

const developerMessage = (url: string, key: string) => `Hi,

Please connect our website's enquiry form to Choranta, so our AI assistant calls every new enquiry within seconds.

When the form is submitted, send this from the website's server (not from browser JavaScript):

  POST ${url}
  Header:  X-API-Key: ${key}
  Body (JSON):
  {
    "phone": "<visitor's phone number>",
    "name": "<visitor's name>",
    "consent": true,
    "source": "website"
  }

Only send "consent": true when the visitor ticked a box like "Yes, call me about my enquiry".
Other form fields (for example "course") can be added too; the assistant can use them.

Please keep the key private: it works like a password for our account.

Examples for WordPress, Node.js and Zapier: ${window.location.origin}/portal/integrations
`;

const Step: React.FC<{ n: number; done: boolean; title: string; children: React.ReactNode }> = ({ n, done, title, children }) => (
  <li className="flex gap-3">
    <span
      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
        done ? 'bg-[#00df8f] text-[#04110c]' : 'border border-[#1d4b5a] text-slate-300'
      }`}
    >
      {done ? <Check className="h-3.5 w-3.5" /> : n}
    </span>
    <div className="min-w-0 flex-1 space-y-2">
      <div className="text-sm font-semibold text-slate-100">{title}</div>
      {children}
    </div>
  </li>
);

/**
 * Dashboard card that walks a client (usually not technical) through instant outbound: turn it on, then give
 * their website person the address and the key Choranta created for them at sign-up.
 */
export const InstantSetupCard: React.FC = () => {
  const [setup, setSetup] = useState<InstantSetup | null>(null);
  const [key, setKey] = useState<string | null>(null);
  const [shown, setShown] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    portalInstantSetup.get().then(setSetup).catch(() => setSetup(null));
  }, []);

  const fullKey = async (): Promise<string | null> => {
    if (key) return key;
    try {
      const { key: value } = await portalInstantSetup.revealKey();
      setKey(value);
      return value;
    } catch (e: any) {
      setError(e.message || 'Could not load your key.');
      return null;
    }
  };

  const copy = async (what: string, text: string | null) => {
    if (!text) return;
    await navigator.clipboard?.writeText(text);
    setCopied(what);
    setTimeout(() => setCopied((c) => (c === what ? null : c)), 2000);
  };

  const regenerate = async () => {
    if (!window.confirm('Make a new key? The current key stops working at once, so your website must be updated with the new one.')) return;
    setBusy(true);
    setError(null);
    try {
      setSetup(await portalInstantSetup.regenerateKey());
      setKey(null);
      setShown(false);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!setup) return null;
  const turnedOn = setup.running;
  const used = !!setup.key?.last_used_at;
  const masked = setup.key ? `${setup.key.prefix}${'•'.repeat(18)}` : '';
  const copiedLabel = (what: string, label: string) => (copied === what ? 'Copied' : label);

  return (
    <Card
      title={
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          <Zap className="h-4 w-4 text-[#00df8f]" /> Call your website enquiries within seconds
        </span>
      }
      subtitle="When someone fills the enquiry form on your website, your AI employee calls them within 30 seconds, while they are still interested."
      action={
        <Link to="/portal/instant-outbound" className="text-xs text-[#00df8f] hover:underline">
          See how it works
        </Link>
      }
    >
      <ol className="space-y-5">
        <Step n={1} done={turnedOn} title="Turn on Instant Outbound">
          {!setup.has_agent ? (
            <p className="text-xs text-slate-400">Your AI employee is still being set up. You can do this step once it's ready.</p>
          ) : turnedOn ? (
            <p className="text-xs text-slate-400">It's on. New enquiries are called during your calling hours.</p>
          ) : (
            <div className="space-y-2">
              <p className="text-xs text-slate-400">
                {setup.campaigns.length
                  ? "It's set up but not running, so enquiries wait instead of being called."
                  : 'Choose which AI employee makes the calls and the hours it may call.'}
              </p>
              <Link to={setup.campaigns.length ? `/portal/instant-outbound/${setup.campaigns[0].id}` : '/portal/instant-outbound'}>
                <Button size="sm" variant="primary">{setup.campaigns.length ? 'Open Instant Outbound' : 'Set up Instant Outbound'}</Button>
              </Link>
            </div>
          )}
        </Step>

        <Step n={2} done={used} title="Connect your website">
          <p className="text-xs text-slate-400">
            Send the two details below to the person who manages your website (your web developer or agency). The easiest way:
            copy the ready-made message and send it to them on email or WhatsApp.
          </p>
          {setup.key ? (
            <>
              <div className="grid gap-2 sm:grid-cols-2">
                <div className="rounded-md border border-[#143c49] bg-[#040d12] p-2">
                  <div className="mb-1 text-[11px] text-slate-500">Address to send enquiries to</div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 break-all text-[11px] text-slate-200">{setup.leads_url}</code>
                    <button type="button" aria-label="Copy address" className="text-slate-500 hover:text-slate-200" onClick={() => copy('url', setup.leads_url)}>
                      {copied === 'url' ? <Check className="h-3.5 w-3.5 text-[#00df8f]" /> : <Copy className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>
                <div className="rounded-md border border-[#143c49] bg-[#040d12] p-2">
                  <div className="mb-1 flex items-center gap-1 text-[11px] text-slate-500">
                    <KeyRound className="h-3 w-3" /> Your secret key
                  </div>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 break-all text-[11px] text-slate-200">{shown && key ? key : masked}</code>
                    <button
                      type="button"
                      aria-label={shown ? 'Hide key' : 'Show key'}
                      className="text-slate-500 hover:text-slate-200"
                      onClick={async () => {
                        if (shown) return setShown(false);
                        if (await fullKey()) setShown(true);
                      }}
                    >
                      {shown ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                    </button>
                    <button type="button" aria-label="Copy key" className="text-slate-500 hover:text-slate-200" onClick={async () => copy('key', await fullKey())}>
                      {copied === 'key' ? <Check className="h-3.5 w-3.5 text-[#00df8f]" /> : <Copy className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>
              </div>
              <p className="text-[11px] text-amber-300/90">
                Keep the key private, like a password. Share it only with your website person, never on your website or social media.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  leftIcon={<Mail className="h-3.5 w-3.5" />}
                  onClick={async () => {
                    const value = await fullKey();
                    if (value) copy('message', developerMessage(setup.leads_url, value));
                  }}
                >
                  {copiedLabel('message', 'Copy message for your website person')}
                </Button>
                <Button size="sm" variant="ghost" isLoading={busy} leftIcon={<RefreshCw className="h-3.5 w-3.5" />} onClick={regenerate}>
                  Make a new key
                </Button>
              </div>
              {used ? (
                <p className="text-xs text-[#00df8f]">Your website is connected: the last enquiry arrived {new Date(setup.key.last_used_at!).toLocaleString()}.</p>
              ) : null}
            </>
          ) : (
            <p className="text-xs text-slate-400">
              Your key isn't available right now. Create one under <Link to="/portal/integrations" className="text-[#00df8f] hover:underline">API &amp; integrations</Link>.
            </p>
          )}
        </Step>

        <Step n={3} done={used && turnedOn} title="Try it yourself">
          <p className="text-xs text-slate-400">
            Once connected, fill the form on your website with your own phone number and tick "call me". You should get a call within a
            few seconds, and it shows up under <Link to="/portal/calls" className="text-[#00df8f] hover:underline">Calls</Link>.
          </p>
        </Step>
      </ol>
      {error && <p className="mt-3 text-xs text-rose-300">{error}</p>}
    </Card>
  );
};
