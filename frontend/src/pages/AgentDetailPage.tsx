import React, { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate, Link, useSearchParams } from 'react-router-dom';
import {
  Bot,
  ArrowLeft,
  Edit2,
  Sliders,
  History,
  UploadCloud,
  AlertTriangle,
  CheckCircle,
  Save,
  Check,
  Plus,
  Trash2,
  Wrench,
  ArrowRight,
  RotateCcw,
  Eye,
  GitCompare,
  FlaskConical,
  Copy,
  Database,
  MoreHorizontal,
  FileText,
} from 'lucide-react';
import { SystemPromptPanel } from '../components/agents/SystemPromptPanel';
import { useAuth } from '../context/AuthContext';
import { agentsService } from '../services/agents';
import { configurationService } from '../services/configuration';
import { catalogsService } from '../services/catalogs';
import {
  Agent,
  AgentUpdateInput,
  AgentVersion,
  AgentStatus,
  AgentConfigurationData,
  ValidationResult,
  KnowledgeSource,
  Tool,
  CartesiaVoice,
  VersionComparison,
  EMPTY_CALL_LIMITS,
} from '../types';
// Cartesia voice picker is kept in components/voice/VoicePickerModal.tsx but not used: voices come from Sarvam
// import { VoicePickerModal } from '../components/voice/VoicePickerModal';
import { SarvamVoicePickerModal as VoicePickerModal } from '../components/voice/SarvamVoicePickerModal';
import { AgentBuildView } from '../components/agents/AgentBuildView';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { StatusBadge } from '../components/common/Badge';
import { Modal } from '../components/common/Modal';
import { Input } from '../components/common/Input';
import { Select } from '../components/common/Select';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { runtimeService } from '../services/runtime';

const AGENT_STATUSES: { value: AgentStatus; label: string }[] = [
  { value: 'DRAFT', label: 'Draft' },
  { value: 'TESTING', label: 'Testing' },
  { value: 'READY', label: 'Ready' },
  { value: 'DEPLOYED', label: 'Deployed' },
  { value: 'PAUSED', label: 'Paused' },
  { value: 'ARCHIVED', label: 'Archived' },
];




const normalizeConfig = (raw: any): AgentConfigurationData => ({
  identity: {
    name: raw?.identity?.name || '',
    organization: raw?.identity?.organization || '',
    persona: raw?.identity?.persona || 'professional, attentive, and helpful',
  },
  business_context: {
    business_name: raw?.business_context?.business_name || '',
    business_type: raw?.business_context?.business_type || '',
    business_hours: raw?.business_context?.business_hours || {},
    location: raw?.business_context?.location || '',
    contact_information: raw?.business_context?.contact_information || {},
    call_direction: raw?.business_context?.call_direction || 'inbound',
  },
  instructions: {
    primary_goal: raw?.instructions?.primary_goal || raw?.instructions?.goal || '',
    responsibilities: Array.isArray(raw?.instructions?.responsibilities) ? raw.instructions.responsibilities : [],
    rules: Array.isArray(raw?.instructions?.rules)
      ? raw.instructions.rules
      : Array.isArray(raw?.instructions?.behavioral_rules)
      ? raw.instructions.behavioral_rules
      : [],
    restrictions: Array.isArray(raw?.instructions?.restrictions) ? raw.instructions.restrictions : [],
    escalation_rules: Array.isArray(raw?.instructions?.escalation_rules)
      ? raw.instructions.escalation_rules
      : [],
    discovery_questions: Array.isArray(raw?.instructions?.discovery_questions) ? raw.instructions.discovery_questions : [],
    offer_points: Array.isArray(raw?.instructions?.offer_points) ? raw.instructions.offer_points : [],
    next_step: raw?.instructions?.next_step || '',
    script_source: raw?.instructions?.script_source || '',
  },
  conversation: {
    tone: raw?.conversation?.tone || 'professional',
    verbosity: raw?.conversation?.verbosity || 'concise',
    greeting: raw?.conversation?.greeting || '',
    farewell: raw?.conversation?.farewell || '',
    interruption_behavior: raw?.conversation?.interruption_behavior || 'pause_and_listen',
    limits: {
      ...EMPTY_CALL_LIMITS,
      ...(raw?.conversation?.limits || {}),
      end_call_phrases: Array.isArray(raw?.conversation?.limits?.end_call_phrases)
        ? raw.conversation.limits.end_call_phrases
        : [],
    },
  },
  languages: {
    primary: raw?.languages?.primary || raw?.languages?.primary_language || 'en',
    supported: Array.isArray(raw?.languages?.supported)
      ? raw.languages.supported
      : Array.isArray(raw?.languages?.supported_languages)
      ? raw.languages.supported_languages
      : ['en'],
  },
  knowledge_sources: Array.isArray(raw?.knowledge_sources) ? raw.knowledge_sources : [],
  tools: Array.isArray(raw?.tools) ? raw.tools : [],
  integrations: Array.isArray(raw?.integrations) ? raw.integrations : [],
  variables: {
    inputs: Array.isArray(raw?.variables?.inputs) ? raw.variables.inputs : [],
    outputs: Array.isArray(raw?.variables?.outputs) ? raw.variables.outputs : [],
  },
  voice: {
    provider: raw?.voice?.provider || 'cartesia',
    voice_id: raw?.voice?.voice_id ?? null,
    language: raw?.voice?.language || 'en',
    speed: typeof raw?.voice?.speed === 'number' ? raw.voice.speed : 1.0,
  },
  providers: {
    stt: typeof raw?.providers?.stt === 'string' ? raw.providers.stt : raw?.providers?.stt?.provider || 'cartesia',
    llm: typeof raw?.providers?.llm === 'string' ? raw.providers.llm : raw?.providers?.llm?.provider || 'gemini',
    tts: typeof raw?.providers?.tts === 'string' ? raw.providers.tts : raw?.providers?.tts?.provider || 'cartesia',
    telephony: typeof raw?.providers?.telephony === 'string' ? raw.providers.telephony : raw?.providers?.telephony?.provider || null,
  },
});

export const AgentDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [agent, setAgent] = useState<Agent | null>(null);
  const [versions, setVersions] = useState<AgentVersion[]>([]);
  const [config, setConfig] = useState<AgentConfigurationData | null>(null);
  const [isDirty, setIsDirty] = useState(false);

  // Catalogs state
  const [knowledgeList, setKnowledgeList] = useState<KnowledgeSource[]>([]);
  const [toolsList, setToolsList] = useState<Tool[]>([]);

  // Navigation tab (?tab=test/tests/voice opens Test, ?tab=variables/tools/versions/prompt those; anything else Configure)
  const [searchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState<'configure' | 'test' | 'variables' | 'tools' | 'versions' | 'prompt'>(
    requestedTab === 'variables' || requestedTab === 'tools' || requestedTab === 'versions' || requestedTab === 'prompt'
      ? requestedTab
      : requestedTab === 'test' || requestedTab === 'tests' || requestedTab === 'voice'
        ? 'test'
        : 'configure'
  );

  // Header overflow menu (Identity, Validate Spec)
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!isMenuOpen) return;
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setIsMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsMenuOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [isMenuOpen]);

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Actions state
  const [isSaving, setIsSaving] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);

  // Validation Modal
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [isValidationModalOpen, setIsValidationModalOpen] = useState(false);

  // Inspect Version Modal
  const [selectedVersionForInspect, setSelectedVersionForInspect] = useState<AgentVersion | null>(null);

  // Compare Versions Modal
  const [isCompareModalOpen, setIsCompareModalOpen] = useState(false);
  const [baseVersionNum, setBaseVersionNum] = useState<number>(1);
  const [compareVersionNum, setCompareVersionNum] = useState<number>(1);
  const [comparisonDiff, setComparisonDiff] = useState<VersionComparison | null>(null);
  const [isComparing, setIsComparing] = useState(false);

  // Auth & Voice Catalog State
  const { token, user } = useAuth();
  // Only admins publish versions (the server enforces it too)
  const isAdmin = user?.role === 'ADMIN';

  const [voicesList, setVoicesList] = useState<CartesiaVoice[]>([]);
  const [isVoicePickerOpen, setIsVoicePickerOpen] = useState(false);
  // A voice was picked in the open picker: it is saved to the draft when the picker closes
  const [voicePicked, setVoicePicked] = useState(false);
  // Edit Metadata Modal State
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editForm, setEditForm] = useState<AgentUpdateInput>({});
  const [editError, setEditError] = useState<string | null>(null);
  const [isSubmittingMeta, setIsSubmittingMeta] = useState(false);

  // List Item Draft Inputs
  const [newOutputVariable, setNewOutputVariable] = useState('');

  // Variable Token Copying & Creation Modals
  const [copiedToken, setCopiedToken] = useState<string | null>(null);
  const handleCopyToken = (name: string) => {
    const token = `{{${name}}}`;
    navigator.clipboard.writeText(token);
    setCopiedToken(token);
    setTimeout(() => setCopiedToken(null), 2000);
  };

  // Add Input Variable Modal State
  const [isAddInputModalOpen, setIsAddInputModalOpen] = useState(false);
  const [newInputName, setNewInputName] = useState('');
  const [newInputSource, setNewInputSource] = useState('CRM or lead database');
  const [newInputType, setNewInputType] = useState('string');
  const [newInputDefault, setNewInputDefault] = useState('');
  const [newInputRequired, setNewInputRequired] = useState(false);
  const [newInputDesc, setNewInputDesc] = useState('');

  // Add Output Variable Modal State
  const [isAddOutputModalOpen, setIsAddOutputModalOpen] = useState(false);
  const [newOutputName, setNewOutputName] = useState('');
  const [newOutputType, setNewOutputType] = useState('string');
  const [newOutputDesc, setNewOutputDesc] = useState('');

  const fetchAllData = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const [agentData, versionsData, configData, toolsData, voicesData] = await Promise.all([
        agentsService.get(id),
        agentsService.getVersions(id),
        configurationService.getConfiguration(id),
        catalogsService.listTools(),
        // Both providers' voices, so the chosen voice shows by name whichever provider it is from
        Promise.all([
          catalogsService.listSarvamVoices().catch(() => []),
          catalogsService.listVoices().catch(() => []),
        ]).then(([sarvam, cartesia]) => [...sarvam, ...cartesia]),
      ]);

      setAgent(agentData);
      setVersions(versionsData);
      setConfig(normalizeConfig(configData.configuration));
      // Only this client's knowledge base can be given to the employee
      setKnowledgeList(await catalogsService.listClientKnowledge(agentData.client_id).catch(() => []));
      setToolsList(toolsData);
      setVoicesList(voicesData);

      setEditForm({
        name: agentData.name,
        role: agentData.role,
        description: agentData.description || '',
        status: agentData.status,
      });

      if (versionsData.length >= 2) {
        setBaseVersionNum(versionsData[versionsData.length - 2].version_number);
        setCompareVersionNum(versionsData[versionsData.length - 1].version_number);
      } else if (versionsData.length === 1) {
        setBaseVersionNum(versionsData[0].version_number);
        setCompareVersionNum(versionsData[0].version_number);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load AI Employee Studio');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAllData();
  }, [id]);

  // Helper to update draft configuration
  const updateDraft = (updater: (prev: AgentConfigurationData) => AgentConfigurationData) => {
    if (!config) return;
    setConfig((prev) => {
      if (!prev) return prev;
      return normalizeConfig(updater(prev));
    });
    setIsDirty(true);
  };

  // Save Draft
  const handleSaveDraft = async () => {
    if (!id || !config) return;
    setIsSaving(true);
    setActionSuccess(null);
    try {
      const updated = await configurationService.updateConfiguration(id, config);
      setConfig(normalizeConfig(updated.configuration));
      setIsDirty(false);
      setActionSuccess('Draft configuration saved successfully.');
      setTimeout(() => setActionSuccess(null), 4000);
    } catch (err: any) {
      alert(`Save failed: ${err.message || 'Unknown error'}`);
    } finally {
      setIsSaving(false);
    }
  };

  // Validate Specification
  const handleValidateSpec = async () => {
    if (!id) return;
    setIsValidating(true);
    try {
      if (isDirty && config) {
        await configurationService.updateConfiguration(id, config);
        setIsDirty(false);
      }
      const result = await configurationService.validateConfiguration(id);
      setValidationResult(result);
      setIsValidationModalOpen(true);
    } catch (err: any) {
      alert(`Validation error: ${err.message || 'Could not validate configuration.'}`);
    } finally {
      setIsValidating(false);
    }
  };

  // A newly picked voice is saved to the draft straight away so it can't be lost. It is never published here:
  // tests and calls switch voice when an admin presses Publish.
  const handleVoiceChosen = async () => {
    if (!id || !config) return;
    setIsSaving(true);
    try {
      const saved = await configurationService.updateConfiguration(id, config);
      setConfig(normalizeConfig(saved.configuration));
      setIsDirty(false);
      setActionSuccess(
        isAdmin ? 'Voice saved. Press Publish to use it on tests and calls.' : 'Voice saved. An admin publishes it for tests and calls.'
      );
      setTimeout(() => setActionSuccess(null), 5000);
    } catch (err: any) {
      alert(`Couldn't save the voice: ${err.message || 'Unknown error'}`);
    } finally {
      setIsSaving(false);
    }
  };

  // Save the draft and publish it as a new frozen version; the test panel always tests the latest one
  const handlePublishAndTest = async () => {
    if (!id || !config) return;
    setIsPublishing(true);
    try {
      if (isDirty) {
        const saved = await configurationService.updateConfiguration(id, config);
        setConfig(normalizeConfig(saved.configuration));
        setIsDirty(false);
      }
      const newVersion = await configurationService.createVersion(id);
      setVersions(await agentsService.getVersions(id));
      setActionSuccess(`Version ${newVersion.version_number} published. Tests now use it.`);
      setTimeout(() => setActionSuccess(null), 4000);
    } catch (err: any) {
      alert(`Publish failed: ${err.message || 'Validation error prevented publishing.'}`);
    } finally {
      setIsPublishing(false);
    }
  };

  // Go live: step through the allowed statuses up to DEPLOYED
  const handleGoLive = async () => {
    if (!id || !agent) return;
    const path: Record<string, string[]> = {
      DRAFT: ['TESTING', 'READY', 'DEPLOYED'],
      TESTING: ['READY', 'DEPLOYED'],
      READY: ['DEPLOYED'],
      PAUSED: ['DEPLOYED'],
      ARCHIVED: ['DRAFT', 'TESTING', 'READY', 'DEPLOYED'],
    };
    let updated = agent;
    for (const status of path[agent.status] || []) {
      updated = await agentsService.update(id, { status: status as any });
    }
    setAgent(updated);
    setActionSuccess(`${updated.name} is live.`);
    setTimeout(() => setActionSuccess(null), 4000);
  };

  // Compare Versions
  const handleCompareVersions = async () => {
    if (!id) return;
    setIsComparing(true);
    try {
      const diff = await configurationService.compareVersions(id, baseVersionNum, compareVersionNum);
      setComparisonDiff(diff);
      setIsCompareModalOpen(true);
    } catch (err: any) {
      alert(`Comparison failed: ${err.message || 'Error comparing versions.'}`);
    } finally {
      setIsComparing(false);
    }
  };

  // Restore Version to Editable Draft
  const handleRestoreVersion = async (versionId: string, versionNumber: number) => {
    if (!id) return;
    if (
      !window.confirm(
        `Are you sure you want to restore Version ${versionNumber} into the current draft? Unsaved changes will be overwritten.`
      )
    ) {
      return;
    }
    try {
      await configurationService.restoreVersion(id, versionId);
      await fetchAllData();
      setIsDirty(false);
      setActionSuccess(`Draft restored from Version ${versionNumber}.`);
      setActiveTab('configure');
      setTimeout(() => setActionSuccess(null), 4000);
    } catch (err: any) {
      alert(`Rollback failed: ${err.message || 'Failed to restore version.'}`);
    }
  };

  // Knowledge Attachment Toggle
  const handleToggleKnowledge = async (sourceId: string) => {
    if (!id || !config) return;
    const isAttached = config.knowledge_sources.includes(sourceId);
    try {
      if (isAttached) {
        await catalogsService.detachKnowledge(id, sourceId);
        updateDraft((prev) => ({
          ...prev,
          knowledge_sources: prev.knowledge_sources.filter((k) => k !== sourceId),
        }));
      } else {
        await catalogsService.attachKnowledge(id, sourceId);
        updateDraft((prev) => ({
          ...prev,
          knowledge_sources: [...prev.knowledge_sources, sourceId],
        }));
      }
    } catch (err: any) {
      alert(`Failed to update knowledge source: ${err.message}`);
    }
  };

  // Tool Attachment Toggle
  const handleToggleTool = async (toolId: string) => {
    if (!id || !config) return;
    const isAttached = config.tools.includes(toolId);
    try {
      if (isAttached) {
        await catalogsService.detachTool(id, toolId);
        updateDraft((prev) => ({
          ...prev,
          tools: prev.tools.filter((t) => t !== toolId),
        }));
      } else {
        await catalogsService.attachTool(id, toolId);
        updateDraft((prev) => ({
          ...prev,
          tools: [...prev.tools, toolId],
        }));
      }
    } catch (err: any) {
      alert(`Failed to update tool: ${err.message}`);
    }
  };

  // Edit Metadata Submit
  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!id || !agent) return;
    setEditError(null);
    setIsSubmittingMeta(true);
    try {
      const updated = await agentsService.update(id, editForm);
      setAgent(updated);
      setIsEditModalOpen(false);
      setActionSuccess('Agent metadata updated successfully.');
      setTimeout(() => setActionSuccess(null), 4000);
    } catch (err: any) {
      setEditError(err.message || 'Failed to update metadata');
    } finally {
      setIsSubmittingMeta(false);
    }
  };

  if (isLoading) {
    return <LoadingState message="Loading AI Employee Studio configuration engine..." />;
  }

  if (error || !agent || !config) {
    return (
      <ErrorState
        message={error || 'AI Employee configuration could not be loaded.'}
        onRetry={fetchAllData}
      />
    );
  }

  return (
    <div className="space-y-6 pb-12">
      {/* SUCCESS BANNER */}
      {actionSuccess && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-900/60 bg-emerald-950/40 px-4 py-3 text-xs text-emerald-300">
          <CheckCircle className="h-4 w-4 shrink-0 text-emerald-400" />
          <span>{actionSuccess}</span>
        </div>
      )}

      {/* TOP STUDIO HEADER BAR */}
      <div className="flex flex-col gap-4 rounded-xl border border-[#1b1f2d] bg-[#0c0e14] p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-xs text-slate-400 mb-2">
            <Link to="/agents" className="hover:text-slate-200 flex items-center gap-1 transition-colors">
              <ArrowLeft className="h-3 w-3" /> AI Employees
            </Link>
            <span>/</span>
            <span className="text-slate-300 font-mono">{agent.id}</span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#00df8f]/15 border border-[#00df8f]/30 text-[#00df8f]">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-slate-100">{agent.name}</h1>
                <StatusBadge status={agent.status} />
                <span className="rounded bg-[#151824] px-2 py-0.5 font-mono text-[10px] text-slate-400">
                  {versions.length > 0 ? `v${versions[0].version_number}` : 'DRAFT'}
                </span>
                {isDirty ? (
                  <span className="flex items-center gap-1 rounded-full bg-amber-950/60 border border-amber-800/40 px-2 py-0.5 text-[10px] font-semibold text-amber-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" /> Unsaved Changes
                  </span>
                ) : (
                  <span className="flex items-center gap-1 rounded-full bg-emerald-950/40 border border-emerald-900/40 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
                    <Check className="h-3 w-3" /> Draft Saved
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Role: <span className="text-slate-200 font-medium">{agent.role}</span> &bull; Client:{' '}
                <span className="text-slate-200 font-medium">{agent.client_name || agent.client_id}</span>
              </p>
            </div>
          </div>
        </div>

        {/* TOP ACTION BUTTONS */}
        <div className="flex flex-wrap items-center gap-2 pt-2 lg:pt-0">
          <Button
            variant="secondary"
            size="sm"
            onClick={handleSaveDraft}
            isLoading={isSaving}
            disabled={!isDirty}
            title="Save draft configuration changes"
          >
            <Save className="h-3.5 w-3.5 mr-1.5 text-[#00df8f]" /> Save Draft
          </Button>

          {isAdmin && (
            <Button
              variant="primary"
              size="sm"
              onClick={handlePublishAndTest}
              isLoading={isPublishing}
              title="Save your changes as a new version; tests use the latest version"
            >
              <UploadCloud className="h-3.5 w-3.5 mr-1.5" /> Publish
            </Button>
          )}

          <div ref={menuRef} className="relative">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsMenuOpen((open) => !open)}
              isLoading={isValidating}
              title="More actions"
              aria-haspopup="menu"
              aria-expanded={isMenuOpen}
            >
              <MoreHorizontal className="h-4 w-4 text-slate-400" />
            </Button>
            {isMenuOpen && (
              <div role="menu" className="absolute right-0 z-20 mt-1 w-48 overflow-hidden rounded-lg border border-[#1b1f2d] bg-[#0c0e14] py-1 shadow-xl">
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setIsMenuOpen(false);
                    setIsEditModalOpen(true);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-slate-300 hover:bg-[#151824] hover:text-slate-100"
                >
                  <Edit2 className="h-3.5 w-3.5 text-slate-400" /> Edit identity &amp; status
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setIsMenuOpen(false);
                    handleValidateSpec();
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-slate-300 hover:bg-[#151824] hover:text-slate-100"
                >
                  <Check className="h-3.5 w-3.5 text-blue-400" /> Validate spec
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* CANVAS SECTION NAVIGATION (STRICT ORDER: INSTRUCTIONS, VARIABLES, TOOLS, SETTINGS, TESTS) */}
      <div className="flex overflow-x-auto rounded-xl border border-[#1b1f2d] bg-[#0c0e14] p-1 no-scrollbar">
        {[
          { id: 'configure', label: 'Configure', icon: Bot },
          { id: 'test', label: 'Test', icon: FlaskConical },
          { id: 'variables', label: `Variables (${config.variables.inputs.length + config.variables.outputs.length})`, icon: Sliders },
          { id: 'tools', label: `Tools (${config.tools.length})`, icon: Wrench },
          { id: 'versions', label: `Versions (${versions.length})`, icon: History },
          { id: 'prompt', label: 'System prompt', icon: FileText },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3.5 py-2.5 text-xs font-medium transition-colors ${
                isActive
                  ? 'bg-[#00df8f]/10 text-[#00df8f]'
                  : 'text-slate-400 hover:bg-[#151824] hover:text-slate-200'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {(activeTab === 'configure' || activeTab === 'test') && (
        <AgentBuildView
          view={activeTab}
          agent={agent}
          config={config}
          updateDraft={updateDraft}
          isDirty={isDirty}
          versions={versions}
          onPublish={handlePublishAndTest}
          isPublishing={isPublishing}
          canPublish={isAdmin}
          knowledgeList={knowledgeList}
          onToggleKnowledge={handleToggleKnowledge}
          onAgentKnowledgeChange={() =>
            catalogsService
              .getAgentKnowledge(id!)
              .then((attached) => updateDraft((prev) => ({ ...prev, knowledge_sources: attached.map((k) => k.id) })))
              .catch(() => {})
          }
          voiceLabel={
            voicesList.find((v) => v.id === config.voice.voice_id)?.name ||
            (config.voice.voice_id ? `${config.voice.voice_id} (${config.voice.provider})` : 'Default voice')
          }
          onChangeVoice={() => setIsVoicePickerOpen(true)}
          onGoLive={handleGoLive}
        />
      )}

      {/* ========================================================= */}
      {/* TAB 2: VARIABLES (INPUT VARIABLES & OUTPUT VARIABLES) */}
      {/* ========================================================= */}
      {activeTab === 'variables' && (
        <div className="space-y-6">
          {/* Quick Token Reference Card */}
          <Card
            title="Runtime Variable Contract"
            subtitle="Dynamic parameters injected into session context or extracted during conversations."
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 text-xs">
              <div className="space-y-1">
                <span className="text-slate-300">
                  Total Active Variables:{' '}
                  <span className="font-semibold text-[#00df8f]">
                    {config.variables.inputs.length} Inputs
                  </span>{' '}
                  &bull;{' '}
                  <span className="font-semibold text-purple-400">
                    {config.variables.outputs.length} Outputs
                  </span>
                </span>
                <p className="text-[11px] text-slate-400 max-w-2xl leading-relaxed">
                  Use <span className="font-mono text-[#00df8f] bg-[#00df8f]/10 px-1 py-0.5 rounded border border-[#00df8f]/20">&#123;&#123;variable_name&#125;&#125;</span> inside instructions, greetings, and tool arguments. The runtime substitutes actual values while suppressing unresolved placeholders.
                </p>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setIsAddInputModalOpen(true)}
                  leftIcon={<Plus className="h-3.5 w-3.5 text-[#00df8f]" />}
                >
                  + Add Input Variable
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setIsAddOutputModalOpen(true)}
                  leftIcon={<Plus className="h-3.5 w-3.5 text-purple-400" />}
                >
                  + Add Output Variable
                </Button>
              </div>
            </div>
          </Card>

          {/* SECTION 1: INPUT VARIABLES */}
          <Card
            title={`Input Variables (${config.variables.inputs.length})`}
            subtitle="Parameters passed at session initialization from CRM leads, contact records, or telephony metadata"
          >
            <div className="space-y-3">
              {config.variables.inputs.length === 0 ? (
                <div className="rounded border border-dashed border-[#1b1f2d] p-6 text-center text-xs text-slate-500">
                  No input variables configured. Click &ldquo;+ Add Input Variable&rdquo; to define one.
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {config.variables.inputs.map((variable, idx) => (
                    <div
                      key={`${variable.name}-${idx}`}
                      className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-3.5 space-y-2 hover:border-[#00df8f]/40 transition-all"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-bold text-[#00df8f]">
                              &#123;&#123;{variable.name}&#125;&#125;
                            </span>
                            <button
                              type="button"
                              onClick={() => handleCopyToken(variable.name)}
                              className="text-slate-500 hover:text-slate-200 p-0.5"
                              title="Copy variable token to clipboard"
                            >
                              {copiedToken === `{{${variable.name}}}` ? (
                                <Check className="h-3 w-3 text-emerald-400" />
                              ) : (
                                <Copy className="h-3 w-3" />
                              )}
                            </button>
                            {variable.required && (
                              <span className="rounded bg-rose-950/60 border border-rose-900/50 px-1.5 py-0.2 text-[9px] font-bold text-rose-300">
                                REQUIRED
                              </span>
                            )}
                          </div>

                          <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
                            <span className="rounded bg-[#151824] px-1.5 py-0.5 text-slate-300 font-mono">
                              Type: {variable.data_type || 'string'}
                            </span>
                            <span className="rounded bg-emerald-950/60 border border-emerald-900/40 px-1.5 py-0.5 text-emerald-300">
                              Source: {variable.source || 'CRM Database'}
                            </span>
                            {variable.default_value !== null && variable.default_value !== undefined && (
                              <span className="rounded bg-[#102d38] px-1.5 py-0.5 text-slate-400">
                                Default: &quot;{String(variable.default_value)}&quot;
                              </span>
                            )}
                          </div>
                        </div>

                        <button
                          type="button"
                          className="p-1 text-slate-500 hover:text-rose-400 transition-colors"
                          title="Remove variable"
                          onClick={() =>
                            updateDraft((prev) => ({
                              ...prev,
                              variables: {
                                ...prev.variables,
                                inputs: prev.variables.inputs.filter((_, itemIndex) => itemIndex !== idx),
                              },
                            }))
                          }
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>

                      {variable.description && (
                        <p className="text-[11px] text-slate-400 leading-relaxed pt-1 border-t border-[#151824]">
                          {variable.description}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>

          {/* SECTION 2: OUTPUT VARIABLES */}
          <Card
            title={`Output Variables (${config.variables.outputs.length})`}
            subtitle="Qualification outcomes and buyer requirements captured during conversation turns and written back to CRM"
          >
            <div className="space-y-3">
              {config.variables.outputs.length === 0 ? (
                <div className="rounded border border-dashed border-[#1b1f2d] p-6 text-center text-xs text-slate-500">
                  No output variables configured. Click &ldquo;+ Add Output Variable&rdquo; to define one.
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {config.variables.outputs.map((variable, idx) => (
                    <div
                      key={`${variable.name}-${idx}`}
                      className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-3.5 space-y-2 hover:border-purple-500/40 transition-all"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs font-bold text-purple-400">
                              {variable.name}
                            </span>
                            <span className="rounded bg-purple-950/60 border border-purple-900/40 px-1.5 py-0.2 text-[9px] font-bold text-purple-300">
                              TARGET OUTCOME
                            </span>
                          </div>

                          <div className="flex items-center gap-1.5 text-[10px]">
                            <span className="rounded bg-[#151824] px-1.5 py-0.5 text-slate-300 font-mono">
                              Type: {variable.data_type || 'string'}
                            </span>
                          </div>
                        </div>

                        <button
                          type="button"
                          className="p-1 text-slate-500 hover:text-rose-400 transition-colors"
                          title="Remove output variable"
                          onClick={() =>
                            updateDraft((prev) => ({
                              ...prev,
                              variables: {
                                ...prev.variables,
                                outputs: prev.variables.outputs.filter((_, itemIndex) => itemIndex !== idx),
                              },
                            }))
                          }
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>

                      {variable.extraction_instructions ? (
                        <p className="text-[11px] text-slate-300 leading-relaxed pt-1 border-t border-[#151824]">
                          {variable.extraction_instructions}
                        </p>
                      ) : (
                        <p className="text-[11px] text-slate-500 italic pt-1 border-t border-[#151824]">
                          Extracted from conversation dialogue turns.
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 3: TOOLS (LOGICAL REAL ESTATE TOOLS & INTEGRATIONS) */}
      {/* ========================================================= */}
      {activeTab === 'tools' && (
        <div className="space-y-6">

          {/* CATALOG REGISTERED TOOLS TOGGLE */}
          <Card
            title={`Catalog Tool Attachments (${config.tools.length} Enabled)`}
            subtitle="Enable or disable catalog tools available to this voice agent during telephone calls"
          >
            <div className="divide-y divide-[#1b1f2d]">
              {toolsList.length === 0 ? (
                <div className="py-6 text-center text-xs text-slate-500">No tools configured in catalog.</div>
              ) : (
                toolsList.map((tool) => {
                  const isAttached = config.tools.includes(tool.id);
                  return (
                    <div key={tool.id} className="py-3.5 flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-200">{tool.name}</span>
                          <span className="rounded bg-[#052b20]/60 border border-[#0a4d39]/50 px-1.5 py-0.5 text-[10px] font-mono text-[#00df8f]">
                            {tool.executor_type}
                          </span>
                          <span className="text-[10px] font-mono text-slate-500">Timeout: {tool.timeout}s</span>
                        </div>
                        <p className="text-xs text-slate-400 mt-1 max-w-xl">{tool.description}</p>
                        <span className="text-[10px] font-mono text-slate-500">{tool.id}</span>
                      </div>

                      <div>
                        <Button
                          size="sm"
                          variant={isAttached ? 'danger' : 'secondary'}
                          onClick={() => handleToggleTool(tool.id)}
                        >
                          {isAttached ? 'Disable' : 'Enable Tool'}
                        </Button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </Card>

        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 11: VERSIONS & HISTORY */}
      {/* ========================================================= */}
      {activeTab === 'prompt' && <SystemPromptPanel agentId={agent.id} config={config} isDirty={isDirty} />}

      {activeTab === 'versions' && (
        <div className="space-y-6">
          {/* Comparison Bar */}
          {versions.length >= 2 && (
            <Card title="Version Comparison Diff" subtitle="Compare two frozen version snapshots side-by-side">
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-slate-400">Base Version:</span>
                  <select
                    className="rounded bg-[#10121a] border border-[#232736] px-2.5 py-1.5 text-xs text-slate-200"
                    value={baseVersionNum}
                    onChange={(e) => setBaseVersionNum(parseInt(e.target.value, 10))}
                  >
                    {versions.map((v) => (
                      <option key={v.id} value={v.version_number}>
                        Version {v.version_number}
                      </option>
                    ))}
                  </select>
                </div>

                <ArrowRight className="h-4 w-4 text-slate-500" />

                <div className="flex items-center gap-2 text-xs">
                  <span className="text-slate-400">Compare With:</span>
                  <select
                    className="rounded bg-[#10121a] border border-[#232736] px-2.5 py-1.5 text-xs text-slate-200"
                    value={compareVersionNum}
                    onChange={(e) => setCompareVersionNum(parseInt(e.target.value, 10))}
                  >
                    {versions.map((v) => (
                      <option key={v.id} value={v.version_number}>
                        Version {v.version_number}
                      </option>
                    ))}
                  </select>
                </div>

                <Button
                  size="sm"
                  variant="secondary"
                  onClick={handleCompareVersions}
                  isLoading={isComparing}
                >
                  <GitCompare className="h-3.5 w-3.5 mr-1" /> Compare Versions
                </Button>
              </div>
            </Card>
          )}

          {/* Versions List */}
          <Card
            title={`Immutable Version Snapshots (${versions.length})`}
            subtitle="Frozen configurations ready for deployment. Roll back by restoring an older version into current draft."
          >
            {versions.length === 0 ? (
              <div className="py-8 text-center">
                <EmptyState
                  icon={<History className="h-6 w-6" />}
                  title="No published versions yet"
                  description={isAdmin ? "Click 'Publish' in the top action bar to create Version 1 from the current draft." : 'An admin publishes Version 1 from the current draft.'}
                />
              </div>
            ) : (
              <div className="divide-y divide-[#1b1f2d]">
                {versions.map((v) => (
                  <div key={v.id} className="p-4 flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-100">
                          Version {v.version_number}
                        </span>
                        <StatusBadge status={v.status} />
                      </div>
                      <div className="text-[11px] font-mono text-slate-500 mt-1">
                        Snapshot ID: {v.id} &bull; Created: {new Date(v.created_at).toLocaleString()}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setSelectedVersionForInspect(v)}
                        title="View raw Canonical Agent Spec JSON"
                      >
                        <Eye className="h-3.5 w-3.5 mr-1 text-slate-400" /> Inspect Spec
                      </Button>

                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => handleRestoreVersion(v.id, v.version_number)}
                        title="Restore this version into current editable draft"
                      >
                        <RotateCcw className="h-3.5 w-3.5 mr-1 text-amber-400" /> Restore as Draft
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* ========================================================= */}
      {/* MODAL 1: VALIDATION RESULTS */}
      {/* ========================================================= */}
      <Modal
        isOpen={isValidationModalOpen}
        onClose={() => setIsValidationModalOpen(false)}
        title="Agent Specification Validation"
        description="Verification against runtime completeness rules"
        maxWidth="lg"
      >
        {validationResult && (
          <div className="space-y-4">
            <div
              className={`rounded-lg p-4 border flex items-center gap-3 ${
                validationResult.valid
                  ? 'border-emerald-900/60 bg-emerald-950/40 text-emerald-300'
                  : 'border-rose-900/60 bg-rose-950/40 text-rose-300'
              }`}
            >
              {validationResult.valid ? (
                <CheckCircle className="h-5 w-5 text-emerald-400 shrink-0" />
              ) : (
                <AlertTriangle className="h-5 w-5 text-rose-400 shrink-0" />
              )}
              <div>
                <strong className="block text-sm font-semibold">
                  {validationResult.valid
                    ? 'Specification is Valid & Publish-Ready'
                    : 'Validation Issues Detected'}
                </strong>
                <span className="text-xs">
                  {validationResult.valid
                    ? 'All required runtime parameters, instructions, and providers are present.'
                    : `${validationResult.errors.length} error(s) must be resolved before publishing a version.`}
                </span>
              </div>
            </div>

            {/* Errors */}
            {validationResult.errors.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-rose-400 uppercase tracking-wide">
                  Blocking Errors ({validationResult.errors.length})
                </h4>
                <div className="space-y-1.5">
                  {validationResult.errors.map((err, i) => (
                    <div
                      key={i}
                      className="rounded border border-rose-900/40 bg-rose-950/20 p-2.5 text-xs text-rose-200 flex items-start gap-2"
                    >
                      <span className="font-mono text-rose-400 font-bold shrink-0">{err.field}:</span>
                      <span>{err.message}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Warnings */}
            {validationResult.warnings.length > 0 && (
              <div className="space-y-2 pt-2">
                <h4 className="text-xs font-semibold text-amber-400 uppercase tracking-wide">
                  Operational Warnings ({validationResult.warnings.length})
                </h4>
                <div className="space-y-1.5">
                  {validationResult.warnings.map((warn, i) => (
                    <div
                      key={i}
                      className="rounded border border-amber-900/40 bg-amber-950/20 p-2.5 text-xs text-amber-200 flex items-start gap-2"
                    >
                      <span className="font-mono text-amber-400 font-bold shrink-0">{warn.field}:</span>
                      <span>{warn.message}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="flex justify-end pt-3 border-t border-[#1b1f2d]">
              <Button variant="secondary" onClick={() => setIsValidationModalOpen(false)}>
                Close
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* ========================================================= */}
      {/* MODAL 2: INSPECT CANONICAL SPEC */}
      {/* ========================================================= */}
      <Modal
        isOpen={!!selectedVersionForInspect}
        onClose={() => setSelectedVersionForInspect(null)}
        title={`Canonical Spec: Version ${selectedVersionForInspect?.version_number}`}
        description={`Immutable snapshot ID: ${selectedVersionForInspect?.id}`}
        maxWidth="xl"
      >
        <div className="space-y-4">
          <div className="rounded-lg bg-[#08090d] p-4 font-mono text-xs text-slate-300 overflow-x-auto max-h-[60vh] border border-[#181b26]">
            <pre>{JSON.stringify(selectedVersionForInspect?.configuration_json, null, 2)}</pre>
          </div>
          <div className="flex justify-end pt-2 border-t border-[#1b1f2d]">
            <Button variant="secondary" onClick={() => setSelectedVersionForInspect(null)}>
              Close
            </Button>
          </div>
        </div>
      </Modal>

      {/* ========================================================= */}
      {/* MODAL 3: VERSION COMPARISON DIFF */}
      {/* ========================================================= */}
      <Modal
        isOpen={isCompareModalOpen}
        onClose={() => setIsCompareModalOpen(false)}
        title={`Comparison: Version ${comparisonDiff?.base_version_number} vs Version ${comparisonDiff?.compare_version_number}`}
        description={comparisonDiff?.summary || 'Field-by-field differences between two immutable configuration snapshots'}
        maxWidth="xl"
      >
        <div className="space-y-4">
          {comparisonDiff && (
            <>
              {(!comparisonDiff.changes || comparisonDiff.changes.length === 0) ? (
                <div className="p-6 text-center text-xs text-slate-400 border border-[#1b1f2d] rounded-lg">
                  No differences found. Both versions have identical specifications.
                </div>
              ) : (
                <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
                  {comparisonDiff.changes.map((diff, idx) => (
                    <div key={idx} className="rounded-lg border border-[#143c49] bg-[#06141a] p-3 text-xs space-y-2">
                      <div className="font-mono font-semibold text-[#00df8f] text-xs">{diff.field}</div>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="rounded bg-rose-950/20 border border-rose-900/40 p-2 text-rose-300">
                          <span className="block text-[10px] font-mono text-rose-400 mb-1">
                            Version {comparisonDiff.base_version_number} (Base)
                          </span>
                          <pre className="font-mono text-[11px] whitespace-pre-wrap overflow-x-auto">
                            {typeof diff.old_value === 'object'
                              ? JSON.stringify(diff.old_value, null, 2)
                              : String(diff.old_value ?? 'None')}
                          </pre>
                        </div>
                        <div className="rounded bg-emerald-950/20 border border-emerald-900/40 p-2 text-emerald-300">
                          <span className="block text-[10px] font-mono text-emerald-400 mb-1">
                            Version {comparisonDiff.compare_version_number} (Compared)
                          </span>
                          <pre className="font-mono text-[11px] whitespace-pre-wrap overflow-x-auto">
                            {typeof diff.new_value === 'object'
                              ? JSON.stringify(diff.new_value, null, 2)
                              : String(diff.new_value ?? 'None')}
                          </pre>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          <div className="flex justify-end pt-2 border-t border-[#1b1f2d]">
            <Button variant="secondary" onClick={() => setIsCompareModalOpen(false)}>
              Close
            </Button>
          </div>
        </div>
      </Modal>

      {/* ========================================================= */}
      {/* MODAL 4: AGENT METADATA SETTINGS */}
      {/* ========================================================= */}
      <Modal
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        title="Edit Agent Metadata"
        description={`Update system record for ${agent.name}`}
        maxWidth="md"
      >
        <form onSubmit={handleEditSubmit} className="space-y-4">
          {editError && (
            <div className="rounded border border-rose-900/50 bg-rose-950/30 p-2.5 text-xs text-rose-300">
              {editError}
            </div>
          )}

          <Input
            label="Employee Name"
            required
            value={editForm.name || ''}
            onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
          />

          <Input
            label="Role"
            required
            value={editForm.role || ''}
            onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
          />

          <Select
            label="Lifecycle Status"
            options={AGENT_STATUSES}
            value={editForm.status || 'DRAFT'}
            onChange={(e) => setEditForm({ ...editForm, status: e.target.value as AgentStatus })}
          />

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">Description</label>
            <textarea
              rows={3}
              className="block w-full rounded-md border border-[#232736] bg-[#10121a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              value={editForm.description || ''}
              onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
            />
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#1b1f2d]">
            <Button type="button" variant="ghost" onClick={() => setIsEditModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" isLoading={isSubmittingMeta}>
              Save Changes
            </Button>
          </div>
        </form>
      </Modal>

      {/* ADD INPUT VARIABLE MODAL */}
      <Modal
        isOpen={isAddInputModalOpen}
        onClose={() => setIsAddInputModalOpen(false)}
        title="Add Input Variable"
        description="Define a parameter passed to the agent at session start."
        maxWidth="md"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!newInputName.trim()) return;
            const variable = {
              name: newInputName.trim(),
              description: newInputDesc.trim(),
              data_type: newInputType,
              default_value: newInputDefault.trim() || null,
              required: newInputRequired,
              source: newInputSource,
              extraction_instructions: '',
            };
            updateDraft((prev) => ({
              ...prev,
              variables: {
                ...prev.variables,
                inputs: [...prev.variables.inputs, variable],
              },
            }));
            setNewInputName('');
            setNewInputDesc('');
            setNewInputDefault('');
            setNewInputRequired(false);
            setIsAddInputModalOpen(false);
          }}
          className="space-y-4"
        >
          <Input
            label="Variable Identifier"
            required
            placeholder="e.g. caller_phone"
            value={newInputName}
            onChange={(e) => setNewInputName(e.target.value.replace(/[^a-zA-Z0-9_]/g, ''))}
            helperText="Alphanumeric identifier used as {{variable_name}}."
          />

          <Select
            label="Source"
            options={[
              { value: 'CRM or lead database', label: 'CRM or lead database' },
              { value: 'Campaign/contact data', label: 'Campaign/contact data' },
              { value: 'Call metadata', label: 'Call metadata (Telephony Caller ID)' },
              { value: 'Caller-provided information', label: 'Caller-provided information' },
            ]}
            value={newInputSource}
            onChange={(e) => setNewInputSource(e.target.value)}
          />

          <div className="grid grid-cols-2 gap-4">
            <Select
              label="Data Type"
              options={[
                { value: 'string', label: 'string' },
                { value: 'number', label: 'number' },
                { value: 'boolean', label: 'boolean' },
                { value: 'array', label: 'array' },
              ]}
              value={newInputType}
              onChange={(e) => setNewInputType(e.target.value)}
            />

            <Input
              label="Default Value (optional)"
              placeholder="e.g. Prestige Estates"
              value={newInputDefault}
              onChange={(e) => setNewInputDefault(e.target.value)}
            />
          </div>

          <div className="flex items-center gap-2 pt-1">
            <input
              type="checkbox"
              id="req-checkbox"
              checked={newInputRequired}
              onChange={(e) => setNewInputRequired(e.target.checked)}
              className="rounded border-[#232736] bg-[#10121a] text-[#00df8f] focus:ring-[#00df8f]"
            />
            <label htmlFor="req-checkbox" className="text-xs text-slate-300 font-medium cursor-pointer">
              Required variable (must be supplied at session start)
            </label>
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">Description</label>
            <textarea
              rows={2}
              className="block w-full rounded-md border border-[#232736] bg-[#10121a] p-2 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f]"
              placeholder="Usage context and expected format..."
              value={newInputDesc}
              onChange={(e) => setNewInputDesc(e.target.value)}
            />
          </div>

          <div className="flex justify-end gap-3 pt-3 border-t border-[#1b1f2d]">
            <Button type="button" variant="ghost" onClick={() => setIsAddInputModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={!newInputName.trim()}>
              Add Input Variable
            </Button>
          </div>
        </form>
      </Modal>

      {/* ADD OUTPUT VARIABLE MODAL */}
      <Modal
        isOpen={isAddOutputModalOpen}
        onClose={() => setIsAddOutputModalOpen(false)}
        title="Add Output Variable"
        description="Define a qualification outcome captured during conversation and synced back to CRM."
        maxWidth="md"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!newOutputName.trim()) return;
            const variable = {
              name: newOutputName.trim(),
              description: '',
              data_type: newOutputType,
              default_value: null,
              required: false,
              extraction_instructions: newOutputDesc.trim(),
            };
            updateDraft((prev) => ({
              ...prev,
              variables: {
                ...prev.variables,
                outputs: [...prev.variables.outputs, variable],
              },
            }));
            setNewOutputName('');
            setNewOutputDesc('');
            setIsAddOutputModalOpen(false);
          }}
          className="space-y-4"
        >
          <Input
            label="Outcome Identifier"
            required
            placeholder="e.g. buyer_budget"
            value={newOutputName}
            onChange={(e) => setNewOutputName(e.target.value.replace(/[^a-zA-Z0-9_]/g, ''))}
            helperText="Field name committed into lead disposition record."
          />

          <Select
            label="Data Type"
            options={[
              { value: 'string', label: 'string' },
              { value: 'number', label: 'number' },
              { value: 'boolean', label: 'boolean' },
              { value: 'enum', label: 'enum' },
            ]}
            value={newOutputType}
            onChange={(e) => setNewOutputType(e.target.value)}
          />

          <div className="space-y-1.5">
            <label className="block text-xs font-medium text-slate-300">Extraction Instructions</label>
            <textarea
              rows={3}
              className="block w-full rounded-md border border-[#232736] bg-[#10121a] p-2 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f]"
              placeholder="e.g. Extract the maximum budget confirmed by caller in INR or Lakhs/Crores."
              value={newOutputDesc}
              onChange={(e) => setNewOutputDesc(e.target.value)}
            />
          </div>

          <div className="flex justify-end gap-3 pt-3 border-t border-[#1b1f2d]">
            <Button type="button" variant="ghost" onClick={() => setIsAddOutputModalOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={!newOutputName.trim()}>
              Add Output Variable
            </Button>
          </div>
        </form>
      </Modal>

      {/* Voice picker (Sarvam voices) */}
      <VoicePickerModal
        isOpen={isVoicePickerOpen}
        onClose={() => {
          setIsVoicePickerOpen(false);
          if (voicePicked) {
            setVoicePicked(false);
            handleVoiceChosen();
          }
        }}
        selectedVoiceId={config.voice.voice_id}
        language={config.languages?.primary}
        provider={config.voice.provider}
        onSelectVoice={(voice) => {
          updateDraft((prev) => ({
            ...prev,
            voice: {
              ...prev.voice,
              provider: voice.provider || 'sarvam',
              voice_id: voice.id,
              language: voice.language || prev.voice.language || 'en-IN',
            },
            providers: { ...prev.providers, tts: voice.provider || 'sarvam' },
          }));
          setVoicePicked(true);
        }}
      />
    </div>
  );
};
