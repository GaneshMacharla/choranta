import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Info,
  PhoneIncoming,
  PhoneOutgoing,
  Phone,
  Sparkles,
  Volume2,
  Trash2,
} from 'lucide-react';
import { agentsService } from '../services/agents';
import { clientsService } from '../services/clients';
import { catalogsService } from '../services/catalogs';
import { configurationService } from '../services/configuration';
import {
  AgentConfigurationData,
  CallDirection,
  CartesiaVoice,
  Client,
  KnowledgeSource,
  Tool,
} from '../types';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { Input } from '../components/common/Input';
import { Select } from '../components/common/Select';
import { VoicePickerModal } from '../components/voice/VoicePickerModal';
import { StringListEditor } from '../components/agents/StringListEditor';
import { CallLimitsEditor, callLimitsValid } from '../components/agents/CallLimitsEditor';
import {
  AVAILABLE_LANGUAGES,
  LLM_PROVIDER_OPTIONS,
  STT_PROVIDER_OPTIONS,
  TTS_PROVIDER_OPTIONS,
} from '../constants/agentOptions';

const STEPS = [
  { id: 'basics', title: 'Basics', hint: 'Who it works for' },
  { id: 'describe', title: 'Describe', hint: 'What it should do' },
  { id: 'review', title: 'Review draft', hint: 'Edit the instructions' },
  { id: 'voice', title: 'Voice', hint: 'How it sounds' },
  { id: 'resources', title: 'Knowledge & tools', hint: 'Optional' },
  { id: 'limits', title: 'Call limits', hint: 'Control cost' },
  { id: 'create', title: 'Review & create', hint: 'Final check' },
] as const;

const DIRECTIONS: { value: CallDirection; label: string; hint: string; icon: React.ReactNode }[] = [
  { value: 'inbound', label: 'Inbound', hint: 'Customers call the business', icon: <PhoneIncoming className="h-4 w-4" /> },
  { value: 'outbound', label: 'Outbound', hint: 'The agent calls leads or customers', icon: <PhoneOutgoing className="h-4 w-4" /> },
  { value: 'both', label: 'Both', hint: 'Answers and places calls', icon: <Phone className="h-4 w-4" /> },
];

const TONE_OPTIONS = ['professional', 'friendly', 'warm', 'casual'].map((t) => ({
  value: t,
  label: t.charAt(0).toUpperCase() + t.slice(1),
}));

const TEXTAREA =
  'block w-full rounded-md border border-[#232736] bg-[#10121a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f]';

interface BasicsForm {
  client_id: string;
  name: string;
  role: string;
  call_direction: CallDirection;
  primary_language: string;
  supported_languages: string[];
  description: string;
  business_notes: string;
}

export const AgentCreateWizardPage: React.FC = () => {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [clients, setClients] = useState<Client[]>([]);
  const [knowledge, setKnowledge] = useState<KnowledgeSource[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);

  const [form, setForm] = useState<BasicsForm>({
    client_id: '',
    name: '',
    role: '',
    call_direction: 'inbound',
    primary_language: 'en',
    supported_languages: [],
    description: '',
    business_notes: '',
  });
  const [config, setConfig] = useState<AgentConfigurationData | null>(null);
  const [draftNotice, setDraftNotice] = useState<string | null>(null);
  const [isDrafting, setIsDrafting] = useState(false);
  const [voiceName, setVoiceName] = useState<string | null>(null);
  const [isVoicePickerOpen, setIsVoicePickerOpen] = useState(false);
  const [knowledgeIds, setKnowledgeIds] = useState<string[]>([]);
  const [toolIds, setToolIds] = useState<string[]>([]);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdAgentId, setCreatedAgentId] = useState<string | null>(null);

  useEffect(() => {
    clientsService.list({ limit: 100 }).then((res) => setClients(res.items)).catch(() => setClients([]));
    catalogsService.listKnowledge().then(setKnowledge).catch(() => setKnowledge([]));
    catalogsService.listTools().then(setTools).catch(() => setTools([]));
  }, []);

  const selectedClient = clients.find((c) => c.id === form.client_id);

  const updateConfig = (fn: (prev: AgentConfigurationData) => AgentConfigurationData) =>
    setConfig((prev) => (prev ? fn(prev) : prev));

  const stepError = useMemo((): string | null => {
    switch (STEPS[step].id) {
      case 'basics':
        if (!form.client_id) return 'Choose the client this employee works for.';
        if (form.name.trim().length < 2) return 'Enter an employee name.';
        if (form.role.trim().length < 2) return 'Enter a role.';
        return null;
      case 'describe':
        if (form.description.trim().length < 10) return 'Describe what the employee should do (at least a sentence).';
        if (!config) return 'Generate a draft to continue.';
        return null;
      case 'review':
        if (!config) return 'Generate a draft first.';
        if (config.instructions.primary_goal.trim().length < 5) return 'Add a primary goal.';
        if (config.instructions.responsibilities.length === 0) return 'Add at least one responsibility.';
        return null;
      case 'limits':
        return config && !callLimitsValid(config.conversation.limits) ? 'Fix the call limits that are out of range.' : null;
      default:
        return null;
    }
  }, [step, form, config]);

  const generateDraft = async () => {
    setError(null);
    setIsDrafting(true);
    try {
      const res = await agentsService.draftConfiguration({
        ...form,
        supported_languages: form.supported_languages.filter((l) => l !== form.primary_language),
      });
      setConfig(res.configuration);
      setDraftNotice(res.draft_source === 'fallback' ? res.message || 'A starter draft was created.' : null);
      setStep(STEPS.findIndex((s) => s.id === 'review'));
    } catch (err: any) {
      setError(err?.message || 'Could not generate a draft.');
    } finally {
      setIsDrafting(false);
    }
  };

  const handleCreate = async () => {
    if (!config) return;
    setError(null);
    setIsCreating(true);
    let agentId = createdAgentId;
    try {
      if (!agentId) {
        const created = await agentsService.create({
          client_id: form.client_id,
          name: form.name.trim(),
          role: form.role.trim(),
          description: form.description.trim(),
        });
        agentId = created.id;
        setCreatedAgentId(agentId);
      }
      await configurationService.updateConfiguration(agentId, config);
      for (const id of knowledgeIds) await catalogsService.attachKnowledge(agentId, id);
      for (const id of toolIds) await catalogsService.attachTool(agentId, id);
      navigate(`/agents/${agentId}?tab=tests`);
    } catch (err: any) {
      setError(
        agentId
          ? `The employee was created, but saving its setup failed: ${err?.message || 'unknown error'}. Retry, or open the employee to finish.`
          : err?.message || 'Could not create the employee.'
      );
    } finally {
      setIsCreating(false);
    }
  };

  const next = () => {
    if (stepError) return;
    setError(null);
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };

  const toggle = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

  // ------------------------------------------------------------------ steps

  const renderBasics = () => (
    <div className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Select
          label="Client business"
          placeholder="Select a client"
          options={clients.map((c) => ({ value: c.id, label: c.name }))}
          value={form.client_id}
          onChange={(e) => setForm({ ...form, client_id: e.target.value })}
        />
        <Input
          label="Employee name"
          placeholder="e.g. Priya – Front Desk"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <Input
          label="Role"
          placeholder="e.g. Appointment Booking Receptionist"
          value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value })}
        />
        <Select
          label="Primary spoken language"
          options={AVAILABLE_LANGUAGES}
          value={form.primary_language}
          onChange={(e) => setForm({ ...form, primary_language: e.target.value })}
        />
      </div>

      <div className="space-y-1.5">
        <span className="block text-xs font-medium text-slate-300">Call direction</span>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {DIRECTIONS.map((d) => (
            <button
              key={d.value}
              type="button"
              onClick={() => setForm({ ...form, call_direction: d.value })}
              className={`flex items-start gap-2 rounded-lg border p-3 text-left transition-colors ${
                form.call_direction === d.value
                  ? 'border-[#00df8f] bg-[#00df8f]/10 text-slate-100'
                  : 'border-[#232736] bg-[#10121a] text-slate-300 hover:border-slate-500'
              }`}
            >
              <span className="mt-0.5">{d.icon}</span>
              <span>
                <span className="block text-xs font-semibold">{d.label}</span>
                <span className="block text-[11px] text-slate-400">{d.hint}</span>
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        <span className="block text-xs font-medium text-slate-300">Also speaks (optional)</span>
        <div className="flex flex-wrap gap-1.5">
          {AVAILABLE_LANGUAGES.filter((l) => l.value !== form.primary_language).map((l) => (
            <button
              key={l.value}
              type="button"
              onClick={() => setForm({ ...form, supported_languages: toggle(form.supported_languages, l.value) })}
              className={`rounded-full border px-2.5 py-1 text-[11px] ${
                form.supported_languages.includes(l.value)
                  ? 'border-[#00df8f] bg-[#00df8f]/15 text-emerald-200'
                  : 'border-[#232736] text-slate-400 hover:border-slate-500'
              }`}
            >
              {l.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  const renderDescribe = () => (
    <div className="space-y-5">
      <div className="space-y-1.5">
        <label className="block text-xs font-medium text-slate-300">What should this employee do on calls?</label>
        <textarea
          rows={5}
          className={TEXTAREA}
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="e.g. Answer calls for Smile Dental, help patients book, reschedule or cancel appointments, and collect their name and preferred time. Hand over to the front desk for emergencies."
        />
        <p className="text-[11px] text-slate-500">
          Plain words are fine. Mention the goal, what to collect from the caller, and when to hand over to a person.
        </p>
      </div>
      <div className="space-y-1.5">
        <label className="block text-xs font-medium text-slate-300">Business notes (optional)</label>
        <textarea
          rows={3}
          className={TEXTAREA}
          value={form.business_notes}
          onChange={(e) => setForm({ ...form, business_notes: e.target.value })}
          placeholder="Opening hours, location, prices, offers, policies the agent should know."
        />
      </div>
      <div className="flex items-center gap-3">
        <Button
          type="button"
          onClick={generateDraft}
          isLoading={isDrafting}
          disabled={form.description.trim().length < 10}
          leftIcon={<Sparkles className="h-4 w-4" />}
        >
          {config ? 'Regenerate draft' : 'Generate draft with AI'}
        </Button>
        {config && <span className="text-[11px] text-emerald-300">Draft ready. Regenerating replaces your edits.</span>}
      </div>
    </div>
  );

  const renderReview = () =>
    config && (
      <div className="space-y-6">
        {draftNotice && (
          <div className="flex items-start gap-2 rounded-md border border-amber-800/60 bg-amber-950/30 p-3 text-[11px] text-amber-200">
            <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>{draftNotice} Review and complete the fields below.</span>
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Input
            label="Persona name"
            value={config.identity.name}
            onChange={(e) => updateConfig((p) => ({ ...p, identity: { ...p.identity, name: e.target.value } }))}
          />
          <Input
            label="Persona"
            value={config.identity.persona}
            onChange={(e) => updateConfig((p) => ({ ...p, identity: { ...p.identity, persona: e.target.value } }))}
          />
          <Select
            label="Tone"
            options={TONE_OPTIONS}
            value={config.conversation.tone}
            onChange={(e) => updateConfig((p) => ({ ...p, conversation: { ...p.conversation, tone: e.target.value } }))}
          />
        </div>
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-slate-300">Primary goal</label>
          <textarea
            rows={2}
            className={TEXTAREA}
            value={config.instructions.primary_goal}
            onChange={(e) =>
              updateConfig((p) => ({ ...p, instructions: { ...p.instructions, primary_goal: e.target.value } }))
            }
          />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">Greeting (first sentence spoken)</label>
            <textarea
              rows={2}
              className={`${TEXTAREA} font-mono`}
              value={config.conversation.greeting}
              onChange={(e) =>
                updateConfig((p) => ({ ...p, conversation: { ...p.conversation, greeting: e.target.value } }))
              }
            />
          </div>
          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">Farewell</label>
            <textarea
              rows={2}
              className={`${TEXTAREA} font-mono`}
              value={config.conversation.farewell}
              onChange={(e) =>
                updateConfig((p) => ({ ...p, conversation: { ...p.conversation, farewell: e.target.value } }))
              }
            />
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {(
            [
              ['responsibilities', 'Responsibilities', 'e.g. Find a convenient appointment slot'],
              ['rules', 'Rules to follow', 'e.g. Ask one question at a time'],
              ['restrictions', 'Never do', 'e.g. Never give medical advice'],
              ['escalation_rules', 'Hand over to a human when', 'e.g. The caller reports an emergency'],
            ] as const
          ).map(([key, label, placeholder]) => (
            <StringListEditor
              key={key}
              label={label}
              placeholder={placeholder}
              items={config.instructions[key]}
              onChange={(items) => updateConfig((p) => ({ ...p, instructions: { ...p.instructions, [key]: items } }))}
            />
          ))}
        </div>
        <div className="space-y-1.5">
          <span className="block text-xs font-medium text-slate-300">Details collected from the caller</span>
          {config.variables.outputs.length === 0 ? (
            <p className="text-[11px] text-slate-500">None. You can add variables later in the Variables tab.</p>
          ) : (
            <div className="divide-y divide-[#1b1f2d] rounded-md border border-[#1b1f2d] bg-[#0c0e14]">
              {config.variables.outputs.map((v, idx) => (
                <div key={v.name} className="flex items-center justify-between gap-2 p-2.5 text-xs">
                  <div className="min-w-0">
                    <span className="font-mono text-emerald-300">{v.name}</span>
                    <span className="text-slate-400"> · {v.description}</span>
                  </div>
                  <button
                    type="button"
                    className="text-slate-500 hover:text-rose-400 p-1"
                    title="Remove"
                    onClick={() =>
                      updateConfig((p) => ({
                        ...p,
                        variables: { ...p.variables, outputs: p.variables.outputs.filter((_, i) => i !== idx) },
                      }))
                    }
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );

  const renderVoice = () =>
    config && (
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[#232736] bg-[#10121a] p-4">
          <Volume2 className="h-5 w-5 text-[#00df8f]" />
          <div className="flex-1 min-w-0">
            <div className="text-xs font-semibold text-slate-100">{voiceName || config.voice.voice_id || 'Default voice'}</div>
            <div className="text-[11px] text-slate-400">
              {config.voice.voice_id ? `${config.voice.provider} · ${config.voice.language}` : 'The provider default voice is used until you pick one.'}
            </div>
          </div>
          <Button type="button" variant="secondary" size="sm" onClick={() => setIsVoicePickerOpen(true)}>
            Choose voice
          </Button>
        </div>
        <div className="space-y-1.5">
          <label className="block text-xs font-medium text-slate-300">Speaking speed: {config.voice.speed.toFixed(2)}×</label>
          <input
            type="range"
            min={0.5}
            max={2}
            step={0.05}
            value={config.voice.speed}
            onChange={(e) => updateConfig((p) => ({ ...p, voice: { ...p.voice, speed: Number(e.target.value) } }))}
            className="w-full accent-[#00df8f]"
          />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Select
            label="Speech-to-text"
            options={STT_PROVIDER_OPTIONS}
            value={config.providers.stt}
            onChange={(e) => updateConfig((p) => ({ ...p, providers: { ...p.providers, stt: e.target.value } }))}
          />
          <Select
            label="AI model"
            options={LLM_PROVIDER_OPTIONS}
            value={config.providers.llm}
            onChange={(e) => updateConfig((p) => ({ ...p, providers: { ...p.providers, llm: e.target.value } }))}
          />
          <Select
            label="Text-to-speech"
            options={TTS_PROVIDER_OPTIONS}
            value={config.providers.tts}
            onChange={(e) => updateConfig((p) => ({ ...p, providers: { ...p.providers, tts: e.target.value } }))}
          />
        </div>
      </div>
    );

  const renderChecklist = <T extends { id: string; name: string; description?: string | null }>(
    title: string,
    items: T[],
    selected: string[],
    setSelected: (ids: string[]) => void,
    empty: string
  ) => (
    <div className="space-y-2">
      <span className="block text-xs font-medium text-slate-300">{title}</span>
      {items.length === 0 ? (
        <p className="text-[11px] text-slate-500">{empty}</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {items.map((item) => (
            <label
              key={item.id}
              className={`flex cursor-pointer items-start gap-2 rounded-md border p-3 text-xs ${
                selected.includes(item.id) ? 'border-[#00df8f] bg-[#00df8f]/10' : 'border-[#232736] bg-[#10121a]'
              }`}
            >
              <input
                type="checkbox"
                className="mt-0.5 accent-[#00df8f]"
                checked={selected.includes(item.id)}
                onChange={() => setSelected(toggle(selected, item.id))}
              />
              <span>
                <span className="block font-semibold text-slate-100">{item.name}</span>
                {item.description && <span className="block text-[11px] text-slate-400">{item.description}</span>}
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  );

  const renderResources = () => (
    <div className="space-y-6">
      <p className="text-[11px] text-slate-400">
        Optional. Attach what the agent needs to look things up or take actions during a call. You can change this later.
      </p>
      {renderChecklist('Knowledge sources', knowledge, knowledgeIds, setKnowledgeIds, 'No knowledge sources in the catalog yet.')}
      {renderChecklist('Tools', tools.filter((t) => t.enabled), toolIds, setToolIds, 'No tools in the catalog yet.')}
    </div>
  );

  const renderLimits = () =>
    config && (
      <CallLimitsEditor
        limits={config.conversation.limits}
        onChange={(limits) => updateConfig((p) => ({ ...p, conversation: { ...p.conversation, limits } }))}
      />
    );

  const renderSummary = () => {
    if (!config) return null;
    const limits = config.conversation.limits;
    const rows: [string, React.ReactNode][] = [
      ['Client', selectedClient?.name || '—'],
      ['Employee', `${form.name} · ${form.role}`],
      ['Calls', DIRECTIONS.find((d) => d.value === form.call_direction)?.label],
      ['Languages', [form.primary_language, ...form.supported_languages].join(', ')],
      ['Goal', config.instructions.primary_goal],
      ['Greeting', config.conversation.greeting],
      ['Instructions', `${config.instructions.responsibilities.length} responsibilities · ${config.instructions.rules.length} rules · ${config.instructions.restrictions.length} restrictions`],
      ['Voice', `${voiceName || config.voice.voice_id || 'Default'} · ${config.voice.speed.toFixed(2)}×`],
      ['Providers', `${config.providers.stt} → ${config.providers.llm} → ${config.providers.tts}`],
      ['Knowledge & tools', `${knowledgeIds.length} knowledge · ${toolIds.length} tools`],
      [
        'Call limits',
        [
          limits.max_call_duration_s ? `max ${limits.max_call_duration_s}s` : 'default duration',
          limits.end_call_phrases.length ? `${limits.end_call_phrases.length} end-call phrases` : null,
        ]
          .filter(Boolean)
          .join(' · '),
      ],
    ];
    return (
      <div className="space-y-4">
        <dl className="divide-y divide-[#1b1f2d] rounded-md border border-[#1b1f2d] bg-[#0c0e14] text-xs">
          {rows.map(([label, value]) => (
            <div key={label} className="grid grid-cols-3 gap-3 p-3">
              <dt className="text-slate-400">{label}</dt>
              <dd className="col-span-2 text-slate-100 break-words">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="text-[11px] text-slate-400">
          After creating, you'll land on the Tests tab to try the employee. Every setting stays editable on its page.
        </p>
      </div>
    );
  };

  const body = [renderBasics, renderDescribe, renderReview, renderVoice, renderResources, renderLimits, renderSummary][step]();
  const isLast = step === STEPS.length - 1;
  const isDescribe = STEPS[step].id === 'describe';

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Link to="/agents" className="text-slate-400 hover:text-slate-200">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Create AI Employee</h1>
          <p className="text-xs text-slate-400">Set up a voice agent from scratch in a few guided steps.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-6">
        <ol className="flex lg:flex-col gap-1 overflow-x-auto">
          {STEPS.map((s, idx) => {
            return (
              <li key={s.id}>
                <button
                  type="button"
                  disabled={idx > step}
                  onClick={() => setStep(idx)}
                  className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs whitespace-nowrap ${
                    idx === step ? 'bg-[#00df8f]/10 text-slate-100' : 'text-slate-400 hover:text-slate-200 disabled:hover:text-slate-400'
                  }`}
                >
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] ${
                      idx < step ? 'border-[#00df8f] bg-[#00df8f] text-black' : idx === step ? 'border-[#00df8f] text-[#00df8f]' : 'border-slate-600'
                    }`}
                  >
                    {idx < step ? <Check className="h-3 w-3" /> : idx + 1}
                  </span>
                  <span>
                    <span className="block font-medium">{s.title}</span>
                    <span className="hidden lg:block text-[10px] text-slate-500">{s.hint}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        <Card title={STEPS[step].title} subtitle={STEPS[step].hint}>
          <div className="space-y-6">
            {body}

            {error && (
              <div className="rounded-md border border-rose-800/60 bg-rose-950/30 p-3 text-xs text-rose-200">
                {error}
                {createdAgentId && (
                  <Link to={`/agents/${createdAgentId}`} className="ml-2 underline">
                    Open employee
                  </Link>
                )}
              </div>
            )}

            <div className="flex items-center justify-between border-t border-[#1b1f2d] pt-4">
              <Button
                type="button"
                variant="ghost"
                onClick={() => (step === 0 ? navigate('/agents') : setStep(step - 1))}
                leftIcon={<ArrowLeft className="h-4 w-4" />}
              >
                {step === 0 ? 'Cancel' : 'Back'}
              </Button>
              <div className="flex items-center gap-3">
                {stepError && !isDescribe && <span className="text-[11px] text-amber-300">{stepError}</span>}
                {isLast ? (
                  <Button type="button" onClick={handleCreate} isLoading={isCreating} leftIcon={<Check className="h-4 w-4" />}>
                    {createdAgentId ? 'Retry saving' : 'Create employee'}
                  </Button>
                ) : isDescribe && !config ? null : (
                  <Button
                    type="button"
                    onClick={next}
                    disabled={!!stepError}
                    rightIcon={<ArrowRight className="h-4 w-4" />}
                  >
                    Next
                  </Button>
                )}
              </div>
            </div>
          </div>
        </Card>
      </div>

      <VoicePickerModal
        isOpen={isVoicePickerOpen}
        onClose={() => setIsVoicePickerOpen(false)}
        selectedVoiceId={config?.voice.voice_id}
        onSelectVoice={(voice: CartesiaVoice) => {
          updateConfig((p) => ({
            ...p,
            voice: {
              ...p.voice,
              provider: voice.provider || 'cartesia',
              voice_id: voice.id,
              language: voice.language || p.voice.language || 'en',
            },
          }));
          setVoiceName(voice.name);
          setIsVoicePickerOpen(false);
        }}
      />
    </div>
  );
};

export default AgentCreateWizardPage;
