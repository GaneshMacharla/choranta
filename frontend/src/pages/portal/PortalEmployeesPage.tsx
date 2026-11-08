import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  BedDouble,
  Bot,
  Briefcase,
  Building2,
  Check,
  CheckCircle,
  FileText,
  Home,
  Hospital,
  Lock,
  PartyPopper,
  Plus,
  Scissors,
  Send,
  Stethoscope,
  GraduationCap,
  Store,
  Upload,
  UtensilsCrossed,
} from 'lucide-react';
import { Card } from '../../components/common/Card';
import { Button } from '../../components/common/Button';
import { LoadingState } from '../../components/common/LoadingState';
import { ErrorState } from '../../components/common/ErrorState';
import { BrowserCallTester } from '../../components/testing/BrowserCallTester';
import { fmtDate } from '../../components/billing/PlanUsageBar';
import { AgentRequest, portalAgentRequestsService as api, RequestOption } from '../../services/agentRequests';
import { portalKnowledge } from '../../services/knowledge';
// import { QualificationSettings } from '../../components/portal/QualificationSettings';

const NAME_MAX = 40;
const NAME_IDEAS = ['Priya', 'Arjun', 'Meera', 'Rahul', 'Anjali', 'Kiran'];

const BUSINESS_ICONS: Record<string, React.ReactNode> = {
  CLINIC: <Stethoscope className="h-5 w-5" />,
  HOSPITAL: <Hospital className="h-5 w-5" />,
  SALON: <Scissors className="h-5 w-5" />,
  REAL_ESTATE: <Home className="h-5 w-5" />,
  HOTEL: <BedDouble className="h-5 w-5" />,
  RESTAURANT: <UtensilsCrossed className="h-5 w-5" />,
  CORPORATE: <Briefcase className="h-5 w-5" />,
  COACHING: <GraduationCap className="h-5 w-5" />,
  OTHER: <Store className="h-5 w-5" />,
};

// ------------------------------------------------------------------ request progress

const PROGRESS = ['Received', 'Being set up', 'Try it', 'Ready'];

const trialLeft = (r: AgentRequest) => r.status === 'CLIENT_TRIAL' && r.trial_calls_used < r.trial_calls_allowed;

const RequestProgress: React.FC<{ request: AgentRequest }> = ({ request: r }) => {
  if (r.status === 'REJECTED' || r.status === 'CANCELLED') {
    return (
      <p className={`text-xs ${r.status === 'REJECTED' ? 'text-rose-300' : 'text-slate-500'}`}>
        {r.status === 'REJECTED' ? `We couldn't set this one up${r.admin_note ? `: ${r.admin_note}` : '.'}` : 'You cancelled this request.'}
      </p>
    );
  }
  const reached = r.status === 'COMPLETED' ? 3 : r.status === 'CLIENT_TRIAL' ? 2 : r.status === 'IN_PROGRESS' ? 1 : 0;
  return (
    <div className="space-y-2">
      <ol className="flex flex-wrap items-center gap-2">
        {PROGRESS.map((label, i) => (
          <li key={label} className="flex items-center gap-2">
            <span
              className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${
                i <= reached ? 'bg-[#00df8f] text-[#04110c]' : 'border border-[#1e4e5e] text-slate-500'
              }`}
            >
              {i < reached || reached === PROGRESS.length - 1 ? <Check className="h-3 w-3" /> : i + 1}
            </span>
            <span className={`text-xs ${i <= reached ? 'text-slate-200' : 'text-slate-500'}`}>{label}</span>
            {i < PROGRESS.length - 1 && <span className={`h-px w-6 ${i < reached ? 'bg-[#00df8f]' : 'bg-[#1e4e5e]'}`} />}
          </li>
        ))}
      </ol>
      <p className="text-xs text-slate-400">
        {r.status === 'PENDING' && "We've got your request. Our team will contact you soon."}
        {r.status === 'IN_PROGRESS' && 'Our team is setting it up now.'}
        {r.status === 'CLIENT_TRIAL' &&
          (trialLeft(r)
            ? `${r.name} is ready for you to try. Talk to it below.`
            : `Thanks for trying ${r.name}. Our team will contact you soon.`)}
        {r.status === 'COMPLETED' && (
          <>
            {r.name} is ready! Next, connect it to a phone number under{' '}
            <Link to="/portal/numbers" className="text-[#00df8f] hover:underline">Phone numbers</Link>.
          </>
        )}
      </p>
    </div>
  );
};

// ------------------------------------------------------------------ page

/** Client portal: ask Choranta for an AI employee with just three answers; Choranta sets up the rest. */
export const PortalEmployeesPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const welcome = searchParams.get('welcome') === 'plan';
  const [requests, setRequests] = useState<AgentRequest[] | null>(null);
  const [canRequest, setCanRequest] = useState(false);
  const [businessTypes, setBusinessTypes] = useState<RequestOption[]>([]);
  const [languageOptions, setLanguageOptions] = useState<RequestOption[]>([]);
  const [languages, setLanguages] = useState<string[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [companyName, setCompanyName] = useState('');
  const [businessType, setBusinessType] = useState('');
  const [name, setName] = useState('');
  // First AI employee only: files about the business our team builds it from
  const [needsDocuments, setNeedsDocuments] = useState(false);
  const [uploaded, setUploaded] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = () =>
    Promise.all([api.list(), api.options()])
      .then(([list, options]) => {
        setRequests(list.requests);
        setCanRequest(list.can_request);
        setBusinessTypes(options.business_types);
        setLanguageOptions(options.languages);
        setNeedsDocuments(options.needs_documents);
        setCompanyName((current) => current || options.company_name);
        setBusinessType((current) => current || (options.business_type !== 'OTHER' ? options.business_type : ''));
        // Nothing requested yet (or just bought a plan): open the form straight away
        if (list.can_request && (list.requests.length === 0 || welcome)) setCreating(true);
      })
      .catch((err) => setLoadError(err.message || 'Could not load your AI employees.'));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const company = companyName.trim();
  const trimmed = name.trim();
  const problem =
    company.length < 2
      ? 'Enter your company name.'
      : !businessType
      ? 'Choose your type of business.'
      : languages.length === 0
      ? 'Choose the languages your customers speak.'
      : trimmed.length < 2
      ? 'Give your AI employee a name.'
      : needsDocuments && uploaded.length === 0
      ? 'Upload at least one file about your business.'
      : null;

  const upload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      const added = await portalKnowledge.upload(Array.from(files));
      setUploaded((current) => [...current, ...added.map((e) => e.name)]);
    } catch (err: any) {
      setError(err.message || 'Could not upload the files. Please try again.');
    } finally {
      setUploading(false);
    }
  };

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const created = await api.create({ company_name: company, business_type: businessType, name: trimmed, languages });
      setNotice(`Done! We've received your request for ${created.name}. Our team will contact you soon. You can follow its progress below.`);
      setCreating(false);
      setName('');
      setLanguages([]);
      if (welcome) setSearchParams({}, { replace: true });
      await load();
    } catch (err: any) {
      setError(err.message || 'Something went wrong. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  if (loadError) return <ErrorState message={loadError} onRetry={load} />;
  if (!requests) return <LoadingState message="Loading your AI employees..." />;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold">
            <Bot className="h-5 w-5 text-[#00df8f]" /> AI Employees
          </h1>
          <p className="mt-1 text-sm text-slate-400">An AI employee answers and makes phone calls for your business, day and night.</p>
        </div>
        {canRequest && !creating && (
          <Button variant="primary" leftIcon={<Plus className="h-4 w-4" />} onClick={() => { setNotice(null); setError(null); setCreating(true); }}>
            New AI employee
          </Button>
        )}
      </div>

      {welcome && creating && (
        <div className="flex items-start gap-3 rounded-lg border border-[#0a4d39] bg-[#052b20]/70 p-4 text-sm text-emerald-100">
          <PartyPopper className="mt-0.5 h-5 w-5 shrink-0 text-[#00df8f]" />
          <div>
            <p className="font-semibold">Your plan is active!</p>
            <p className="text-emerald-200/80">Now let's create your first AI employee. It takes less than a minute.</p>
          </div>
        </div>
      )}

      {notice && (
        <div className="flex items-start gap-2 rounded-lg border border-emerald-800/60 bg-emerald-950/30 p-3 text-sm text-emerald-200">
          <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" /> {notice}
        </div>
      )}

      {!canRequest ? (
        <Card>
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <Lock className="h-8 w-8 text-slate-500" />
            <p className="text-base text-slate-200">One step first: choose a plan or buy credits</p>
            <p className="max-w-md text-sm text-slate-400">Your AI employee uses credits for every call it handles. Once you've paid, come back here to create it. It only takes a minute.</p>
            <div className="flex gap-2">
              <Link to="/portal/plans"><Button variant="primary">See plans</Button></Link>
              <Link to="/portal/billing"><Button variant="secondary">Buy credits</Button></Link>
            </div>
          </div>
        </Card>
      ) : creating ? (
        <Card title="Create your AI employee" subtitle={needsDocuments ? 'Four quick answers and your business files. Our team sets up everything else.' : 'Just four quick answers. Our team sets up everything else.'}>
          <div className="space-y-6">
            <label className="block space-y-2">
              <span className="flex items-center gap-2 text-sm font-medium text-slate-200">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#00df8f] text-[11px] font-bold text-[#04110c]">1</span>
                What is your company called?
              </span>
              <div className="relative">
                <Building2 className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-slate-500" />
                <input
                  className="w-full rounded-lg border border-[#1e4e5e] bg-[#06141a] py-3 pl-9 pr-4 text-base text-slate-100 placeholder-slate-600 focus:border-[#00df8f] focus:outline-none"
                  placeholder="e.g. Smile Dental Care"
                  maxLength={100}
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                />
              </div>
            </label>

            <div className="space-y-2">
              <span className="flex items-center gap-2 text-sm font-medium text-slate-200">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#00df8f] text-[11px] font-bold text-[#04110c]">2</span>
                What kind of business is it?
              </span>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {businessTypes.map((t) => {
                  const on = businessType === t.id;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      onClick={() => setBusinessType(t.id)}
                      className={`flex flex-col items-center gap-1.5 rounded-lg border px-2 py-3 text-sm transition-colors ${
                        on ? 'border-[#00df8f] bg-[#00df8f]/10 text-[#00df8f]' : 'border-[#1e4e5e] text-slate-300 hover:border-[#2a6577]'
                      }`}
                    >
                      {BUSINESS_ICONS[t.id] || <Store className="h-5 w-5" />}
                      {t.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="space-y-2">
              <span className="flex items-center gap-2 text-sm font-medium text-slate-200">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#00df8f] text-[11px] font-bold text-[#04110c]">3</span>
                Which languages do your customers speak?
              </span>
              <p className="text-xs text-slate-500">
                Tap all that apply. The first one you pick is the main language; your AI employee switches to the others when a caller uses them.
              </p>
              <div className="flex flex-wrap gap-2">
                {languageOptions.map((l) => {
                  const position = languages.indexOf(l.id);
                  const on = position >= 0;
                  return (
                    <button
                      key={l.id}
                      type="button"
                      onClick={() => setLanguages(on ? languages.filter((x) => x !== l.id) : [...languages, l.id])}
                      className={`flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
                        on ? 'border-[#00df8f] bg-[#00df8f]/10 text-[#00df8f]' : 'border-[#1e4e5e] text-slate-300 hover:border-[#2a6577]'
                      }`}
                    >
                      {on && <Check className="h-3.5 w-3.5" />}
                      {l.label}
                      {position === 0 && languages.length > 1 && <span className="text-[10px] uppercase tracking-wide opacity-80">main</span>}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="space-y-2">
              <span className="flex items-center gap-2 text-sm font-medium text-slate-200">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#00df8f] text-[11px] font-bold text-[#04110c]">4</span>
                What should we call your AI employee?
              </span>
              <input
                className="w-full rounded-lg border border-[#1e4e5e] bg-[#06141a] px-4 py-3 text-base text-slate-100 placeholder-slate-600 focus:border-[#00df8f] focus:outline-none"
                placeholder="Type a name"
                maxLength={NAME_MAX}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                Need an idea?
                {NAME_IDEAS.map((idea) => (
                  <button
                    key={idea}
                    type="button"
                    onClick={() => setName(idea)}
                    className="rounded-full border border-[#1e4e5e] px-3 py-1 text-slate-200 hover:border-[#00df8f] hover:text-[#00df8f]"
                  >
                    {idea}
                  </button>
                ))}
              </div>
              {trimmed.length >= 2 && (
                <div className="rounded-lg bg-[#06141a] p-3 text-sm text-slate-300">
                  Callers will hear:{' '}
                  <span className="italic text-[#00df8f]">
                    "Hello! This is {trimmed}{company.length >= 2 ? ` from ${company}` : ''}. How can I help you today?"
                  </span>
                </div>
              )}
            </div>

            {needsDocuments && (
              <div className="space-y-2">
                <span className="flex items-center gap-2 text-sm font-medium text-slate-200">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#00df8f] text-[11px] font-bold text-[#04110c]">5</span>
                  Upload files about your business
                </span>
                <p className="text-xs text-slate-500">
                  Your brochure, price or fee list, services, timings, FAQs: anything your AI employee should know. PDF, Word, Excel,
                  text or images. Our team builds your AI employee from these.
                  {/* Knowledge base hidden from clients for now:
                  {' '}You can add more later under{' '}
                  <Link to="/portal/knowledge" className="text-[#00df8f] hover:underline">Knowledge</Link>. */}
                </p>
                <label
                  className={`flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-5 text-sm transition-colors ${
                    uploading ? 'border-[#1e4e5e] text-slate-500' : 'border-[#2a6577] text-slate-300 hover:border-[#00df8f] hover:text-[#00df8f]'
                  }`}
                >
                  <Upload className="h-4 w-4" />
                  {uploading ? 'Uploading…' : uploaded.length ? 'Add more files' : 'Choose files'}
                  <input
                    type="file"
                    multiple
                    className="hidden"
                    disabled={uploading}
                    onChange={(e) => {
                      upload(e.target.files);
                      e.target.value = '';
                    }}
                  />
                </label>
                {uploaded.length > 0 && (
                  <ul className="space-y-1">
                    {uploaded.map((f, i) => (
                      <li key={`${f}-${i}`} className="flex items-center gap-2 text-xs text-slate-300">
                        <FileText className="h-3.5 w-3.5 text-[#00df8f]" /> {f}
                        <Check className="h-3.5 w-3.5 text-[#00df8f]" />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            <div className="rounded-lg border border-[#143c49] p-3 text-xs text-slate-400">
              <span className="font-medium text-slate-300">What happens next: </span>
              our team will contact you soon, then set up its voice and what it says and does. You'll see it marked <span className="text-slate-200">Ready</span> here
              and get a notification. Then connect it to a phone number and it starts taking calls.
            </div>

            {error && (
              <div className="flex items-start gap-2 rounded-lg border border-rose-800/50 bg-rose-950/40 p-3 text-sm text-rose-200">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#102d38] pt-4">
              {requests.length > 0 ? (
                <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
              ) : <span />}
              <div className="flex items-center gap-3">
                {problem && <span className="hidden text-xs text-slate-500 sm:inline">{problem}</span>}
                <Button variant="primary" isLoading={saving} disabled={!!problem || saving} onClick={submit} leftIcon={<Send className="h-4 w-4" />}>
                  Send request
                </Button>
              </div>
            </div>
          </div>
        </Card>
      ) : null}

      {requests.length > 0 && (
        <Card title="Your AI employees" noPadding>
          <ul className="divide-y divide-[#102d38]">
            {requests.map((r) => (
              <li key={r.id} className="space-y-2 px-5 py-4">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-base font-semibold text-slate-100">{r.name}</span>
                  <span className="text-xs text-slate-500">Requested {fmtDate(r.created_at)}</span>
                </div>
                {(r.company_name || r.business_type_label || r.language_labels.length > 0) && (
                  <p className="text-xs text-slate-400">
                    {[
                      r.company_name,
                      r.business_type_label,
                      r.language_labels.length ? `Speaks ${r.language_labels.join(', ')}` : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                )}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <RequestProgress request={r} />
                  {r.status === 'PENDING' && (
                    <button
                      type="button"
                      className="text-xs text-slate-500 hover:text-rose-300"
                      onClick={async () => {
                        if (!window.confirm(`Cancel the request for ${r.name}?`)) return;
                        try {
                          await api.cancel(r.id);
                          await load();
                        } catch (err: any) {
                          setError(err.message);
                        }
                      }}
                    >
                      Cancel request
                    </button>
                  )}
                </div>
                {trialLeft(r) && (
                  <div className="rounded-lg border border-[#143c49] bg-[#06141a]">
                    <BrowserCallTester
                      ready
                      clientMode
                      clientIntro={`You have ${r.trial_calls_allowed - r.trial_calls_used === 1 ? 'one free call' : `${r.trial_calls_allowed - r.trial_calls_used} free calls`} of up to ${r.trial_max_minutes} minutes. Allow your microphone when asked; headphones work best.`}
                      onStart={(offer) => api.startTrialCall(r.id, offer)}
                      onHangUp={(callId) => api.hangUpTrialCall(r.id, callId)}
                      onEnded={() => {
                        load().catch(() => {});
                      }}
                    />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* Hidden from clients for now: leads use the default (interested or asked for a callback) */}
      {/* <QualificationSettings /> */}
    </div>
  );
};
