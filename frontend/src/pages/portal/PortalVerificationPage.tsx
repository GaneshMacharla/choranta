import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { AlertTriangle, Building2, CheckCircle, Clock, Fingerprint, RefreshCw, Search, ShieldCheck, User, XCircle } from 'lucide-react';
import { Card } from '../../components/common/Card';
import { Button } from '../../components/common/Button';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { BusinessVerification, CinMatch, KycCheck, KycType, portalService } from '../../services/portal';

const TYPE_ICONS: Record<KycType, React.ElementType> = { INDIVIDUAL: User, BUSINESS: Building2 };
const inputClass = 'w-full rounded border border-[#232736] bg-[#10121a] p-2 text-sm text-slate-100 disabled:opacity-70';

const CheckStatus: React.FC<{ check?: KycCheck }> = ({ check }) => {
  if (!check) return <span className="text-xs text-slate-500">Not checked yet</span>;
  if (check.status === 'verified')
    return <span className="flex items-center gap-1 text-xs text-emerald-300"><CheckCircle className="h-3.5 w-3.5" /> Verified{check.name ? `: ${check.name}` : ''}</span>;
  if (check.status === 'pending')
    return <span className="flex items-center gap-1 text-xs text-sky-300"><Clock className="h-3.5 w-3.5" /> Being checked</span>;
  return (
    <span className="flex items-center gap-1 text-xs text-rose-300">
      <XCircle className="h-3.5 w-3.5" /> Couldn't verify{check.message ? `: ${check.message}` : ''}. Check it and try again.
    </span>
  );
};

/** One document: what the client types, and Vobiz's answer. */
const Step: React.FC<{ title: string; hint?: string; check?: KycCheck; children?: React.ReactNode }> = ({ title, hint, check, children }) => (
  <div className="space-y-2 rounded-lg border border-[#143c49] bg-[#06141a] p-4">
    <div className="flex flex-wrap items-start justify-between gap-2">
      <div>
        <div className="text-sm font-medium text-slate-200">{title}</div>
        {hint && <div className="text-xs text-slate-500">{hint}</div>}
      </div>
      <CheckStatus check={check} />
    </div>
    {check?.status !== 'verified' && children}
  </div>
);

/**
 * Client portal: one-time business verification before getting phone numbers. The client picks Individual or
 * Business and types their documents' numbers; each is checked by Vobiz on the spot (Aadhaar through DigiLocker).
 */
export const PortalVerificationPage: React.FC = () => {
  const [params, setParams] = useSearchParams();
  const [v, setV] = useState<BusinessVerification | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [kycType, setKycType] = useState<KycType | null>(null);
  const [email, setEmail] = useState('');
  const [changing, setChanging] = useState(false);
  const [pan, setPan] = useState('');
  const [gstin, setGstin] = useState('');
  const [company, setCompany] = useState('');
  const [matches, setMatches] = useState<CinMatch[] | null>(null);
  const returning = useRef(false);

  const load = useCallback(
    () =>
      portalService
        .verification()
        .then((data) => {
          setV(data);
          if (data.kyc_type) setKycType(data.kyc_type);
          if (data.email) setEmail(data.email);
        })
        .catch((e) => setLoadError(e.message || 'Could not load your verification.')),
    [],
  );

  const run = async (key: string, action: () => Promise<BusinessVerification | void>) => {
    setBusy(key);
    setError(null);
    try {
      const updated = await action();
      if (updated) setV(updated);
    } catch (e: any) {
      setError(e.message || 'Something went wrong. Please try again.');
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    // Back from DigiLocker: finish the Aadhaar check once
    const state = params.get('state');
    if (params.get('digilocker') && state && !returning.current) {
      returning.current = true;
      setParams({}, { replace: true });
      run('aadhaar', () => portalService.completeAadhaar(state)).then(load);
      return;
    }
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loadError) return <ErrorState message={loadError} onRetry={load} />;
  if (!v) return <LoadingState message="Loading..." />;

  const checks = v.checks || {};
  const verified = v.status === 'VERIFIED';
  const started = v.status !== 'NOT_STARTED' && !changing;
  const anyVerified = Object.values(checks).some((c) => c?.status === 'verified');
  const anyPending = Object.values(checks).some((c) => c?.status === 'pending');
  const panVerified = checks.pan?.status === 'verified';
  const businessDone = checks.gst?.status === 'verified' || checks.cin?.status === 'verified';

  const start = () =>
    kycType &&
    run('start', async () => {
      const updated = await portalService.startVerification(kycType, email.trim());
      setChanging(false);
      return updated;
    });

  const digilocker = () =>
    run('aadhaar', async () => {
      const { auth_url } = await portalService.startAadhaar(`${window.location.origin}/portal/verification?digilocker=1`);
      window.location.href = auth_url;
    });

  const searchCompany = () =>
    run('cin-search', async () => {
      setMatches((await portalService.searchCin(company.trim())).matches);
    });

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-bold">
          <ShieldCheck className="h-5 w-5 text-[#00df8f]" /> Verify your business
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          A one-time step before you get phone numbers. Indian telecom rules require every number to be linked to a verified owner.
          Your documents are checked instantly against government records; nothing to upload.
        </p>
      </div>

      {verified && (
        <div className="flex items-start gap-2 rounded-lg border border-emerald-800/60 bg-emerald-950/30 p-4 text-sm text-emerald-200">
          <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Your business is verified. <Link to="/portal/numbers" className="font-semibold underline">Get a phone number</Link>
          </span>
        </div>
      )}

      <Card title="1. How are you registered?">
        {started ? (
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="text-slate-200">
              {v.kyc_types[v.kyc_type!]?.label} · <span className="text-slate-400">{v.email}</span>
            </span>
            {!verified && !anyVerified && (
              <Button size="sm" variant="ghost" onClick={() => setChanging(true)}>Change</Button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {(Object.keys(v.kyc_types) as KycType[]).map((key) => {
                const Icon = TYPE_ICONS[key];
                const selected = kycType === key;
                return (
                  <button key={key} type="button" onClick={() => setKycType(key)}
                    className={`rounded-lg border p-4 text-left transition ${selected ? 'border-[#00df8f] bg-[#00df8f]/10' : 'border-[#143c49] hover:border-[#1e4e5e]'}`}>
                    <div className="flex items-center gap-2 font-medium text-slate-100"><Icon className="h-4 w-4 text-[#00df8f]" /> {v.kyc_types[key].label}</div>
                    <p className="mt-1 text-xs text-slate-400">{v.kyc_types[key].hint}</p>
                  </button>
                );
              })}
            </div>
            <label className="block space-y-1">
              <span className="block text-xs font-medium text-slate-300">Email for verification updates</span>
              <input type="email" className={inputClass} placeholder="you@yourbusiness.in" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <div className="flex justify-end gap-2">
              {changing && <Button variant="ghost" onClick={() => setChanging(false)}>Cancel</Button>}
              <Button variant="primary" disabled={!kycType || !email.trim()} isLoading={busy === 'start'} onClick={start}>Continue</Button>
            </div>
          </div>
        )}
      </Card>

      {started && (
        <Card title="2. Verify your documents" subtitle={verified ? undefined : 'Each one is checked as soon as you submit it.'}>
          <div className="space-y-3">
            <Step title={v.kyc_type === 'BUSINESS' ? "Business's PAN" : 'Your PAN'}
              hint={v.kyc_type === 'BUSINESS' ? 'The PAN issued to the business, not a personal one.' : 'Sole proprietors: your own PAN.'}
              check={checks.pan}>
              <div className="flex gap-2">
                <input className={`${inputClass} font-mono uppercase`} placeholder="ABCDE1234F" maxLength={v.test_inputs ? 20 : 10}
                  value={pan} onChange={(e) => setPan(e.target.value.toUpperCase())} />
                <Button variant="primary" disabled={v.test_inputs ? !pan.trim() : pan.trim().length !== 10} isLoading={busy === 'pan'}
                  onClick={() => run('pan', () => portalService.verifyPan(pan.trim()))}>Verify</Button>
              </div>
            </Step>

            {v.kyc_type === 'INDIVIDUAL' && (
              <Step title="Aadhaar" hint="Through DigiLocker, the government's app: sign in, allow sharing, and you'll come straight back here." check={checks.aadhaar}>
                <Button variant="primary" leftIcon={<Fingerprint className="h-4 w-4" />} isLoading={busy === 'aadhaar'} onClick={digilocker}>
                  Verify with DigiLocker
                </Button>
              </Step>
            )}

            {v.kyc_type === 'BUSINESS' && (
              <>
                {checks.cin?.status !== 'verified' && (
                  <Step title="GSTIN" hint="If your business is GST-registered." check={checks.gst}>
                    <div className="flex gap-2">
                      <input className={`${inputClass} font-mono uppercase`} placeholder="36ABCDE1234F1Z5" maxLength={15}
                        value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())} />
                      <Button variant="primary" disabled={gstin.trim().length !== 15} isLoading={busy === 'gst'}
                        onClick={() => run('gst', () => portalService.verifyGst(gstin.trim()))}>Verify</Button>
                    </div>
                  </Step>
                )}
                {checks.gst?.status !== 'verified' ? (
                  <Step title="Or: company registration (CIN)" hint="No GSTIN? Find your company by its registered name." check={checks.cin}>
                    <div className="flex gap-2">
                      <input className={inputClass} placeholder="Registered company name" value={company}
                        onChange={(e) => { setCompany(e.target.value); setMatches(null); }} />
                      <Button variant="secondary" leftIcon={<Search className="h-4 w-4" />} disabled={company.trim().length < 3}
                        isLoading={busy === 'cin-search'} onClick={searchCompany}>Search</Button>
                    </div>
                    {matches && matches.length === 0 && <p className="text-xs text-slate-400">No company found with that name. Try the exact registered name.</p>}
                    {matches && matches.length > 0 && (
                      <div className="space-y-1.5">
                        {matches.map((m) => (
                          <div key={m.cin} className="flex flex-wrap items-center justify-between gap-2 rounded border border-[#143c49] px-3 py-2 text-xs">
                            <span>
                              <span className="text-slate-200">{m.company_name}</span>
                              <span className="ml-2 font-mono text-slate-500">{m.cin}</span>
                              {m.status && <span className="ml-2 text-slate-500">{m.status}</span>}
                            </span>
                            <Button size="sm" variant="primary" isLoading={busy === `cin-${m.cin}`}
                              onClick={() => run(`cin-${m.cin}`, () => portalService.confirmCin(m.company_name, m.cin))}>
                              This is mine
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </Step>
                ) : null}
              </>
            )}
          </div>

          {!verified && panVerified && (v.kyc_type === 'INDIVIDUAL' ? checks.aadhaar?.status !== 'verified' : !businessDone) && (
            <p className="mt-3 text-xs text-slate-400">
              {v.kyc_type === 'INDIVIDUAL' ? 'One more: verify your Aadhaar.' : 'One more: your GSTIN or company registration.'}
            </p>
          )}
          {anyPending && (
            <div className="mt-3 flex items-center justify-between gap-2 rounded-lg border border-sky-800/60 bg-sky-950/30 p-3 text-xs text-sky-100">
              <span>Some checks take a few minutes. Refresh to see the result.</span>
              <Button size="sm" variant="ghost" leftIcon={<RefreshCw className="h-3.5 w-3.5" />} onClick={load}>Refresh</Button>
            </div>
          )}
          {v.mock && !verified && (
            <p className="mt-3 text-[11px] text-slate-500">Test mode: any well-formed PAN or GSTIN passes, except one whose digits are 0000.</p>
          )}
          {v.test_inputs && !verified && (
            <p className="mt-3 text-[11px] text-slate-500">Vobiz test mode: enter TESTSUCCESS0001 to pass a check, TESTFAIL0001 to fail it.</p>
          )}
        </Card>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-800/60 bg-rose-950/40 p-3 text-sm text-rose-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}
    </div>
  );
};
