import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, BookOpen, CheckCircle2, Circle, Rocket, UploadCloud, Volume2 } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Select } from '../common/Select';
import { StringListEditor } from './StringListEditor';
import { CallLimitsEditor } from './CallLimitsEditor';
import { CallScriptCard } from './CallScriptCard';
import { AgentKnowledgePanel } from './AgentKnowledgePanel';
import { AgentTestingWorkbench } from '../testing/AgentTestingWorkbench';
import {
  AVAILABLE_LANGUAGES,
  LLM_PROVIDER_OPTIONS,
  STT_PROVIDER_OPTIONS,
  TTS_PROVIDER_OPTIONS,
  getProviderOptions,
} from '../../constants/agentOptions';
import { clientsService } from '../../services/clients';
import { runtimeService } from '../../services/runtime';
import { request } from '../../services/api';
import { StandardCallScript, callScriptsService } from '../../services/callScripts';
import { useAuth } from '../../context/AuthContext';
import { Agent, AgentConfigurationData, AgentVersion, Client, KnowledgeSource } from '../../types';

const FIELD =
  'block w-full rounded-md border border-[#153945] bg-[#06141a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none';

interface AgentBuildViewProps {
  /** 'configure' shows the setup cards; 'test' shows the test panel and the go-live checklist */
  view: 'configure' | 'test';
  agent: Agent;
  config: AgentConfigurationData;
  updateDraft: (fn: (prev: AgentConfigurationData) => AgentConfigurationData) => void;
  isDirty: boolean;
  versions: AgentVersion[];
  /** Saves the draft and publishes it as a new version; resolves when the new version exists */
  onPublish: () => Promise<void>;
  isPublishing: boolean;
  /** Only admins publish; others see that the draft is waiting for an admin */
  canPublish: boolean;
  knowledgeList: KnowledgeSource[];
  onToggleKnowledge: (id: string) => void;
  /** The employee's own notes/FAQs changed: refresh the attached knowledge list */
  onAgentKnowledgeChange: () => void;
  voiceLabel: string;
  onChangeVoice: () => void;
  /** Moves the employee to DEPLOYED (through the allowed status steps) */
  onGoLive: () => Promise<void>;
}

/**
 * The AI employee's workspace, shown as two tabs: Configure (its setup in call order) and Test (a test panel that
 * always tests the latest published version, next to the go-live checklist). Edit, "Publish & test", listen,
 * repeat; then Go live.
 */
export const AgentBuildView: React.FC<AgentBuildViewProps> = ({
  view, agent, config, updateDraft, isDirty, versions, onPublish, isPublishing, canPublish, knowledgeList, onToggleKnowledge,
  onAgentKnowledgeChange, voiceLabel, onChangeVoice, onGoLive,
}) => {
  const [client, setClient] = useState<Client | null>(null);
  const [sessions, setSessions] = useState<number | null>(null);
  const [goingLive, setGoingLive] = useState(false);
  const [goLiveError, setGoLiveError] = useState<string | null>(null);
  const latest = versions[0];

  useEffect(() => {
    clientsService.get(agent.client_id).then(setClient).catch(() => setClient(null));
  }, [agent.client_id]);
  // Standard call scripts (shared per template; admins edit them)
  const { user } = useAuth();
  const [standards, setStandards] = useState<StandardCallScript[] | null>(null);
  useEffect(() => {
    callScriptsService.list().then(setStandards).catch(() => setStandards([]));
  }, []);

  // Providers the server forces on every call (*_PROVIDER_OVERRIDE), whatever is saved here
  const [providerOverrides, setProviderOverrides] = useState<Record<string, string>>({});
  useEffect(() => {
    request<{ provider_overrides?: Record<string, string> }>('/runtime/mode')
      .then((res) => setProviderOverrides(res.provider_overrides || {}))
      .catch(() => {});
  }, []);
  useEffect(() => {
    runtimeService.sessionCount(agent.id).then((r) => setSessions(r.sessions)).catch(() => setSessions(null));
  }, [agent.id, latest?.id]);

  const ins = config.instructions;
  const setIns = (patch: Partial<AgentConfigurationData['instructions']>) =>
    updateDraft((prev) => ({ ...prev, instructions: { ...prev.instructions, ...patch } }));
  const setConversation = (patch: Partial<AgentConfigurationData['conversation']>) =>
    updateDraft((prev) => ({ ...prev, conversation: { ...prev.conversation, ...patch } }));
  const setProvider = (kind: 'stt' | 'llm' | 'tts', value: string) =>
    updateDraft((prev) => ({
      ...prev,
      providers: { ...prev.providers, [kind]: value },
      // A voice belongs to one provider: switching provider clears it, so a voice is picked again instead of the
      // new provider silently using its default
      ...(kind === 'tts' && value !== prev.voice.provider ? { voice: { ...prev.voice, provider: value, voice_id: null } } : {}),
    }));
  const otherLanguages = config.languages.supported.filter((l) => l !== config.languages.primary);
  // The script calls will use: the linked standard script, else this employee's own
  const linkedScript = standards?.find((st) => st.key === ins.script_source) || null;
  const script = linkedScript || ins;

  // Go-live readiness: blocking items must pass; warnings are shown but don't block
  const checks: { label: string; ok: boolean; blocking: boolean }[] = [
    { label: 'Greeting written', ok: !!config.conversation.greeting.trim(), blocking: true },
    { label: 'Goal written', ok: !!ins.primary_goal.trim(), blocking: true },
    { label: 'Call script has questions and a next step', ok: !!script.discovery_questions?.length && !!script.next_step?.trim(), blocking: true },
    { label: 'Voice chosen', ok: !!config.voice.voice_id, blocking: true },
    { label: 'All changes published', ok: !isDirty && !!latest, blocking: true },
    { label: 'Knowledge attached', ok: config.knowledge_sources.length > 0, blocking: false },
    { label: 'Tested at least once', ok: (sessions ?? 0) > 0, blocking: false },
    { label: 'Client timezone set (not UTC)', ok: !!client && client.timezone !== 'UTC', blocking: false },
  ];
  const ready = checks.every((c) => c.ok || !c.blocking);
  const isLive = agent.status === 'DEPLOYED';

  const goLive = async () => {
    setGoingLive(true);
    setGoLiveError(null);
    try {
      await onGoLive();
    } catch (err: any) {
      setGoLiveError(err?.message || 'Could not go live.');
    } finally {
      setGoingLive(false);
    }
  };

  if (view === 'test') {
    return (
      // Test panel full width, go-live checklist pinned beside it (below it on narrow screens)
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3">
          <p className="text-xs text-slate-400">
            {latest ? <>Testing version <span className="font-mono text-slate-200">v{latest.version_number}</span></> : 'Publish once to start testing'}
          </p>
          {isDirty || !latest ? (
            <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-800/50 bg-amber-950/30 p-3 text-xs text-amber-200">
              <span>
                {latest ? 'There are changes the test isn\'t using yet.' : 'Not published yet.'}
                {!canPublish && ' An admin needs to publish them.'}
              </span>
              {canPublish && (
                <Button variant="primary" size="sm" isLoading={isPublishing} onClick={onPublish}>
                  <UploadCloud className="mr-1.5 h-3.5 w-3.5" /> Publish &amp; test
                </Button>
              )}
            </div>
          ) : null}
          {latest && <AgentTestingWorkbench key={latest.id} agentId={agent.id} initialVersionId={latest.id} />}
        </div>

        <div className="lg:sticky lg:top-4 lg:self-start">
          <Card title="Go live" subtitle={isLive ? 'This employee is live.' : 'Check these, then put it to work on calls.'}>
            <ul className="space-y-1.5 text-xs">
              {checks.map((c) => (
                <li key={c.label} className="flex items-center gap-2">
                  {c.ok ? <CheckCircle2 className="h-4 w-4 text-[#00df8f]" />
                    : c.blocking ? <Circle className="h-4 w-4 text-rose-400" /> : <AlertTriangle className="h-4 w-4 text-amber-400" />}
                  <span className={c.ok ? 'text-slate-300' : c.blocking ? 'text-rose-200' : 'text-amber-200'}>{c.label}</span>
                  {!c.ok && !c.blocking && <span className="text-[10px] text-slate-500">(recommended)</span>}
                </li>
              ))}
            </ul>
            {goLiveError && <p className="mt-3 text-xs text-rose-300">{goLiveError}</p>}
            {!isLive && (
              <Button className="mt-4 w-full" variant="primary" disabled={!ready} isLoading={goingLive} onClick={goLive}>
                <Rocket className="mr-1.5 h-4 w-4" /> Go live
              </Button>
            )}
          </Card>
        </div>
      </div>
    );
  }

  return (
    // Setup in call order, full width: short cards pair up on wide screens, long ones span both columns
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
      <Card title="1. Who it is" subtitle="How it introduces itself and comes across on the call.">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <label className="block space-y-1">
            <span className="text-xs font-medium text-slate-300">Name it uses</span>
            <input className={FIELD} value={config.identity.name} placeholder="e.g. Priya"
              onChange={(e) => updateDraft((prev) => ({ ...prev, identity: { ...prev.identity, name: e.target.value } }))} />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-slate-300">Company it represents</span>
            <input className={FIELD} value={config.business_context.business_name} placeholder="e.g. ABC Academy"
              onChange={(e) =>
                updateDraft((prev) => ({
                  ...prev,
                  business_context: { ...prev.business_context, business_name: e.target.value },
                  identity: { ...prev.identity, organization: e.target.value },
                }))
              } />
            <span className="block text-[11px] text-slate-500">Said on calls and used for {'{{company_name}}'} in the greeting.</span>
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-slate-300">Persona</span>
            <textarea rows={2} className={FIELD} value={config.identity.persona} placeholder="e.g. Friendly admissions counsellor who knows every course"
              onChange={(e) => updateDraft((prev) => ({ ...prev, identity: { ...prev.identity, persona: e.target.value } }))} />
          </label>
          <label className="block space-y-1">
            <span className="text-xs font-medium text-slate-300">Tone</span>
            <textarea rows={2} className={FIELD} value={config.conversation.tone} placeholder="e.g. Warm, patient and to the point"
              onChange={(e) => setConversation({ tone: e.target.value })} />
          </label>
        </div>
      </Card>

      <Card title="2. Greeting & farewell" subtitle="Said word for word (translated to the call's language). {{company_name}} is filled in.">
        <div className="space-y-3">
          <textarea rows={2} className={FIELD} value={config.conversation.greeting} placeholder="Hello, this is Priya from {{company_name}}..."
            onChange={(e) => setConversation({ greeting: e.target.value })} />
          <input className={FIELD} value={config.conversation.farewell} placeholder="Thank you for your time. Have a great day!"
            onChange={(e) => setConversation({ farewell: e.target.value })} />
          {config.conversation.greeting.length > 160 && (
            <p className="text-[11px] text-amber-300">Long greetings feel slow on the phone; aim for one or two short sentences.</p>
          )}
        </div>
      </Card>

      <Card className="xl:col-span-2" title="3. Goal" subtitle="The one outcome this call is for, and what else it can help with.">
        <div className="space-y-4">
          <textarea rows={2} className={FIELD} value={ins.primary_goal} placeholder="Book a free demo class for interested learners."
            onChange={(e) => setIns({ primary_goal: e.target.value })} />
          <StringListEditor label="What it handles" items={ins.responsibilities} placeholder="e.g. Answer questions about courses, fees and timings"
            onChange={(items) => setIns({ responsibilities: items })} emptyText="Nothing added." />
        </div>
      </Card>

      <div className="xl:col-span-2">
        <CallScriptCard
          instructions={ins}
          setInstructions={setIns}
          standards={standards}
          onStandardSaved={(saved) => setStandards((prev) => (prev || []).map((st) => (st.key === saved.key ? saved : st)))}
          isAdmin={user?.role === 'ADMIN'}
          publishedInstructions={latest?.configuration_json?.instructions}
        />
      </div>

      <Card
        title={<span className="flex items-center gap-2 text-sm font-semibold text-slate-100"><BookOpen className="h-4 w-4 text-[#00df8f]" /> 5. Knowledge</span>}
        subtitle={`From ${client?.name || 'the client'}'s knowledge base. Ticked entries are what it answers from.`}
        action={<Link to={`/clients/${agent.client_id}`} className="text-xs text-[#00df8f] hover:underline">Manage knowledge base</Link>}
      >
        {knowledgeList.length === 0 ? (
          <p className="text-xs text-slate-500">This client has no knowledge yet; add it on the client's page.</p>
        ) : (
          <div className="space-y-1.5">
            {knowledgeList.map((k) => {
              const on = config.knowledge_sources.includes(k.id);
              return (
                <button key={k.id} type="button" onClick={() => onToggleKnowledge(k.id)}
                  className="flex w-full items-center gap-2 rounded border border-[#102d38] px-3 py-2 text-left text-xs hover:border-slate-600">
                  {on ? <CheckCircle2 className="h-4 w-4 text-[#00df8f]" /> : <Circle className="h-4 w-4 text-slate-600" />}
                  <span className="text-slate-200">{k.name}</span>
                  <span className="ml-auto text-[10px] text-slate-500">{(k.content || '').length.toLocaleString()} chars</span>
                </button>
              );
            })}
          </div>
        )}
      </Card>

      <AgentKnowledgePanel agentId={agent.id} onChange={onAgentKnowledgeChange} />

      <Card className="xl:col-span-2" title="6. Rules & handoff" subtitle="What it must always or never do, and when a person takes over.">
        <div className="space-y-4">
          <StringListEditor label="Always" items={ins.rules} placeholder="e.g. Confirm the batch timing before booking"
            onChange={(items) => setIns({ rules: items })} />
          <StringListEditor label="Never" items={ins.restrictions} placeholder="e.g. Never promise a job or salary"
            onChange={(items) => setIns({ restrictions: items })} />
          <StringListEditor label="Hand over to a person when..." items={ins.escalation_rules} placeholder="e.g. They ask about refunds: book a callback"
            onChange={(items) => setIns({ escalation_rules: items })} />
        </div>
      </Card>

      <Card title="7. Voice & language">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div>
            <span className="mb-1.5 block text-xs font-medium text-slate-300">Voice</span>
            <div className="flex items-center justify-between rounded-lg border border-[#1b3a46] p-3">
              <span className="flex items-center gap-2 text-sm text-slate-100"><Volume2 className="h-4 w-4 text-[#00df8f]" /> {voiceLabel}</span>
              <Button variant="secondary" size="sm" onClick={onChangeVoice}>Change</Button>
            </div>
          </div>
          <Select label="Main language" options={AVAILABLE_LANGUAGES} value={config.languages.primary}
            onChange={(e) => {
              const primary = e.target.value;
              updateDraft((prev) => ({
                ...prev,
                languages: { ...prev.languages, primary, supported: [primary, ...prev.languages.supported.filter((l) => l !== primary)] },
                voice: { ...prev.voice, language: primary },
              }));
            }} />
          <div>
            <span className="mb-1.5 block text-xs font-medium text-slate-300">Also speaks (when the caller does)</span>
            <div className="flex flex-wrap gap-1.5">
              {/* English is listed once (en-IN); plain 'en' shows only if an older setup already picked it */}
              {AVAILABLE_LANGUAGES.filter((l) => l.value !== config.languages.primary && (l.value !== 'en' || otherLanguages.includes('en'))).map((l) => {
                const on = otherLanguages.includes(l.value);
                return (
                  <button key={l.value} type="button"
                    onClick={() =>
                      updateDraft((prev) => {
                        const others = prev.languages.supported.filter((x) => x !== prev.languages.primary && x !== l.value);
                        return { ...prev, languages: { ...prev.languages, supported: [prev.languages.primary, ...others, ...(on ? [] : [l.value])] } };
                      })
                    }
                    className={`rounded-full border px-2.5 py-0.5 text-[11px] ${on ? 'border-[#00df8f] bg-[#00df8f]/15 text-[#00df8f]' : 'border-[#1b3a46] text-slate-300'}`}>
                    {l.label.split(' (')[0].split(' - ')[0]}
                  </button>
                );
              })}
            </div>
          </div>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-slate-300">
              Speaking speed <span className="font-mono text-[#00df8f]">{config.voice.speed.toFixed(2)}x</span>
            </span>
            <input type="range" min="0.5" max="2.0" step="0.05" value={config.voice.speed} className="w-full accent-[#00df8f]"
              onChange={(e) => updateDraft((prev) => ({ ...prev, voice: { ...prev.voice, speed: parseFloat(e.target.value) || 1.0 } }))} />
            <span className="flex justify-between text-[10px] text-slate-500"><span>Slower</span><span>Natural (1.00x)</span><span>Faster</span></span>
          </label>
        </div>
      </Card>

      <Card title="8. Call limits" subtitle="Keeps calls short and costs in check.">
        <CallLimitsEditor limits={config.conversation.limits} onChange={(limits) => setConversation({ limits })} />
      </Card>

      <details className="rounded-xl border xl:col-span-2 border-[#102d38] bg-[#071a21] p-4 text-xs">
        <summary className="cursor-pointer select-none font-semibold text-slate-300">Advanced: speech and AI providers</summary>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
          {([
            { kind: 'stt', label: 'Speech-to-text', options: STT_PROVIDER_OPTIONS },
            { kind: 'llm', label: 'AI model', options: LLM_PROVIDER_OPTIONS },
            { kind: 'tts', label: 'Text-to-speech', options: TTS_PROVIDER_OPTIONS },
          ] as const).map(({ kind, label, options }) => {
            const saved = config.providers[kind];
            const forced = providerOverrides[kind];
            return (
              <Select key={kind} label={label} options={getProviderOptions(options, saved)} value={saved}
                onChange={(e) => setProvider(kind, e.target.value)}
                helperText={forced && forced !== saved ? `Calls use ${forced}: set for every agent by the server (${kind.toUpperCase()}_PROVIDER_OVERRIDE).` : undefined} />
            );
          })}
        </div>
      </details>
    </div>
  );
};
