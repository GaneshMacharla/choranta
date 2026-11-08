import React, { useEffect, useState } from 'react';
import { Wallet as WalletIcon, Plus, Download, UserPlus, Trash2, AlertTriangle } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Modal } from '../common/Modal';
import { WalletLedger } from './WalletLedger';
import { billingService, BillingProfile, ClientLogin, GstSplit } from '../../services/billing';
import { inr, InvoiceSummary, Wallet } from '../../services/portal';

const inputClass = 'w-full rounded border border-[#232736] bg-[#10121a] p-2 text-xs text-slate-100';

/** Admin view of a client's prepaid wallet, GST invoices, billing profile and portal logins. */
export const ClientBillingCard: React.FC<{ clientId: string }> = ({ clientId }) => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  const [profile, setProfile] = useState<BillingProfile | null>(null);
  const [logins, setLogins] = useState<ClientLogin[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [modal, setModal] = useState<'payment' | 'adjust' | 'profile' | 'login' | null>(null);

  // Form state
  const [amount, setAmount] = useState('');
  const [reference, setReference] = useState('');
  const [split, setSplit] = useState<GstSplit | null>(null);
  const [adjAmount, setAdjAmount] = useState('');
  const [adjNote, setAdjNote] = useState('');
  const [profileDraft, setProfileDraft] = useState<BillingProfile | null>(null);
  const [loginEmail, setLoginEmail] = useState('');
  const [loginName, setLoginName] = useState('');

  const load = async () => {
    try {
      const [w, i, p] = await Promise.all([
        billingService.wallet(clientId),
        billingService.invoices(clientId),
        billingService.profile(clientId),
      ]);
      setWallet(w);
      setInvoices(i);
      setProfile(p);
      if (isAdmin) setLogins(await billingService.logins(clientId));
    } catch (err: any) {
      setError(err.message || 'Could not load billing.');
    }
  };

  useEffect(() => {
    load();
  }, [clientId]);

  // Live GST split while typing the received amount
  useEffect(() => {
    const value = Number(amount);
    if (modal !== 'payment' || !value || value <= 0) {
      setSplit(null);
      return;
    }
    const t = setTimeout(() => {
      billingService.previewPayment(clientId, value).then(setSplit).catch(() => setSplit(null));
    }, 300);
    return () => clearTimeout(t);
  }, [amount, modal, clientId]);

  const run = async (key: string, action: () => Promise<any>, close = true) => {
    setBusy(key);
    setError(null);
    try {
      await action();
      if (close) setModal(null);
      await load();
    } catch (err: any) {
      setError(err.message || 'Something went wrong.');
    } finally {
      setBusy(null);
    }
  };

  if (!wallet) {
    return (
      <Card title="Billing & Wallet">
        <p className="text-xs text-slate-500">{error || 'Loading billing...'}</p>
      </Card>
    );
  }

  return (
    <Card
      title="Billing & Wallet"
      subtitle={`Prepaid wallet: ${wallet.invoices_enabled ? `payments issue ${wallet.gst_registered ? 'GST invoices' : 'receipts (no GST)'}, ` : ''}calls are charged automatically`}
    >
      <div className="space-y-4 text-xs">
        {error && (
          <div className="flex items-start gap-2 rounded border border-rose-800/50 bg-rose-950/40 p-2.5 text-rose-300">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span className="flex items-center gap-1.5 text-slate-400">
              <WalletIcon className="h-4 w-4 text-[#00df8f]" /> Wallet balance{wallet.gst_registered ? ' (excl. GST)' : ''}
            </span>
            <span className={`font-mono text-2xl font-bold ${wallet.calls_blocked ? 'text-rose-300' : wallet.low_balance ? 'text-amber-300' : 'text-slate-100'}`}>
              {inr(wallet.balance_inr)}
            </span>
            {wallet.calls_blocked && <span className="ml-2 text-rose-300">Calls paused: {wallet.calls_blocked_reason}</span>}
            {!wallet.calls_blocked && wallet.low_balance && <span className="ml-2 text-amber-300">Low balance</span>}
            {!wallet.subscription && wallet.balance_inr > 0 && wallet.max_concurrent_calls != null && (
              <span className="block text-xs text-slate-500">
                Covers up to {wallet.max_concurrent_calls} call{wallet.max_concurrent_calls === 1 ? '' : 's'} at a time
                ({wallet.live_calls} live now)
              </span>
            )}
          </div>
          {isAdmin && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="primary" onClick={() => { setAmount(''); setReference(''); setModal('payment'); }}>
                <Plus className="mr-1 h-3.5 w-3.5" /> Record payment
              </Button>
              <Button size="sm" variant="secondary" onClick={() => { setAdjAmount(''); setAdjNote(''); setModal('adjust'); }}>
                Adjust
              </Button>
              <Button size="sm" variant="secondary" onClick={() => { setProfileDraft(profile); setModal('profile'); }}>
                Billing profile
              </Button>
            </div>
          )}
        </div>

        <div className="rounded border border-[#1b2030] bg-[#0d101a] p-3 text-slate-400">
          <span className="text-slate-300">{profile?.legal_name}</span>
          {profile?.gstin ? ` · GSTIN ${profile.gstin}` : ' · GSTIN not set'}
          {profile?.state_code ? ` · State code ${profile.state_code}` : (wallet.invoices_enabled ? ' · State not set (invoices use your state)' : ' · State not set')}
        </div>

        {wallet.invoices_enabled && <div className="rounded border border-[#1b2030]">
          <p className="border-b border-[#1b2030] px-4 py-2 font-semibold text-slate-300">Invoices</p>
          {invoices.length === 0 ? (
            <p className="px-4 py-3 text-slate-500">No invoices yet.</p>
          ) : (
            invoices.slice(0, 10).map((inv) => (
              <div key={inv.id} className="flex items-center justify-between border-b border-[#151a26] px-4 py-2 last:border-0">
                <span className="font-mono text-slate-300">{inv.number}</span>
                <span className="text-slate-500">{new Date(inv.issue_date).toLocaleDateString('en-IN')}</span>
                <span className="font-mono text-slate-200">{inr(inv.total_inr)}</span>
                <Button size="sm" variant="ghost" isLoading={busy === 'pdf-' + inv.id} onClick={() => run('pdf-' + inv.id, () => billingService.downloadInvoice(inv), false)}>
                  <Download className="h-3.5 w-3.5" />
                </Button>
              </div>
            ))
          )}
        </div>}

        <div className="rounded border border-[#1b2030]">
          <p className="border-b border-[#1b2030] px-4 py-2 font-semibold text-slate-300">Wallet activity</p>
          <WalletLedger transactions={wallet.transactions.slice(0, 50)} />
        </div>

        {isAdmin && (
          <div className="rounded border border-[#1b2030]">
            <div className="flex items-center justify-between border-b border-[#1b2030] px-4 py-2">
              <span className="font-semibold text-slate-300">Client portal logins (Google)</span>
              <Button size="sm" variant="secondary" onClick={() => { setLoginEmail(''); setLoginName(''); setModal('login'); }}>
                <UserPlus className="mr-1 h-3.5 w-3.5" /> Invite
              </Button>
            </div>
            {logins.length === 0 ? (
              <p className="px-4 py-3 text-slate-500">No one from this client can sign in yet.</p>
            ) : (
              logins.map((l) => (
                <div key={l.id} className="flex items-center justify-between border-b border-[#151a26] px-4 py-2 last:border-0">
                  <span className="text-slate-300">{l.name} <span className="text-slate-500">· {l.email}</span></span>
                  <Button size="sm" variant="ghost" isLoading={busy === 'rm-' + l.id} onClick={() => run('rm-' + l.id, () => billingService.removeLogin(clientId, l.id), false)}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <Modal
        isOpen={modal === 'payment'}
        onClose={() => setModal(null)}
        title="Record payment"
        description={
          wallet.gst_registered
            ? `Amount received from the client, including GST. ${wallet.invoices_enabled ? 'A GST invoice is issued and the' : 'The'} wallet is credited with the taxable value.`
            : `Amount received from the client. ${wallet.invoices_enabled ? 'A payment receipt is issued and the' : 'The'} wallet is credited with the full amount (no GST).`
        }
      >
        <div className="space-y-3 text-xs">
          <label className="block space-y-1">
            <span className="text-slate-300">Amount received (₹{wallet.gst_registered ? ', incl. GST' : ''})</span>
            <input type="number" min={1} className={inputClass} value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label className="block space-y-1">
            <span className="text-slate-300">Payment reference (UTR / UPI ref)</span>
            <input className={inputClass} value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
          {split && (
            <div className="space-y-1 rounded border border-[#1b2030] bg-black/30 p-3 font-mono text-slate-300">
              <div className="flex justify-between"><span>Wallet credit{split.gst_registered ? ' (taxable)' : ''}</span><span className="text-[#00df8f]">{inr(split.taxable_inr)}</span></div>
              {!split.gst_registered ? null : split.intra_state ? (
                <>
                  <div className="flex justify-between"><span>CGST</span><span>{inr(split.cgst_inr)}</span></div>
                  <div className="flex justify-between"><span>SGST</span><span>{inr(split.sgst_inr)}</span></div>
                </>
              ) : (
                <div className="flex justify-between"><span>IGST</span><span>{inr(split.igst_inr)}</span></div>
              )}
              <div className="flex justify-between border-t border-[#1b2030] pt-1 font-semibold"><span>{!wallet.invoices_enabled ? 'Total' : split.gst_registered ? 'Invoice total' : 'Receipt total'}</span><span>{inr(split.total_inr)}</span></div>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setModal(null)}>Cancel</Button>
            <Button variant="primary" disabled={!split} isLoading={busy === 'pay'} onClick={() => run('pay', () => billingService.recordPayment(clientId, Number(amount), reference))}>
              {wallet.invoices_enabled ? 'Record & issue invoice' : 'Record payment'}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal isOpen={modal === 'adjust'} onClose={() => setModal(null)} title="Adjust wallet" description={`Refunds, goodwill credits or corrections.${wallet.invoices_enabled ? ' No invoice is issued.' : ''}`}>
        <div className="space-y-3 text-xs">
          <label className="block space-y-1">
            <span className="text-slate-300">Amount (₹; negative to deduct)</span>
            <input type="number" className={inputClass} value={adjAmount} onChange={(e) => setAdjAmount(e.target.value)} />
          </label>
          <label className="block space-y-1">
            <span className="text-slate-300">Note (required)</span>
            <input className={inputClass} value={adjNote} onChange={(e) => setAdjNote(e.target.value)} />
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setModal(null)}>Cancel</Button>
            <Button variant="primary" disabled={!Number(adjAmount) || !adjNote.trim()} isLoading={busy === 'adj'} onClick={() => run('adj', () => billingService.adjust(clientId, Number(adjAmount), adjNote))}>
              Apply
            </Button>
          </div>
        </div>
      </Modal>

      <Modal isOpen={modal === 'profile'} onClose={() => setModal(null)} title="Billing profile" description={wallet.invoices_enabled ? "Printed on the client's GST invoices." : "The client's billing details."}>
        {profileDraft && (
          <div className="space-y-3 text-xs">
            {([
              ['legal_name', 'Legal name'],
              ['gstin', 'GSTIN (optional)'],
              ['state_code', 'GST state code (2 digits, e.g. 36 Telangana, 29 Karnataka)'],
              ['billing_email', 'Billing email'],
            ] as const).map(([key, label]) => (
              <label key={key} className="block space-y-1">
                <span className="text-slate-300">{label}</span>
                <input
                  className={inputClass}
                  value={profileDraft[key] || ''}
                  onChange={(e) => setProfileDraft({ ...profileDraft, [key]: e.target.value })}
                />
              </label>
            ))}
            <label className="block space-y-1">
              <span className="text-slate-300">Address</span>
              <textarea rows={3} className={inputClass} value={profileDraft.address || ''} onChange={(e) => setProfileDraft({ ...profileDraft, address: e.target.value })} />
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setModal(null)}>Cancel</Button>
              <Button
                variant="primary"
                disabled={!profileDraft.legal_name?.trim()}
                isLoading={busy === 'profile'}
                onClick={() =>
                  run('profile', () =>
                    billingService.saveProfile(clientId, {
                      legal_name: profileDraft.legal_name,
                      gstin: profileDraft.gstin || null,
                      address: profileDraft.address || null,
                      state_code: profileDraft.state_code || null,
                      billing_email: profileDraft.billing_email || null,
                    })
                  )
                }
              >
                Save
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal isOpen={modal === 'login'} onClose={() => setModal(null)} title="Invite client login" description="They sign in with the Google account for this email and see only this client's portal.">
        <div className="space-y-3 text-xs">
          <label className="block space-y-1">
            <span className="text-slate-300">Google email</span>
            <input type="email" className={inputClass} value={loginEmail} onChange={(e) => setLoginEmail(e.target.value)} />
          </label>
          <label className="block space-y-1">
            <span className="text-slate-300">Name (optional)</span>
            <input className={inputClass} value={loginName} onChange={(e) => setLoginName(e.target.value)} />
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setModal(null)}>Cancel</Button>
            <Button variant="primary" disabled={!loginEmail.includes('@')} isLoading={busy === 'invite'} onClick={() => run('invite', () => billingService.inviteLogin(clientId, loginEmail.trim(), loginName.trim()))}>
              Invite
            </Button>
          </div>
        </div>
      </Modal>
    </Card>
  );
};
