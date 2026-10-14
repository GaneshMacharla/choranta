import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, BookOpen, CheckCircle2, Circle, Rocket, UploadCloud, Volume2 } from 'lucide-react';
import { Card } from '../common/Card';
import { Button } from '../common/Button';
import { Select } from '../common/Select';
import { StringListEditor } from './StringListEditor';
import { CallLimitsEditor } from './CallLimitsEditor';
import { AgentTestingWorkbench } from '../testing/AgentTestingWorkbench';
import { AVAILABLE_LANGUAGES } from '../../constants/agentOptions';
import { clientsService } from '../../services/clients';
import { runtimeService } from '../../services/runtime';
import { Agent, AgentConfigurationData, AgentVersion, Client, KnowledgeSource } from '../../types';

const FIELD =
  'block w-full rounded-md border border-[#153945] bg-[#06141a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:outline-none';

interface AgentBuildViewProps {
  agent: Agent;
  config: AgentConfigurationData;
  updateDraft: (fn: (prev: AgentConfigurationData) => AgentConfigurationData) => void;
  isDirty: boolean;
  versions: AgentVersion[];
  /** Saves the draft and publishes it as a new version; resolves when the new version exists */
  onPublish: () => Promise<void>;
  isPublishing: boolean;
  knowledgeList: KnowledgeSource[];
  onToggleKnowledge: (id: string) => void;
  voiceLabel: string;
  onChangeVoice: () => void;
  /** Moves the employee to DEPLOYED (through the allowed status steps) */
  onGoLive: () => Promise<void>;
}

/**
 * The AI employee's workspace: its setup in call order on the left, and a test panel on the right that always
 * tests the latest published version. Edit, "Publish & test", listen, repeat; then Go live.
 */
export const AgentBuildView: React.FC<AgentBuildViewProps> = ({
  agent, config, updateDraft, isDirty, versions, onPublish, isPublishing, knowledgeList, onToggleKnowledge,
  voiceLabel, onChangeVoice, onGoLive,
}) => {
  const [client, setClient] = useState<Client | null>(null);
  const [sessions, setSessions] = useState<number | null>(null);
  const [goingLive, setGoingLive] = useState(false);
  const [goLiveError, setGoLiveError] = useState<string | null>(null);
  const latest = versions[0];

  useEffect(() => {
    clientsService.get(agent.client_id).then(setClient).catch(() => setClient(null));
  }, [agent.client_id]);
  useEffect(() => {
    runtimeService.sessionCount(agent.id).then((r) => setSessions(r.sessions)).catch(() => setSessions(null));
  }, [agent.id, latest?.id]);

  const ins = config.instructions;
  const setIns = (patch: Partial<AgentConfigurationData['instructions']>) =>
    updateDraft((prev) => ({ ...prev, instructions: { ...prev.instructions, ...patch } }));
  const setConversation = (patch: Partial<AgentConfigurationData['conversation']>) =>
    updateDraft((prev) => ({ ...prev, conversation: { ...prev.conversation, ...patch } }));

  // Go-live readiness: blocking items must pass; warnings are shown but don't block
  const checks: { label: string; ok: boolean; blocking: boolean }[] = [
    { label: 'Greeting written', ok: !!config.conversation.greeting.trim(), blocking: true },
    { label: 'Goal written', ok: !!ins.primary_goal.trim(), blocking: true },
    { label: 'Call script has questions and a next step', ok: !!ins.discovery_questions?.length && !!ins.next_step?.trim(), blocking: true },
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

  return (
    <div className="grid grid-cols-1 gap-6 2xl:grid-cols-2">
      {/* SETUP, IN CALL ORDER */}
      <div className="space-y-5">
        <Card title="1. Greeting & farewell" subtitle="Said word for word (translated to the call's language). {{company_name}} is filled in.">
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

        <Card title="2. Goal" subtitle="The one outcome this call is for.">
          <textarea rows={2} className={FIELD} value={ins.primary_goal} placeholder="Book a free demo class for interested learners."
            onChange={(e) => setIns({ primary_goal: e.target.value })} />
        </Card>

        <Card title="3. Call script" subtitle="What it asks (in order), what it mentions, and the step it agrees. It skips anything already known.">
          <div className="space-y-4">
            <StringListEditor label="Questions to ask" items={ins.discovery_questions || []} placeholder="e.g. Would online or classroom suit you better?"
              onChange={(items) => setIns({ discovery_questions: items })} emptyText="No questions yet." />
            <StringListEditor label="Points to mention (only the ones that fit)" items={ins.offer_points || []} placeholder="e.g. New batch starts Monday"
              onChange={(items) => setIns({ offer_points: items })} emptyText="No points yet." />
            <label className="block space-y-1">
              <span className="text-xs font-medium text-slate-300">Next step to agree</span>
              <input className={FIELD} value={ins.next_step || ''} placeholder="e.g. Book a free demo class"
                onChange={(e) => setIns({ next_step: e.target.value })} />
            </label>
          </div>
        </Card>

        <Card
          title={<span className="flex items-center gap-2 text-sm font-semibold text-slate-100"><BookOpen className="h-4 w-4 text-[#00df8f]" /> 4. Knowledge</span>}
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

        <Card title="5. Rules & handoff" subtitle="What it must always or never do, and when a person takes over.">
          <div className="space-y-4">
            <StringListEditor label="Rules" items={ins.rules} placeholder="e.g. Never promise a job or salary"
              onChange={(items) => setIns({ rules: items })} />
            <StringListEditor label="Hand over to a person when..." items={ins.escalation_rules} placeholder="e.g. They ask about refunds: book a callback"
              onChange={(items) => setIns({ escalation_rules: items })} />
          </div>
        </Card>

        <Card title="6. Voice & language">
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
          </div>
        </Card>

        <Card title="7. Call limits" subtitle="Keeps calls short and costs in check.">
          <CallLimitsEditor limits={config.conversation.limits} onChange={(limits) => setConversation({ limits })} />
        </Card>
      </div>

      {/* TEST + GO LIVE */}
      <div>
        <div className="space-y-5 2xl:sticky 2xl:top-4">
          <Card title="Test" subtitle={latest ? `Testing version ${latest.version_number}` : 'Publish once to start testing'}>
            {isDirty || !latest ? (
              <div className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-amber-800/50 bg-amber-950/30 p-3 text-xs text-amber-200">
                <span>{latest ? 'You have changes the test isn\'t using yet.' : 'Not published yet.'}</span>
                <Button variant="primary" size="sm" isLoading={isPublishing} onClick={onPublish}>
                  <UploadCloud className="mr-1.5 h-3.5 w-3.5" /> Publish &amp; test
                </Button>
              </div>
            ) : null}
            {latest && <AgentTestingWorkbench key={latest.id} agentId={agent.id} initialVersionId={latest.id} />}
          </Card>

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
    </div>
  );
};
