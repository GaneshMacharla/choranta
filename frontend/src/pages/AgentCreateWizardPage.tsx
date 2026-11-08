import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, BookOpen, Check, LayoutTemplate, Phone, PhoneIncoming, PhoneOutgoing, PenLine, Volume2 } from 'lucide-react';
import { agentsService } from '../services/agents';
import { clientsService } from '../services/clients';
import { catalogsService } from '../services/catalogs';
import { configurationService } from '../services/configuration';
import { AgentRequest, agentRequestsService } from '../services/agentRequests';
import { AgentConfigurationData, AgentTemplate, CallDirection, CartesiaVoice, Client, EMPTY_CALL_LIMITS, KnowledgeSource } from '../types';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Input } from '../components/common/Input';
import { Select } from '../components/common/Select';
import { NameSuggestions } from '../components/common/NameSuggestions';
import { SarvamVoicePickerModal as VoicePickerModal } from '../components/voice/SarvamVoicePickerModal';
import { AVAILABLE_LANGUAGES } from '../constants/agentOptions';

const DIRECTIONS: { value: CallDirection; label: string; hint: string; icon: React.ReactNode }[] = [
  { value: 'inbound', label: 'Inbound', hint: 'Customers call the business', icon: <PhoneIncoming className="h-4 w-4" /> },
  { value: 'outbound', label: 'Outbound', hint: 'It calls leads or customers', icon: <PhoneOutgoing className="h-4 w-4" /> },
  { value: 'both', label: 'Both', hint: 'Answers and places calls', icon: <Phone className="h-4 w-4" /> },
];

const ROLE_OPTIONS = [
  'Receptionist',
  'Appointment Booking Assistant',
  'Lead Qualification Specialist',
  'Sales Follow-up Caller',
  'Customer Support Agent',
  'Payment Reminder Agent',
  'Feedback & Survey Caller',
].map((r) => ({ value: r, label: r }));

// Client request jobs -> role and call direction
const TASK_ROLES: Record<string, string> = {
  answer_calls: 'Receptionist',
  answer_questions: 'Customer Support Agent',
  book_appointments: 'Appointment Booking Assistant',
  call_leads: 'Lead Qualification Specialist',
  send_reminders: 'Payment Reminder Agent',
  collect_feedback: 'Feedback & Survey Caller',
};
const OUTBOUND_TASKS = ['call_leads', 'send_reminders', 'collect_feedback'];
const directionFor = (tasks: string[]): CallDirection => {
  const outbound = tasks.some((t) => OUTBOUND_TASKS.includes(t));
  const inbound = tasks.some((t) => !OUTBOUND_TASKS.includes(t));
  return inbound && outbound ? 'both' : outbound ? 'outbound' : 'inbound';
};

const BLANK = '__blank__';

/** A template's ready-made setup made specific to this employee (no AI involved). */
// Default text-to-speech voice for new employees: Cartesia's Siya (Indian, multilingual)
const DEFAULT_VOICE = { id: '4459a9a5-69d6-4680-b970-e13dc51845b6', name: 'Siya', provider: 'cartesia' };

const configFromTemplate = (tpl: AgentTemplate, employeeName: string, companyName: string): AgentConfigurationData => {
  const config = JSON.parse(JSON.stringify(tpl.default_config || {})) as AgentConfigurationData;
  const company = companyName || config.business_context?.business_name || '';
  config.identity = { ...config.identity, name: employeeName || config.identity?.name, organization: company };
  config.business_context = { ...config.business_context, business_name: company };
  config.conversation = { ...config.conversation, limits: { ...EMPTY_CALL_LIMITS, ...(config.conversation?.limits || {}) } };
  config.variables = {
    ...config.variables,
    inputs: (config.variables?.inputs || []).map((v: any) => (v.name === 'company_name' && company ? { ...v, default_value: company } : v)),
  };
  return config;
};

/** Start blank: the platform's default setup, given a plain greeting, goal and call flow for this business. */
const blankSetup = (base: AgentConfigurationData, name: string, role: string, company: string, direction: CallDirection): AgentConfigurationData => ({
  ...base,
  identity: { ...base.identity, name, organization: company, persona: `friendly, helpful ${role.toLowerCase()} at ${company}` },
  business_context: { ...base.business_context, business_name: company },
  instructions: {
    ...base.instructions,
    primary_goal:
      direction === 'outbound'
        ? `Call the customer on behalf of ${company}, understand their need and agree a clear next step.`
        : `Help every caller to ${company} quickly and agree a clear next step.`,
    responsibilities: base.instructions?.responsibilities?.length
      ? base.instructions.responsibilities
      : ['Understand what the caller needs.', "Answer from the business's information only.", 'Agree a next step and confirm it.'],
    discovery_questions: ['How can I help you today?'],
    offer_points: [],
    next_step: 'Book an appointment or a callback from the team',
  },
  conversation: {
    ...base.conversation,
    greeting:
      direction === 'outbound'
        ? `Hello, this is ${name} from {{company_name}}. Is this a good time to talk?`
        : `Hello, thank you for calling {{company_name}}. This is ${name}, how can I help you?`,
    farewell: base.conversation?.farewell || 'Thank you for your time. Have a great day!',
    limits: { ...EMPTY_CALL_LIMITS, ...(base.conversation?.limits || {}) },
  },
});

/**
 * Create an AI employee on one screen: pick a template (recommended for the client's business), name it, choose
 * languages, direction, voice and knowledge, and create. The setup comes from the template - no AI drafting.
 * It starts as an unpublished draft; an admin publishes it from the employee's workspace.
 */
export const AgentCreateWizardPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestId = searchParams.get('request');
  const [fromRequest, setFromRequest] = useState<AgentRequest | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [knowledge, setKnowledge] = useState<KnowledgeSource[]>([]);
  const [clientAgentNames, setClientAgentNames] = useState<string[]>([]);

  const [clientId, setClientId] = useState(searchParams.get('client') || '');
  const [templateId, setTemplateId] = useState('');
  const [templateTouched, setTemplateTouched] = useState(false);
  const [name, setName] = useState('');
  const [role, setRole] = useState('');
  const [direction, setDirection] = useState<CallDirection>('inbound');
  const [primaryLanguage, setPrimaryLanguage] = useState('en-IN');
  const [otherLanguages, setOtherLanguages] = useState<string[]>([]);
  const [voice, setVoice] = useState<{ id: string; name: string; provider: string } | null>(null);
  const [voiceTouched, setVoiceTouched] = useState(false);
  const [isVoicePickerOpen, setIsVoicePickerOpen] = useState(false);
  const [knowledgeIds, setKnowledgeIds] = useState<string[]>([]);
  const [documentCount, setDocumentCount] = useState(0);
  const [knowledgeError, setKnowledgeError] = useState(false);
  // The employee already created by an attempt that failed part-way: trying again carries on with it
  const createdRef = useRef<{ id: string; clientId: string } | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    clientsService.list({ limit: 100 }).then((res) => setClients(res.items)).catch(() => setClients([]));
    catalogsService.listTemplates().then(setTemplates).catch(() => setTemplates([]));
  }, []);

  // Opened from Employee Requests ("Build agent"): start with what the client asked for
  useEffect(() => {
    if (!requestId) return;
    agentRequestsService
      .get(requestId)
      .then((r) => {
        // Already being built: carry on in its workspace rather than creating a second one
        if (r.agent_id && r.agent_name) {
          navigate(`/agents/${r.agent_id}`, { replace: true });
          return;
        }
        setFromRequest(r);
        setClientId(r.client_id);
        setName(r.name);
        if (r.tasks[0] && TASK_ROLES[r.tasks[0]]) setRole(TASK_ROLES[r.tasks[0]]);
        if (r.tasks.length) setDirection(directionFor(r.tasks));
        const [primary, ...others] = r.languages;
        if (primary) setPrimaryLanguage(primary);
        setOtherLanguages(others);
        if (r.voice_id) {
          setVoice({ id: r.voice_id, name: r.voice_name || r.voice_id, provider: 'sarvam' });
          setVoiceTouched(true);
        }
      })
      .catch((err) => setError(`Could not load the request: ${err?.message || 'unknown error'}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestId]);

  // The client's knowledge (all ticked) and the names its employees already use. Uploaded documents are for the team
  // to read, so they can't be ticked. Nothing from the previously selected client carries over.
  useEffect(() => {
    setKnowledge([]);
    setKnowledgeIds([]);
    setDocumentCount(0);
    setKnowledgeError(false);
    if (!clientId) {
      setClientAgentNames([]);
      return;
    }
    let stale = false;
    catalogsService
      .listClientKnowledge(clientId)
      .then((list) => {
        if (stale) return;
        const usable = list.filter((k) => k.type !== 'DOCUMENT');
        setKnowledge(usable);
        setKnowledgeIds(usable.map((k) => k.id));
        setDocumentCount(list.length - usable.length);
      })
      .catch(() => {
        if (!stale) setKnowledgeError(true);
      });
    agentsService
      .list({ client_id: clientId })
      .then((res) => {
        if (!stale) setClientAgentNames(res.items.map((a) => a.name));
      })
      .catch(() => {
        if (!stale) setClientAgentNames([]);
      });
    return () => {
      stale = true;
    };
  }, [clientId]);

  const client = clients.find((c) => c.id === clientId);
  const businessType = fromRequest?.business_type || client?.business_type || '';
  const isRecommended = (t: AgentTemplate) => !!businessType && (t.business_types || []).includes(businessType);
  const sortedTemplates = useMemo(
    () => [...templates].sort((a, b) => Number(isRecommended(b)) - Number(isRecommended(a))),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [templates, businessType]
  );
  const template = templates.find((t) => t.id === templateId) || null;

  const applyTemplate = (tpl: AgentTemplate | null) => {
    setTemplateId(tpl ? tpl.id : BLANK);
    if (tpl) {
      setRole(tpl.role || role);
      if (tpl.call_direction) setDirection(tpl.call_direction);
    }
  };

  // Pre-pick the template recommended for the client's business, until the admin picks one
  useEffect(() => {
    if (templateTouched || !templates.length || !businessType) return;
    const match = templates.find(isRecommended);
    if (match) applyTemplate(match);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates, businessType, templateTouched]);

  // Voice: Cartesia's Siya (Indian, speaks every Indian language) unless the admin or the request picks another
  useEffect(() => {
    if (!voiceTouched) setVoice(DEFAULT_VOICE);
  }, [voiceTouched]);

  const languages = [primaryLanguage, ...otherLanguages.filter((l) => l !== primaryLanguage)];
  const missing = !clientId
    ? 'Choose the client.'
    : !templateId
    ? 'Choose a template or Start blank.'
    : name.trim().length < 2
    ? 'Enter a name.'
    : templateId === BLANK && role.trim().length < 2
    ? 'Choose a role.'
    : null;

  const finish = (config: AgentConfigurationData): AgentConfigurationData => ({
    ...config,
    business_context: { ...config.business_context, call_direction: direction },
    languages: { ...config.languages, primary: primaryLanguage, supported: languages },
    voice: voice
      ? { ...config.voice, provider: voice.provider, voice_id: voice.id, language: primaryLanguage }
      : { ...config.voice, language: primaryLanguage },
    providers: voice ? { ...config.providers, tts: voice.provider } : config.providers,
    // Only this client's knowledge base is used; the template's sample knowledge is dropped
    knowledge_sources: knowledgeIds,
  });

  const create = async () => {
    if (missing || !client) return;
    setError(null);
    setIsCreating(true);
    try {
      const details = {
        name: name.trim(),
        role: (template?.role || role).trim(),
        description: template?.description || `${role} for ${client.name}.`,
      };
      let agentId: string;
      if (createdRef.current?.clientId === clientId) {
        agentId = createdRef.current.id;
        await agentsService.update(agentId, details);
      } else {
        agentId = (await agentsService.create({ client_id: clientId, ...details })).id;
        createdRef.current = { id: agentId, clientId };
      }
      let config: AgentConfigurationData;
      if (template) {
        config = configFromTemplate(template, name.trim(), client.name);
      } else {
        const base = (await configurationService.getConfiguration(agentId)).configuration;
        config = blankSetup(base, name.trim(), role, client.name, direction);
      }
      config = finish(config);
      // Saving the configuration also attaches its knowledge and tools
      await configurationService.updateConfiguration(agentId, config);
      // Starts as an unpublished draft: an admin publishes it, then the client hears it's ready when it goes live
      if (fromRequest) await agentRequestsService.link(fromRequest.id, agentId);
      navigate(`/agents/${agentId}`);
    } catch (err: any) {
      setError(err?.message || 'Could not create the employee.');
      setIsCreating(false);
    }
  };

  const pill = (active: boolean) =>
    `rounded-lg border p-3 text-left transition-colors ${active ? 'border-[#00df8f] bg-[#00df8f]/10' : 'border-[#1b3a46] hover:border-slate-500'}`;

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/agents" className="mb-2 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200">
            <ArrowLeft className="h-3.5 w-3.5" /> AI Employees
          </Link>
          <h1 className="text-xl font-bold text-slate-100">Create AI Employee</h1>
          <p className="text-xs text-slate-400">One screen. It's ready to test as soon as you create it; fine-tune everything in its workspace.</p>
        </div>
      </div>

      {fromRequest && (
        <div className="rounded-lg border border-[#0a4d39] bg-[#052b20] p-3 text-xs text-slate-200">
          Building <strong>{fromRequest.name}</strong> requested by {fromRequest.client_name}
          {fromRequest.notes ? ` · "${fromRequest.notes}"` : ''}
        </div>
      )}

      <Card title="1. Who it works for">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Select
            label="Client"
            placeholder="Select a client"
            options={clients.map((c) => ({ value: c.id, label: c.client_code ? `${c.name} · ${c.client_code}` : c.name }))}
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
          />
          <div className="space-y-2">
            <Input label="Employee name" placeholder="e.g. Priya" value={name} onChange={(e) => setName(e.target.value)} />
            <NameSuggestions current={name} exclude={clientAgentNames} onPick={setName} />
          </div>
        </div>
      </Card>

      <Card title="2. What it does" subtitle={businessType ? `Templates for ${businessType.toLowerCase().replace('_', ' ')} businesses come first.` : undefined}>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {sortedTemplates.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => {
                setTemplateTouched(true);
                applyTemplate(t);
              }}
              className={pill(templateId === t.id)}
            >
              <span className="flex items-center gap-2 text-sm font-semibold text-slate-100">
                <LayoutTemplate className="h-4 w-4 text-[#00df8f]" /> {t.name}
                {isRecommended(t) && <span className="rounded bg-[#00df8f]/15 px-1.5 text-[10px] font-semibold text-[#00df8f]">Recommended</span>}
              </span>
              <span className="mt-1 block text-[11px] text-slate-400 line-clamp-2">{t.description}</span>
            </button>
          ))}
          <button
            type="button"
            onClick={() => {
              setTemplateTouched(true);
              applyTemplate(null);
            }}
            className={pill(templateId === BLANK)}
          >
            <span className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              <PenLine className="h-4 w-4 text-slate-300" /> Start blank
            </span>
            <span className="mt-1 block text-[11px] text-slate-400">A plain setup you fill in yourself in the workspace.</span>
          </button>
        </div>
        {templateId === BLANK && (
          <div className="mt-4 max-w-sm">
            <Select label="Role" placeholder="Select a role" options={ROLE_OPTIONS} value={role} onChange={(e) => setRole(e.target.value)} />
          </div>
        )}
        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
          {DIRECTIONS.map((d) => (
            <button key={d.value} type="button" onClick={() => setDirection(d.value)} className={pill(direction === d.value)}>
              <span className="flex items-center gap-2 text-xs font-semibold text-slate-100">
                {d.icon} {d.label}
              </span>
              <span className="mt-0.5 block text-[11px] text-slate-400">{d.hint}</span>
            </button>
          ))}
        </div>
      </Card>

      <Card title="3. How it sounds">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div className="space-y-3">
            <Select label="Main language" options={AVAILABLE_LANGUAGES} value={primaryLanguage} onChange={(e) => setPrimaryLanguage(e.target.value)} />
            <div>
              <span className="mb-1.5 block text-xs font-medium text-slate-300">Also speaks (optional)</span>
              <div className="flex flex-wrap gap-1.5">
                {AVAILABLE_LANGUAGES.filter((l) => l.value !== primaryLanguage && l.value !== 'en').map((l) => {
                  const on = otherLanguages.includes(l.value);
                  return (
                    <button
                      key={l.value}
                      type="button"
                      onClick={() => setOtherLanguages(on ? otherLanguages.filter((x) => x !== l.value) : [...otherLanguages, l.value])}
                      className={`rounded-full border px-2.5 py-0.5 text-[11px] ${on ? 'border-[#00df8f] bg-[#00df8f]/15 text-[#00df8f]' : 'border-[#1b3a46] text-slate-300'}`}
                    >
                      {l.label.split(' (')[0].split(' - ')[0]}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
          <div>
            <span className="mb-1.5 block text-xs font-medium text-slate-300">Voice</span>
            <div className="flex items-center justify-between rounded-lg border border-[#1b3a46] p-3">
              <span className="flex items-center gap-2 text-sm text-slate-100">
                <Volume2 className="h-4 w-4 text-[#00df8f]" />
                {voice ? (
                  <>
                    {voice.name} <span className="text-[11px] capitalize text-slate-500">· {voice.provider}</span>
                  </>
                ) : (
                  'Picking a voice...'
                )}
              </span>
              <Button variant="secondary" size="sm" onClick={() => setIsVoicePickerOpen(true)}>
                Change
              </Button>
            </div>
            {!voiceTouched && voice && <p className="mt-1 text-[11px] text-slate-500">Recommended for this language. Press Change to listen to others.</p>}
          </div>
        </div>
      </Card>

      <Card
        title={
          <span className="flex items-center gap-2 text-sm font-semibold text-slate-100">
            <BookOpen className="h-4 w-4 text-[#00df8f]" /> 4. What it knows
          </span>
        }
        subtitle={client ? `${client.name}'s knowledge base` : 'Choose a client first'}
      >
        {documentCount > 0 && (
          <p className="mb-3 text-xs text-slate-400">
            {documentCount} uploaded document{documentCount === 1 ? '' : 's'} on{' '}
            <Link to={`/clients/${clientId}`} className="text-[#00df8f] hover:underline">
              the client's page
            </Link>{' '}
            for your team to read. The employee can't read documents, so write what it needs to know into its knowledge.
          </p>
        )}
        {knowledgeError ? (
          <p className="text-xs text-rose-300">
            Couldn't load this client's knowledge. You can create the employee and add knowledge in its workspace.
          </p>
        ) : knowledge.length === 0 ? (
          <p className="text-xs text-slate-500">
            {clientId ? (
              <>
                This client has no knowledge yet. You can add it later on{' '}
                <Link to={`/clients/${clientId}`} className="text-[#00df8f] hover:underline">
                  the client's page
                </Link>
                ; until then the employee offers a callback for questions it can't answer.
              </>
            ) : (
              'Pick a client to see its knowledge base.'
            )}
          </p>
        ) : (
          <div className="space-y-1.5">
            {knowledge.map((k) => {
              const on = knowledgeIds.includes(k.id);
              return (
                <button
                  key={k.id}
                  type="button"
                  onClick={() => setKnowledgeIds(on ? knowledgeIds.filter((x) => x !== k.id) : [...knowledgeIds, k.id])}
                  className="flex w-full items-center gap-2 rounded border border-[#102d38] px-3 py-2 text-left text-xs hover:border-slate-600"
                >
                  <span className={`flex h-4 w-4 items-center justify-center rounded border ${on ? 'border-[#00df8f] bg-[#00df8f] text-[#04130d]' : 'border-slate-600'}`}>
                    {on && <Check className="h-3 w-3" />}
                  </span>
                  <span className="text-slate-200">{k.name}</span>
                  <span className="ml-auto text-[10px] text-slate-500">{(k.content || '').length.toLocaleString()} chars</span>
                </button>
              );
            })}
          </div>
        )}
      </Card>

      {error && <p className="rounded border border-rose-800/50 bg-rose-950/40 p-3 text-xs text-rose-300">{error}</p>}

      <div className="flex items-center justify-between border-t border-[#102d38] pt-4">
        <span className="text-xs text-slate-500">{missing || 'Ready. You can test it right after creating.'}</span>
        <Button variant="primary" disabled={!!missing} isLoading={isCreating} onClick={create}>
          Create &amp; open workspace
        </Button>
      </div>

      <VoicePickerModal
        isOpen={isVoicePickerOpen}
        onClose={() => setIsVoicePickerOpen(false)}
        selectedVoiceId={voice?.id}
        language={primaryLanguage}
        provider={voice?.provider}
        onSelectVoice={(v: CartesiaVoice) => {
          setVoice({ id: v.id, name: v.name, provider: v.provider || 'sarvam' });
          setVoiceTouched(true);
          setIsVoicePickerOpen(false);
        }}
      />
    </div>
  );
};
