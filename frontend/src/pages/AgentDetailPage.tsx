import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate, Link, useSearchParams } from 'react-router-dom';
import {
  Bot,
  ArrowLeft,
  Building2,
  Calendar,
  Clock,
  Edit2,
  Sliders,
  History,
  FileCode,
  AlertTriangle,
  Info,
  CheckCircle,
  Save,
  Check,
  Plus,
  Trash2,
  Layers,
  Wrench,
  Link2,
  Volume2,
  VolumeX,
  Play,
  Square,
  Sparkles,
  Radio,
  RefreshCw,
  Cpu,
  Globe,
  MessageSquare,
  ShieldAlert,
  ArrowRight,
  RotateCcw,
  Eye,
  GitCompare,
  FlaskConical,
  PhoneCall,
  Copy,
  ExternalLink,
  ShieldCheck,
  Database,
  ListChecks,
  HelpCircle,
} from 'lucide-react';
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
  Integration,
  CartesiaVoice,
  VersionComparison,
  EMPTY_CALL_LIMITS,
} from '../types';
// Cartesia voice picker is kept in components/voice/VoicePickerModal.tsx but not used: voices come from Sarvam
// import { VoicePickerModal } from '../components/voice/VoicePickerModal';
import { SarvamVoicePickerModal as VoicePickerModal } from '../components/voice/SarvamVoicePickerModal';
import { AgentTestingWorkbench } from '../components/testing/AgentTestingWorkbench';
import { CallLimitsEditor } from '../components/agents/CallLimitsEditor';
import { Card } from '../components/common/Card';
import { Button } from '../components/common/Button';
import { StatusBadge, Badge } from '../components/common/Badge';
import { Modal } from '../components/common/Modal';
import { Input } from '../components/common/Input';
import { Select } from '../components/common/Select';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import { runtimeService } from '../services/runtime';
import {
  AVAILABLE_LANGUAGES,
  getLanguageOptions,
  getProviderOptions,
  LLM_PROVIDER_OPTIONS,
  STT_PROVIDER_OPTIONS,
  TELEPHONY_PROVIDER_OPTIONS,
  TTS_PROVIDER_OPTIONS,
} from '../constants/agentOptions';

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
  const [integrationsList, setIntegrationsList] = useState<Integration[]>([]);

  // Navigation tab (?tab=tests opens the testing step directly)
  const [searchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState<
    | 'instructions'
    | 'variables'
    | 'knowledge'
    | 'tools'
    | 'settings'
    | 'tests'
    | 'versions'
  >(searchParams.get('tab') === 'tests' ? 'tests' : 'instructions');

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  // Actions state
  const [isSaving, setIsSaving] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isSimulatingMockCall, setIsSimulatingMockCall] = useState(false);

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
  const { token } = useAuth();
  const [voicesList, setVoicesList] = useState<CartesiaVoice[]>([]);
  const [isVoicePickerOpen, setIsVoicePickerOpen] = useState(false);
  const [isPlayingPreview, setIsPlayingPreview] = useState(false);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
        previewAudioRef.current = null;
      }
    };
  }, []);

  const handleTogglePreview = (voiceId?: string | null) => {
    if (isPlayingPreview) {
      if (previewAudioRef.current) {
        previewAudioRef.current.pause();
        previewAudioRef.current.currentTime = 0;
        previewAudioRef.current = null;
      }
      setIsPlayingPreview(false);
      setIsPreviewLoading(false);
      return;
    }

    const effectiveId = voiceId || 'a0e99841-438c-4a64-b679-ae501e7d6091';
    setIsPreviewLoading(true);
    const voiceObj = voicesList.find((v) => v.id === effectiveId);
    const previewUrl = voiceObj?.preview_url || catalogsService.getVoicePreviewUrl(effectiveId, token);
    const audio = new Audio(previewUrl);
    previewAudioRef.current = audio;

    audio.oncanplay = () => {
      setIsPreviewLoading(false);
      setIsPlayingPreview(true);
    };

    audio.onended = () => {
      setIsPlayingPreview(false);
      previewAudioRef.current = null;
    };

    audio.onerror = () => {
      setIsPlayingPreview(false);
      setIsPreviewLoading(false);
      previewAudioRef.current = null;
    };

    audio.play().catch(() => {
      setIsPlayingPreview(false);
      setIsPreviewLoading(false);
    });
  };

  // Edit Metadata Modal State
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editForm, setEditForm] = useState<AgentUpdateInput>({});
  const [editError, setEditError] = useState<string | null>(null);
  const [isSubmittingMeta, setIsSubmittingMeta] = useState(false);

  // List Item Draft Inputs
  const [newResponsibility, setNewResponsibility] = useState('');
  const [newRule, setNewRule] = useState('');
  const [newRestriction, setNewRestriction] = useState('');
  const [newEscalation, setNewEscalation] = useState('');
  const [newLanguage, setNewLanguage] = useState('');
  const [newInputVariable, setNewInputVariable] = useState('');
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
      const [agentData, versionsData, configData, knwData, toolsData, intsData, voicesData] = await Promise.all([
        agentsService.get(id),
        agentsService.getVersions(id),
        configurationService.getConfiguration(id),
        catalogsService.listKnowledge(),
        catalogsService.listTools(),
        catalogsService.listIntegrations(),
        // Cartesia: catalogsService.listVoices() — voices now come from Sarvam
        catalogsService.listSarvamVoices().catch(() => []),
      ]);

      setAgent(agentData);
      setVersions(versionsData);
      setConfig(normalizeConfig(configData.configuration));
      setKnowledgeList(knwData);
      setToolsList(toolsData);
      setIntegrationsList(intsData);
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

  // Create Immutable Version Snapshot
  const handleCreateVersion = async () => {
    if (!id) return;
    if (isDirty) {
      if (!window.confirm('You have unsaved changes. Save and freeze into a new version?')) {
        return;
      }
    }
    setIsPublishing(true);
    setActionSuccess(null);
    try {
      if (isDirty && config) {
        await configurationService.updateConfiguration(id, config);
        setIsDirty(false);
      }
      const newVersion = await configurationService.createVersion(id);
      setActionSuccess(`Immutable Version ${newVersion.version_number} published successfully!`);
      const updatedVersions = await agentsService.getVersions(id);
      setVersions(updatedVersions);
      setTimeout(() => setActionSuccess(null), 4000);
    } catch (err: any) {
      alert(`Publish failed: ${err.message || 'Validation error prevented publishing.'}`);
    } finally {
      setIsPublishing(false);
    }
  };

  const handleSimulateMockCall = async () => {
    if (!id || versions.length === 0) return;
    setIsSimulatingMockCall(true);
    try {
      const result = await runtimeService.simulateMockCall(id, versions[0].id, [
        'I am looking for a 3 BHK apartment in Whitefield under 1.2 Cr.',
        'Yes, please schedule a site visit for this Saturday.',
      ]);
      setActionSuccess(`Simulated call ${result.call_id} completed with ${result.event_count} runtime events.`);
      setTimeout(() => setActionSuccess(null), 5000);
    } catch (err: any) {
      setActionSuccess(null);
      alert(`Mock call failed: ${err.message || 'Runtime simulation failed.'}`);
    } finally {
      setIsSimulatingMockCall(false);
    }
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
      setActiveTab('instructions');
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

  // Integration Attachment Toggle
  const handleToggleIntegration = async (integrationId: string) => {
    if (!id || !config) return;
    const isAttached = config.integrations.includes(integrationId);
    try {
      if (isAttached) {
        await catalogsService.detachIntegration(id, integrationId);
        updateDraft((prev) => ({
          ...prev,
          integrations: prev.integrations.filter((i) => i !== integrationId),
        }));
      } else {
        await catalogsService.attachIntegration(id, integrationId);
        updateDraft((prev) => ({
          ...prev,
          integrations: [...prev.integrations, integrationId],
        }));
      }
    } catch (err: any) {
      alert(`Failed to update integration: ${err.message}`);
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
            variant="ghost"
            size="sm"
            onClick={() => setIsEditModalOpen(true)}
            title="Edit Agent Identity and Status"
          >
            <Edit2 className="h-3.5 w-3.5 mr-1.5 text-slate-400" /> Identity
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={handleValidateSpec}
            isLoading={isValidating}
            title="Validate configuration completeness against canonical specification"
          >
            <Check className="h-3.5 w-3.5 mr-1.5 text-blue-400" /> Validate Spec
          </Button>

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

          <Button
            variant="primary"
            size="sm"
            onClick={() => setActiveTab('tests')}
            className="bg-emerald-600 hover:bg-emerald-500 text-white border-none shadow-md"
            title="Switch to Tests tab to run deterministic voice scenarios"
          >
            <FlaskConical className="h-3.5 w-3.5 mr-1.5" /> Test Agent
          </Button>

          <Button
            variant="primary"
            size="sm"
            onClick={handleCreateVersion}
            isLoading={isPublishing}
            title="Commit current draft as an immutable version snapshot"
          >
            <History className="h-3.5 w-3.5 mr-1.5" /> Commit Version
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setActiveTab('versions')}
            title="View immutable version history"
          >
            <History className="h-3.5 w-3.5 mr-1.5 text-slate-400" /> History ({versions.length})
          </Button>
        </div>
      </div>

      {/* CANVAS SECTION NAVIGATION (STRICT ORDER: INSTRUCTIONS, VARIABLES, TOOLS, SETTINGS, TESTS) */}
      <div className="flex overflow-x-auto rounded-xl border border-[#1b1f2d] bg-[#0c0e14] p-1 no-scrollbar">
        {[
          { id: 'instructions', label: '1. Instructions', icon: FileCode },
          { id: 'variables', label: `2. Variables (${config.variables.inputs.length + config.variables.outputs.length})`, icon: Sliders },
          { id: 'tools', label: `3. Tools (${config.tools.length})`, icon: Wrench },
          { id: 'settings', label: '4. Settings', icon: Volume2 },
          { id: 'tests', label: '5. Tests', icon: FlaskConical },
          { id: 'versions', label: `Versions (${versions.length})`, icon: History },
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

      {/* ========================================================= */}
      {/* TAB 1: OVERVIEW */}
      {/* ========================================================= */}
      {activeTab === 'instructions' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card title="Agent Specification Summary" className="md:col-span-2">
            <div className="space-y-4 text-xs">
              <div>
                <h4 className="font-semibold text-slate-400">Primary Goal</h4>
                <p className="mt-1 text-sm font-medium text-slate-200">
                  {config.instructions.primary_goal || 'No primary goal defined yet.'}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-4 pt-3 border-t border-[#1b1f2d]">
                <div>
                  <h4 className="font-semibold text-slate-400">Persona &amp; Demeanor</h4>
                  <p className="mt-1 text-slate-200">
                    {config.identity.persona} &bull; <span className="text-slate-400">{config.conversation.tone}</span>
                  </p>
                </div>
                <div>
                  <h4 className="font-semibold text-slate-400">Operating Client</h4>
                  <p className="mt-1 text-slate-200 font-semibold">{agent.client_name || agent.client_id}</p>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4 pt-3 border-t border-[#1b1f2d]">
                <div>
                  <span className="text-slate-500 block">Responsibilities</span>
                  <span className="text-sm font-bold text-slate-200">{config.instructions.responsibilities.length}</span>
                </div>
                <div>
                  <span className="text-slate-500 block">Behavioral Rules</span>
                  <span className="text-sm font-bold text-slate-200">{config.instructions.rules.length}</span>
                </div>
                <div>
                  <span className="text-slate-500 block">Escalation Rules</span>
                  <span className="text-sm font-bold text-slate-200">{config.instructions.escalation_rules.length}</span>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4 pt-3 border-t border-[#1b1f2d]">
                <div>
                  <span className="text-slate-500 block">Knowledge Sources</span>
                  <span className="text-sm font-bold text-[#00df8f]">{config.knowledge_sources.length} Attached</span>
                </div>
                <div>
                  <span className="text-slate-500 block">Available Tools</span>
                  <span className="text-sm font-bold text-emerald-400">{config.tools.length} Attached</span>
                </div>
                <div>
                  <span className="text-slate-500 block">Integrations</span>
                  <span className="text-sm font-bold text-purple-400">{config.integrations.length} Attached</span>
                </div>
              </div>
            </div>
          </Card>

          <Card title="Runtime Blueprint" className="md:col-span-1">
            <div className="space-y-3 text-xs">
              <div>
                <span className="text-slate-500 block">STT Provider</span>
                <span className="font-semibold text-slate-200">{config.providers.stt.toUpperCase()}</span>
              </div>
              <div>
                <span className="text-slate-500 block">LLM Provider</span>
                <span className="font-semibold text-slate-200">{config.providers.llm.toUpperCase()}</span>
              </div>
              <div>
                <span className="text-slate-500 block">TTS Voice</span>
                <span className="font-semibold text-slate-200">
                  Sarvam &bull; {voicesList.find((v) => v.id === config.voice.voice_id)?.name || (config.voice.voice_id ? config.voice.voice_id.substring(0, 12) : 'Default (Shubh)')}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block">Telephony Engine</span>
                <span className="font-semibold text-slate-200">
                  {config.providers.telephony ? config.providers.telephony.toUpperCase() : 'NONE (WEB BROWSER)'}
                </span>
              </div>
              <div className="pt-3 border-t border-[#102d38]">
                <span className="text-slate-500 block">Immutable Versions</span>
                <span className="font-semibold text-[#00df8f]">{versions.length} Published Snapshots</span>
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 1: INITIAL GREETING WITH DYNAMIC PLACEHOLDERS */}
      {/* ========================================================= */}
      {activeTab === 'instructions' && (
        <Card
          title="Initial Greeting &amp; Dynamic Placeholders"
          subtitle="The opening statement spoken on session start. Supports caller &amp; business placeholders like {{user_name}} and {{company_name}}."
        >
          <div className="space-y-4 text-xs">
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-300">
                Spoken Greeting Message
              </label>
              <textarea
                rows={2}
                className="block w-full rounded-md border border-[#232736] bg-[#10121a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-[#00df8f] focus:ring-1 focus:ring-[#00df8f] font-mono"
                value={config.conversation.greeting}
                onChange={(e) =>
                  updateDraft((prev) => ({
                    ...prev,
                    conversation: { ...prev.conversation, greeting: e.target.value },
                  }))
                }
                placeholder="e.g. Hello, am I speaking with {{user_name}}? I'm calling from {{company_name}} regarding your property enquiry."
              />
            </div>

            {/* Quick Variable Token Chips */}
            <div className="space-y-1.5">
              <span className="text-[11px] font-medium text-slate-400 block">
                Click to insert dynamic variable placeholder:
              </span>
              <div className="flex flex-wrap gap-1.5">
                {[
                  'user_name',
                  'company_name',
                  'property_viewed',
                  'enquiry_location',
                  'enquiry_budget',
                  'enquiry_bhk',
                ].map((token) => (
                  <button
                    key={token}
                    type="button"
                    onClick={() => {
                      const tag = `{{${token}}}`;
                      const current = config.conversation.greeting || '';
                      const updated = current ? `${current} ${tag}` : tag;
                      updateDraft((prev) => ({
                        ...prev,
                        conversation: { ...prev.conversation, greeting: updated },
                      }));
                    }}
                    className="flex items-center gap-1 rounded bg-[#09222c] border border-[#1b4e5f] px-2 py-1 text-[11px] font-mono text-[#00df8f] hover:bg-[#0d3443] transition-colors"
                  >
                    <Plus className="h-3 w-3" /> &#123;&#123;{token}&#125;&#125;
                  </button>
                ))}
              </div>
            </div>

            {/* Dynamic Greeting Resolution Simulator Box */}
            <div className="rounded-xl border border-[#143c49] bg-gradient-to-r from-[#061820] to-[#0a232f] p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-200 flex items-center gap-1.5 text-xs">
                  <Sparkles className="h-3.5 w-3.5 text-[#00df8f]" /> Runtime Greeting Resolution Simulator
                </span>
                <span className="rounded bg-emerald-950/80 border border-emerald-800/50 px-2 py-0.5 text-[10px] text-emerald-300 font-medium">
                  Played Once per Session &bull; Zero Raw Placeholders Spoken
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="rounded-lg border border-[#1c3844] bg-[#081820] p-3 space-y-1">
                  <div className="flex items-center gap-2">
                    <CheckCircle className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="text-[11px] font-semibold text-slate-300">
                      When caller name is known ({'{'}user_name: &quot;Rahul Sharma&quot;{'}'}):
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-200 font-mono italic pl-5">
                    &ldquo;Hello, am I speaking with <span className="text-[#00df8f] font-bold">Rahul Sharma</span>? I&apos;m calling from <span className="text-[#00df8f] font-bold">{config.business_context.business_name || 'Prestige Estates'}</span> regarding your property enquiry.&rdquo;
                  </p>
                </div>

                <div className="rounded-lg border border-[#1c3844] bg-[#081820] p-3 space-y-1">
                  <div className="flex items-center gap-2">
                    <Info className="h-3.5 w-3.5 text-blue-400" />
                    <span className="text-[11px] font-semibold text-slate-300">
                      When caller name is missing (neutral fallback):
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-200 font-mono italic pl-5">
                    &ldquo;Hello, <span className="text-blue-300 font-bold">thank you for connecting</span>. I&apos;m calling from <span className="text-[#00df8f] font-bold">{config.business_context.business_name || 'Prestige Estates'}</span> regarding your property enquiry.&rdquo;
                  </p>
                </div>
              </div>

              <p className="text-[10px] text-slate-400 leading-relaxed">
                &bull; The runtime engine resolves placeholders dynamically from CRM data. Unresolved placeholders are never spoken aloud over the telephone line or audio stream.
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* ========================================================= */}
      {/* TAB 2: IDENTITY */}
      {/* ========================================================= */}
      {activeTab === 'instructions' && (
        <Card title="Agent Identity &amp; Persona" subtitle="Defines how the AI employee introduces itself and its personality traits">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
            <Input
              label="Agent Public Name"
              value={config.identity.name}
              onChange={(e) =>
                updateDraft((prev) => ({
                  ...prev,
                  identity: { ...prev.identity, name: e.target.value },
                }))
              }
              placeholder="e.g. Sarah Connor"
            />

            <Input
              label="Representing Organization"
              value={config.identity.organization}
              onChange={(e) =>
                updateDraft((prev) => ({
                  ...prev,
                  identity: { ...prev.identity, organization: e.target.value },
                }))
              }
              placeholder="e.g. Apex Health Clinic"
            />

            <div className="space-y-1.5 md:col-span-2">
              <label className="block text-xs font-medium text-slate-300">Persona Description</label>
              <textarea
                rows={3}
                className="block w-full rounded-md border border-[#232736] bg-[#10121a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                value={config.identity.persona}
                onChange={(e) =>
                  updateDraft((prev) => ({
                    ...prev,
                    identity: { ...prev.identity, persona: e.target.value },
                  }))
                }
                placeholder="e.g. Warm, articulate, reassuring, and attentive healthcare assistant..."
              />
            </div>

            <div className="space-y-1.5 md:col-span-2">
              <label className="block text-xs font-medium text-slate-300">Tone &amp; Demeanor</label>
              <textarea
                rows={2}
                className="block w-full rounded-md border border-[#232736] bg-[#10121a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                value={config.conversation.tone}
                onChange={(e) =>
                  updateDraft((prev) => ({
                    ...prev,
                    conversation: { ...prev.conversation, tone: e.target.value },
                  }))
                }
                placeholder="e.g. Empathetic, crisp, polite, patient, and concise."
              />
            </div>
          </div>
        </Card>
      )}

      {/* ========================================================= */}
      {/* TAB 3: BUSINESS CONTEXT */}
      {/* ========================================================= */}
      {activeTab === 'instructions' && (
        <Card title="Business Context" subtitle="Client organization background provided to ground agent conversations">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
            <Input
              label="Business / Client Name"
              value={config.business_context.business_name}
              onChange={(e) =>
                updateDraft((prev) => ({
                  ...prev,
                  business_context: { ...prev.business_context, business_name: e.target.value },
                }))
              }
            />

            <Input
              label="Business Domain / Type"
              value={config.business_context.business_type}
              onChange={(e) =>
                updateDraft((prev) => ({
                  ...prev,
                  business_context: { ...prev.business_context, business_type: e.target.value },
                }))
              }
            />

            <Input
              label="Physical Location / Region"
              value={config.business_context.location}
              onChange={(e) =>
                updateDraft((prev) => ({
                  ...prev,
                  business_context: { ...prev.business_context, location: e.target.value },
                }))
              }
              placeholder="e.g. New York, NY (UTC region)"
            />

            <Input
              label="Operating Business Hours"
              value={config.business_context.business_hours?.monday_friday || ''}
              onChange={(e) =>
                updateDraft((prev) => ({
                  ...prev,
                  business_context: {
                    ...prev.business_context,
                    business_hours: {
                      ...prev.business_context.business_hours,
                      monday_friday: e.target.value,
                    },
                  },
                }))
              }
              placeholder="e.g. 09:00 - 18:00"
            />

            <Input
              label="Primary Contact Person"
              value={config.business_context.contact_information?.name || ''}
              onChange={(e) =>
                updateDraft((prev) => ({
                  ...prev,
                  business_context: {
                    ...prev.business_context,
                    contact_information: {
                      ...prev.business_context.contact_information,
                      name: e.target.value,
                    },
                  },
                }))
              }
              placeholder="e.g. Dr. Jane Smith"
            />

            <Input
              label="Contact Email"
              value={config.business_context.contact_information?.email || ''}
              onChange={(e) =>
                updateDraft((prev) => ({
                  ...prev,
                  business_context: {
                    ...prev.business_context,
                    contact_information: {
                      ...prev.business_context.contact_information,
                      email: e.target.value,
                    },
                  },
                }))
              }
              placeholder="e.g. contact@business.com"
            />
          </div>
        </Card>
      )}

      {/* ========================================================= */}
      {/* TAB 4: INSTRUCTIONS */}
      {/* ========================================================= */}
      {activeTab === 'instructions' && (
        <div className="space-y-6">
          {/* Primary Goal */}
          <Card title="Primary Operational Goal" subtitle="The singular core objective the voice agent is tasked with fulfilling">
            <textarea
              rows={3}
              className="block w-full rounded-md border border-[#232736] bg-[#10121a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              value={config.instructions.primary_goal}
              onChange={(e) =>
                updateDraft((prev) => ({
                  ...prev,
                  instructions: { ...prev.instructions, primary_goal: e.target.value },
                }))
              }
              placeholder="e.g. Professionally greet callers, answer questions about clinic services, verify availability, and schedule appointments."
            />
          </Card>

          {/* Responsibilities */}
          <Card
            title={`Core Responsibilities (${config.instructions.responsibilities.length})`}
            subtitle="Specific operational duties the agent is authorized and expected to perform"
          >
            <div className="space-y-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  className="block flex-1 rounded-md border border-[#232736] bg-[#10121a] px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  placeholder="Add a new responsibility..."
                  value={newResponsibility}
                  onChange={(e) => setNewResponsibility(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newResponsibility.trim()) {
                      updateDraft((prev) => ({
                        ...prev,
                        instructions: {
                          ...prev.instructions,
                          responsibilities: [...prev.instructions.responsibilities, newResponsibility.trim()],
                        },
                      }));
                      setNewResponsibility('');
                    }
                  }}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    if (newResponsibility.trim()) {
                      updateDraft((prev) => ({
                        ...prev,
                        instructions: {
                          ...prev.instructions,
                          responsibilities: [...prev.instructions.responsibilities, newResponsibility.trim()],
                        },
                      }));
                      setNewResponsibility('');
                    }
                  }}
                >
                  <Plus className="h-3.5 w-3.5 mr-1" /> Add
                </Button>
              </div>

              <div className="divide-y divide-[#1b1f2d] rounded-md border border-[#1b1f2d] bg-[#0c0e14]">
                {config.instructions.responsibilities.length === 0 ? (
                  <div className="p-4 text-xs text-slate-500 text-center">No responsibilities added yet.</div>
                ) : (
                  config.instructions.responsibilities.map((item, idx) => (
                    <div key={idx} className="flex items-center justify-between p-2.5 text-xs text-slate-200">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-slate-500">{idx + 1}.</span>
                        <span>{item}</span>
                      </div>
                      <button
                        onClick={() =>
                          updateDraft((prev) => ({
                            ...prev,
                            instructions: {
                              ...prev.instructions,
                              responsibilities: prev.instructions.responsibilities.filter((_, i) => i !== idx),
                            },
                          }))
                        }
                        className="text-slate-500 hover:text-rose-400 p-1"
                        title="Remove"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </Card>

          {/* Behavioral Rules */}
          <Card
            title={`Behavioral Rules (${config.instructions.rules.length})`}
            subtitle="Strict conversational guidelines and etiquette"
          >
            <div className="space-y-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  className="block flex-1 rounded-md border border-[#232736] bg-[#10121a] px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  placeholder="Add a new behavioral rule..."
                  value={newRule}
                  onChange={(e) => setNewRule(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newRule.trim()) {
                      updateDraft((prev) => ({
                        ...prev,
                        instructions: {
                          ...prev.instructions,
                          rules: [...prev.instructions.rules, newRule.trim()],
                        },
                      }));
                      setNewRule('');
                    }
                  }}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    if (newRule.trim()) {
                      updateDraft((prev) => ({
                        ...prev,
                        instructions: {
                          ...prev.instructions,
                          rules: [...prev.instructions.rules, newRule.trim()],
                        },
                      }));
                      setNewRule('');
                    }
                  }}
                >
                  <Plus className="h-3.5 w-3.5 mr-1" /> Add
                </Button>
              </div>

              <div className="divide-y divide-[#1b1f2d] rounded-md border border-[#1b1f2d] bg-[#0c0e14]">
                {config.instructions.rules.length === 0 ? (
                  <div className="p-4 text-xs text-slate-500 text-center">No behavioral rules added yet.</div>
                ) : (
                  config.instructions.rules.map((item, idx) => (
                    <div key={idx} className="flex items-center justify-between p-2.5 text-xs text-slate-200">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-slate-500">{idx + 1}.</span>
                        <span>{item}</span>
                      </div>
                      <button
                        onClick={() =>
                          updateDraft((prev) => ({
                            ...prev,
                            instructions: {
                              ...prev.instructions,
                              rules: prev.instructions.rules.filter((_, i) => i !== idx),
                            },
                          }))
                        }
                        className="text-slate-500 hover:text-rose-400 p-1"
                        title="Remove"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </Card>

          {/* Restrictions */}
          <Card
            title={`Negative Boundaries & Restrictions (${config.instructions.restrictions.length})`}
            subtitle="Actions, topics, or disclosures the agent must strictly avoid"
          >
            <div className="space-y-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  className="block flex-1 rounded-md border border-[#232736] bg-[#10121a] px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  placeholder="Add a restriction (e.g. Never give clinical diagnoses)..."
                  value={newRestriction}
                  onChange={(e) => setNewRestriction(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newRestriction.trim()) {
                      updateDraft((prev) => ({
                        ...prev,
                        instructions: {
                          ...prev.instructions,
                          restrictions: [...prev.instructions.restrictions, newRestriction.trim()],
                        },
                      }));
                      setNewRestriction('');
                    }
                  }}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    if (newRestriction.trim()) {
                      updateDraft((prev) => ({
                        ...prev,
                        instructions: {
                          ...prev.instructions,
                          restrictions: [...prev.instructions.restrictions, newRestriction.trim()],
                        },
                      }));
                      setNewRestriction('');
                    }
                  }}
                >
                  <Plus className="h-3.5 w-3.5 mr-1" /> Add
                </Button>
              </div>

              <div className="divide-y divide-[#1b1f2d] rounded-md border border-[#1b1f2d] bg-[#0c0e14]">
                {config.instructions.restrictions.length === 0 ? (
                  <div className="p-4 text-xs text-slate-500 text-center">No restrictions added yet.</div>
                ) : (
                  config.instructions.restrictions.map((item, idx) => (
                    <div key={idx} className="flex items-center justify-between p-2.5 text-xs text-rose-300">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-rose-500">{idx + 1}.</span>
                        <span>{item}</span>
                      </div>
                      <button
                        onClick={() =>
                          updateDraft((prev) => ({
                            ...prev,
                            instructions: {
                              ...prev.instructions,
                              restrictions: prev.instructions.restrictions.filter((_, i) => i !== idx),
                            },
                          }))
                        }
                        className="text-slate-500 hover:text-rose-400 p-1"
                        title="Remove"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </Card>

          {/* Escalation Rules */}
          <Card
            title={`Escalation Rules (${config.instructions.escalation_rules.length})`}
            subtitle="Routing rules when situations exceed agent scope or an emergency arises"
          >
            <div className="space-y-3">
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="Add escalation rule (e.g. Transfer urgent emergency callers to human queue immediately)..."
                  className="block flex-1 rounded-md border border-[#232736] bg-[#10121a] px-3 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  value={newEscalation}
                  onChange={(e) => setNewEscalation(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && newEscalation.trim()) {
                      updateDraft((prev) => ({
                        ...prev,
                        instructions: {
                          ...prev.instructions,
                          escalation_rules: [...prev.instructions.escalation_rules, newEscalation.trim()],
                        },
                      }));
                      setNewEscalation('');
                    }
                  }}
                />
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    if (newEscalation.trim()) {
                      updateDraft((prev) => ({
                        ...prev,
                        instructions: {
                          ...prev.instructions,
                          escalation_rules: [...prev.instructions.escalation_rules, newEscalation.trim()],
                        },
                      }));
                      setNewEscalation('');
                    }
                  }}
                >
                  <Plus className="h-3.5 w-3.5 mr-1" /> Add
                </Button>
              </div>

              <div className="divide-y divide-[#1b1f2d] rounded-md border border-[#1b1f2d] bg-[#0c0e14]">
                {config.instructions.escalation_rules.length === 0 ? (
                  <div className="p-4 text-xs text-slate-500 text-center">No escalation rules configured.</div>
                ) : (
                  config.instructions.escalation_rules.map((item, idx) => (
                    <div key={idx} className="flex items-center justify-between p-2.5 text-xs text-amber-300">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-amber-500">{idx + 1}.</span>
                        <span>{item}</span>
                      </div>
                      <button
                        onClick={() =>
                          updateDraft((prev) => ({
                            ...prev,
                            instructions: {
                              ...prev.instructions,
                              escalation_rules: prev.instructions.escalation_rules.filter((_, i) => i !== idx),
                            },
                          }))
                        }
                        className="text-slate-500 hover:text-rose-400 p-1"
                        title="Remove"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 5: STRUCTURED CONVERSATION FLOW (PHASE 4) */}
      {/* ========================================================= */}
      {activeTab === 'instructions' && (
        <Card
          title="Structured Lead Qualification Conversation Flow"
          subtitle="Pre-configured multi-step conversational roadmap followed by the sales assistant"
        >
          <div className="space-y-3 text-xs">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {[
                {
                  step: 1,
                  title: 'Warm Initial Greeting & Caller Verification',
                  desc: 'Greet the caller, confirm identity (using {{user_name}} if known), and introduce representing company.',
                },
                {
                  step: 2,
                  title: 'Refer to Property Enquiry',
                  desc: 'Acknowledge the original enquiry and property/project viewed (e.g. Prestige Highline, 3 BHK in Whitefield).',
                },
                {
                  step: 3,
                  title: 'Validate Missing Buyer Requirements',
                  desc: 'Ask only for requirements not already present in the enquiry record; never repeatedly re-ask known data.',
                },
                {
                  step: 4,
                  title: 'Confirm Budget, Location, BHK & Timeline',
                  desc: 'Capture specific micro-markets, upper budget cap in Lakhs/Crores, preferred BHK configuration, and buying timeline.',
                },
                {
                  step: 5,
                  title: 'Query Approved Property Inventory',
                  desc: 'Invoke search_properties tool to find verified project matches based on confirmed location and budget criteria.',
                },
                {
                  step: 6,
                  title: 'Present Curated Property Matches',
                  desc: 'Pitch 1 to 2 matching projects concisely over phone audio, highlighting location, pricing, and possession date.',
                },
                {
                  step: 7,
                  title: 'Offer Site Visit or Senior Sales Callback',
                  desc: 'Check available calendar slots using check_site_visit_slots and offer an in-person walkthrough or coordinator call.',
                },
                {
                  step: 8,
                  title: 'Confirm Next Action Plan',
                  desc: 'Reiterate agreed next step clearly (WhatsApp brochure, site visit, or sales team callback).',
                },
                {
                  step: 9,
                  title: 'Commit Lead Qualification Outcome to CRM',
                  desc: 'Invoke update_lead_record to persist extracted budget, location, BHK, disposition, and next action.',
                },
                {
                  step: 10,
                  title: 'Professional Closing Farewell',
                  desc: 'Conclude conversation with a polite, appreciative closing without exerting aggressive pressure.',
                },
              ].map((item) => (
                <div
                  key={item.step}
                  className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-3 space-y-1 hover:border-[#00df8f]/30 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[#00df8f]/10 text-[10px] font-mono font-bold text-[#00df8f] border border-[#00df8f]/30">
                      {item.step}
                    </span>
                    <span className="font-semibold text-slate-200 text-[11px]">{item.title}</span>
                  </div>
                  <p className="text-[11px] text-slate-400 pl-7 leading-relaxed">{item.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* ========================================================= */}
      {/* TAB 5: CONVERSATION STYLE */}
      {/* ========================================================= */}
      {activeTab === 'instructions' && (
        <Card title="Conversational Flow &amp; Dynamics" subtitle="Greeting, closing farewell, conversational tone, verbosity, and turn-taking behavior">
          <div className="space-y-5 text-xs">
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-300">Initial Greeting Message</label>
              <textarea
                rows={2}
                className="block w-full rounded-md border border-[#232736] bg-[#10121a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                value={config.conversation.greeting}
                onChange={(e) =>
                  updateDraft((prev) => ({
                    ...prev,
                    conversation: { ...prev.conversation, greeting: e.target.value },
                  }))
                }
                placeholder="e.g. Thank you for calling. How may I assist you today?"
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-slate-300">Closing Farewell Message</label>
              <textarea
                rows={2}
                className="block w-full rounded-md border border-[#232736] bg-[#10121a] p-2.5 text-xs text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                value={config.conversation.farewell}
                onChange={(e) =>
                  updateDraft((prev) => ({
                    ...prev,
                    conversation: { ...prev.conversation, farewell: e.target.value },
                  }))
                }
                placeholder="e.g. Thank you for reaching out. Have a wonderful day!"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-5 pt-3 border-t border-[#1b1f2d]">
              <Input
                label="Tone Style"
                value={config.conversation.tone}
                onChange={(e) =>
                  updateDraft((prev) => ({
                    ...prev,
                    conversation: { ...prev.conversation, tone: e.target.value },
                  }))
                }
                placeholder="e.g. professional, empathetic, friendly"
              />

              <Select
                label="Verbosity Level"
                options={[
                  { value: 'concise', label: 'Concise (Direct, low word-count responses)' },
                  { value: 'balanced', label: 'Balanced (Natural conversational flow)' },
                  { value: 'detailed', label: 'Detailed (In-depth explanations)' },
                ]}
                value={config.conversation.verbosity}
                onChange={(e) =>
                  updateDraft((prev) => ({
                    ...prev,
                    conversation: {
                      ...prev.conversation,
                      verbosity: e.target.value,
                    },
                  }))
                }
              />

              <Select
                label="Interruption / Barge-in Behavior"
                options={[
                  { value: 'pause_and_listen', label: 'Pause & Listen (Instant barge-in)' },
                  { value: 'finish_sentence', label: 'Finish Sentence (Finish current thought)' },
                ]}
                value={config.conversation.interruption_behavior}
                onChange={(e) =>
                  updateDraft((prev) => ({
                    ...prev,
                    conversation: {
                      ...prev.conversation,
                      interruption_behavior: e.target.value,
                    },
                  }))
                }
              />
            </div>
          </div>
        </Card>
      )}

      {activeTab === 'instructions' && (
        <Card
          title="Call Limits &amp; Cost Controls"
          subtitle="Per-agent limits that cut wasted call minutes, AI model calls and voice characters"
        >
          <CallLimitsEditor
            limits={config.conversation.limits}
            onChange={(limits) =>
              updateDraft((prev) => ({
                ...prev,
                conversation: { ...prev.conversation, limits },
              }))
            }
          />
        </Card>
      )}

      {/* ========================================================= */}
      {/* TAB 6: LANGUAGES */}
      {/* ========================================================= */}
      {activeTab === 'settings' && (
        <Card title="Language &amp; Locale Configuration" subtitle="Primary spoken locale and supported languages">
          <div className="space-y-6 text-xs">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <Select
                label="Primary Spoken Language"
                options={getLanguageOptions(config.languages.primary)}
                value={config.languages.primary}
                onChange={(e) => {
                  const val = e.target.value;
                  updateDraft((prev) => ({
                    ...prev,
                    languages: {
                      ...prev.languages,
                      primary: val,
                      // Filter out new primary from secondary supported if it was there
                      supported: prev.languages.supported.filter((l) => l !== val),
                    },
                    voice: {
                      ...prev.voice,
                      language: val,
                    },
                  }));
                }}
                helperText="Primary locale for conversation prompts, speech recognition and voice synthesis."
              />
            </div>

            <div className="space-y-3 pt-4 border-t border-[#1b1f2d]">
              <div>
                <label className="block text-xs font-medium text-slate-300">Supported Languages</label>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  Additional languages this agent can understand and respond in during conversations.
                </p>
              </div>

              <div className="flex gap-2 max-w-lg items-center">
                <div className="flex-1">
                  <Select
                    placeholder="Choose language to add..."
                    options={AVAILABLE_LANGUAGES.filter(
                      (l) => l.value !== config.languages.primary && !config.languages.supported.includes(l.value)
                    )}
                    value={newLanguage}
                    onChange={(e) => setNewLanguage(e.target.value)}
                  />
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!newLanguage}
                  onClick={() => {
                    if (newLanguage && !config.languages.supported.includes(newLanguage)) {
                      updateDraft((prev) => ({
                        ...prev,
                        languages: {
                          ...prev.languages,
                          supported: [...prev.languages.supported, newLanguage],
                        },
                      }));
                      setNewLanguage('');
                    }
                  }}
                >
                  <Plus className="h-3.5 w-3.5 mr-1" /> Add
                </Button>
              </div>

              <div className="flex flex-wrap gap-2 pt-2">
                {config.languages.supported.length === 0 ? (
                  <span className="text-slate-500 text-xs italic">No secondary languages configured.</span>
                ) : (
                  config.languages.supported.map((lang, idx) => {
                    const langMeta = AVAILABLE_LANGUAGES.find((l) => l.value === lang);
                    return (
                      <span
                        key={idx}
                        className="flex items-center gap-2 rounded-md bg-[#101e28] border border-[#1b4353] px-3 py-1.5 text-xs text-slate-200"
                      >
                        <span className="font-semibold text-[#00df8f]">{lang}</span>
                        <span className="text-slate-400">
                          ({langMeta ? langMeta.label.split(' - ')[0] : lang})
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            updateDraft((prev) => ({
                              ...prev,
                              languages: {
                                ...prev.languages,
                                supported: prev.languages.supported.filter((_, i) => i !== idx),
                              },
                            }))
                          }
                          className="text-slate-500 hover:text-rose-400 ml-1 transition-colors font-bold text-sm"
                          title={`Remove ${lang}`}
                        >
                          &times;
                        </button>
                      </span>
                    );
                  })
                )}
              </div>
            </div>
          </div>
        </Card>
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
      {/* TAB 5: TESTS (final step: test the published AI Employee before deploying) */}
      {/* ========================================================= */}
      {activeTab === 'tests' && (
        <div className="space-y-6">
          <Card
            title="Test your AI Employee"
            subtitle="Final step before deploying: talk to the published version by voice, phone or chat, and run scenario regressions"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <p className="text-xs text-slate-300 max-w-2xl leading-relaxed">
                {versions.length === 0
                  ? 'Publish a version first (Versions tab); tests always run against an immutable published version.'
                  : 'Pick the version to test below, then start a browser voice call, call your phone, chat, or run the scenario suite.'}
              </p>
              <Button
                variant="secondary"
                onClick={handleSimulateMockCall}
                isLoading={isSimulatingMockCall}
                disabled={versions.length === 0}
                className="shrink-0"
              >
                <PhoneCall className="mr-1.5 h-3.5 w-3.5" /> Simulate Mock Call
              </Button>
            </div>
          </Card>

          <AgentTestingWorkbench agentId={agent.id} />
        </div>
      )}

      {/* ========================================================= */}
      {/* TAB 3: TOOLS (LOGICAL REAL ESTATE TOOLS & INTEGRATIONS) */}
      {/* ========================================================= */}
      {activeTab === 'tools' && (
        <div className="space-y-6">
          {/* LOGICAL TOOLS FOR REAL ESTATE QUALIFICATION */}
          <Card
            title="Core Logical Real Estate Tools (2)"
            subtitle="Autonomous capabilities the agent can invoke during calls to search inventory and update lead outcomes"
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Tool 1: search_properties */}
              <div className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-4 space-y-2.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-sm text-[#00df8f]">search_properties</span>
                    <span className="rounded bg-blue-950/60 border border-blue-900/50 px-1.5 py-0.5 text-[9px] font-bold text-blue-300">
                      PROPERTY STORE
                    </span>
                  </div>
                  <span className="text-[10px] text-slate-500 font-mono">Timeout: 10s</span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  Performs structured queries against approved residential inventory, filtering by price, location, and BHK.
                </p>
                <div className="rounded bg-[#121520] p-2 text-[10px] font-mono space-y-1">
                  <div><span className="text-slate-500">Inputs:</span> <span className="text-blue-300">location, budget_min, budget_max, bhk</span></div>
                  <div><span className="text-slate-500">Outputs:</span> <span className="text-slate-300">matching properties (property_id, project_name, price, bhk)</span></div>
                </div>
              </div>

              {/* Tool 2: update_lead_record */}
              <div className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-4 space-y-2.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-sm text-[#00df8f]">update_lead_record</span>
                    <span className="rounded bg-emerald-950/60 border border-emerald-900/50 px-1.5 py-0.5 text-[9px] font-bold text-emerald-300">
                      CRM WRITE-BACK
                    </span>
                  </div>
                  <span className="text-[10px] text-slate-500 font-mono">Timeout: 10s</span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  Commits confirmed buyer preferences, qualification status, and call outcome back to the CRM database record.
                </p>
                <div className="rounded bg-[#121520] p-2 text-[10px] font-mono space-y-1">
                  <div><span className="text-slate-500">Inputs:</span> <span className="text-blue-300">buyer_budget, buyer_location, qualification_status</span></div>
                  <div><span className="text-slate-500">Outputs:</span> <span className="text-slate-300">success: true, record_id</span></div>
                </div>
              </div>
            </div>
          </Card>

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

          {/* ATTACHED REAL ESTATE KNOWLEDGE CATALOG */}
          <Card
            title={`Knowledge Catalogs (${config.knowledge_sources.length} Attached)`}
            subtitle="Reference documents, property catalogs, and developer FAQs attached to ground agent answers"
          >
            <div className="divide-y divide-[#1b1f2d]">
              {knowledgeList.length === 0 ? (
                <div className="py-6 text-center text-xs text-slate-500">No knowledge sources available in catalog.</div>
              ) : (
                knowledgeList.map((knw) => {
                  const isAttached = config.knowledge_sources.includes(knw.id);
                  return (
                    <div key={knw.id} className="py-3.5 flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-200">{knw.name}</span>
                          <span className="rounded bg-[#1b1f2d] px-1.5 py-0.5 text-[10px] font-mono text-slate-400">
                            {knw.type}
                          </span>
                          <StatusBadge status={knw.status} />
                        </div>
                        <p className="text-xs text-slate-400 mt-1 max-w-xl">{knw.description}</p>
                        <span className="text-[10px] font-mono text-slate-500">{knw.id}</span>
                      </div>

                      <div>
                        <Button
                          size="sm"
                          variant={isAttached ? 'danger' : 'secondary'}
                          onClick={() => handleToggleKnowledge(knw.id)}
                        >
                          {isAttached ? 'Detach' : 'Attach to Agent'}
                        </Button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </Card>

          {/* EXTERNAL INTEGRATIONS */}
          <Card
            title={`External Integrations (${config.integrations.length} Attached)`}
            subtitle="Enterprise connections for calendars, CRM databases, webhooks, and telephony"
          >
            <div className="divide-y divide-[#1b1f2d]">
              {integrationsList.length === 0 ? (
                <div className="py-6 text-center text-xs text-slate-500">No integrations configured in catalog.</div>
              ) : (
                integrationsList.map((integ) => {
                  const isAttached = config.integrations.includes(integ.id);
                  return (
                    <div key={integ.id} className="py-3.5 flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-200">{integ.name}</span>
                          <span className="rounded bg-purple-950/60 border border-purple-900/40 px-1.5 py-0.5 text-[10px] font-mono text-purple-300">
                            {integ.category}
                          </span>
                          <span className="rounded bg-[#1b1f2d] px-1.5 py-0.5 text-[10px] font-mono text-slate-300">
                            {integ.provider}
                          </span>
                          <Badge variant="blue">{integ.connection_status}</Badge>
                        </div>
                        <p className="text-xs text-slate-400 mt-1 max-w-xl">{integ.description}</p>
                        <span className="text-[10px] font-mono text-slate-500">{integ.id}</span>
                      </div>

                      <div>
                        <Button
                          size="sm"
                          variant={isAttached ? 'danger' : 'secondary'}
                          onClick={() => handleToggleIntegration(integ.id)}
                        >
                          {isAttached ? 'Disconnect' : 'Connect to Agent'}
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
      {/* TAB 10: VOICE & PROVIDERS */}
      {/* ========================================================= */}
      {activeTab === 'settings' && (() => {
        const activeVoice =
          voicesList.find((v) => v.id === config.voice.voice_id) ||
          (config.voice.voice_id ? null : voicesList.find((v) => v.is_default)) ||
          voicesList.find((v) => (v.country || '').toUpperCase() === 'IN') ||
          voicesList[0];

        return (
          <div className="space-y-6">
            {/* CURRENT SELECTED VOICE SHOWCASE CARD */}
            <Card
              title="Acoustic Voice Synthesis"
              subtitle="Choose the Sarvam voice this AI Employee speaks with (made for Indian languages)"
            >
              <div className="space-y-5">
                {/* Active Voice Spotlight Banner */}
                <div className="rounded-xl border border-[#143c49] bg-gradient-to-r from-[#061820] to-[#0a232f] p-5">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div className="flex items-start gap-4">
                      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-purple-950/60 border border-purple-800/50 text-purple-400 shrink-0 shadow-inner">
                        <Volume2 className="h-6 w-6" />
                      </div>
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-lg font-bold text-slate-100">
                            {activeVoice ? activeVoice.name : 'Default Neural Voice (Siya)'}
                          </span>
                          {((activeVoice?.country || '').toUpperCase() === 'IN' || activeVoice?.language === 'hi') && (
                            <span className="text-[11px] font-semibold px-2 py-0.5 rounded bg-emerald-950/80 border border-emerald-800/50 text-emerald-400 flex items-center gap-1">
                              🇮🇳 India
                            </span>
                          )}
                          {activeVoice?.is_default && (
                            <Badge variant="purple">DEFAULT</Badge>
                          )}
                          {activeVoice?.gender && (
                            <span
                              className={`text-[10px] px-2 py-0.5 rounded uppercase font-medium ${
                                activeVoice.gender === 'feminine'
                                  ? 'bg-pink-950/50 text-pink-300 border border-pink-900/50'
                                  : 'bg-blue-950/50 text-blue-300 border border-blue-900/50'
                              }`}
                            >
                              {activeVoice.gender === 'feminine' ? 'Female' : 'Male'}
                            </span>
                          )}
                          {activeVoice?.country && activeVoice.country !== 'IN' && (
                            <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                              {activeVoice.country}
                            </span>
                          )}
                        </div>

                        {activeVoice?.tagline && (
                          <div className="text-xs font-medium text-purple-300 flex items-center gap-1.5">
                            <Sparkles className="h-3.5 w-3.5" />
                            <span>{activeVoice.tagline}</span>
                          </div>
                        )}

                        <p className="text-xs text-slate-300 max-w-2xl leading-relaxed">
                          {activeVoice?.description ||
                            'Sarvam Bulbul v3 voice, made for Indian languages.'}
                        </p>

                        <div className="pt-1 flex items-center gap-2 text-[11px] font-mono text-slate-400">
                          <span className="text-slate-500">VOICE ID:</span>
                          <span className="text-[#00df8f] bg-[#00df8f]/10 px-2 py-0.5 rounded border border-[#00df8f]/20">
                            {config.voice.voice_id || activeVoice?.id || 'shubh'}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Action Controls */}
                    <div className="flex flex-wrap md:flex-col lg:flex-row items-center gap-2.5 shrink-0">
                      <button
                        type="button"
                        onClick={() => handleTogglePreview(config.voice.voice_id || activeVoice?.id)}
                        className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all shadow-md ${
                          isPlayingPreview
                            ? 'bg-purple-900 text-purple-200 border border-purple-700 animate-pulse'
                            : 'bg-[#0f2d3a] hover:bg-[#153f52] text-slate-100 border border-[#1b4e5f]'
                        }`}
                      >
                        {isPreviewLoading ? (
                          <>
                            <RefreshCw className="h-3.5 w-3.5 animate-spin text-purple-300" />
                            <span>Loading Audio...</span>
                          </>
                        ) : isPlayingPreview ? (
                          <>
                            <Square className="h-3.5 w-3.5 fill-current text-purple-300" />
                            <span>Stop Audio Sample</span>
                          </>
                        ) : (
                          <>
                            <Play className="h-3.5 w-3.5 fill-current text-[#00df8f]" />
                            <span>Preview Voice Sample</span>
                          </>
                        )}
                      </button>

                      <Button
                        variant="primary"
                        size="md"
                        onClick={() => setIsVoicePickerOpen(true)}
                        className="font-semibold shadow-md shadow-emerald-950/40"
                      >
                        <Radio className="h-3.5 w-3.5 mr-1.5" />
                        Browse Sarvam Voices ({voicesList.length || 37})
                      </Button>
                    </div>
                  </div>
                </div>

                {/* Acoustic Fine-Tuning Settings */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-5 pt-3 border-t border-[#102d38] text-xs">
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Speaking Speed Rate:{' '}
                      <span className="text-[#00df8f] font-mono font-bold">
                        {config.voice.speed.toFixed(2)}x
                      </span>
                    </label>
                    <div className="space-y-2">
                      <input
                        type="range"
                        min="0.5"
                        max="2.0"
                        step="0.05"
                        value={config.voice.speed}
                        onChange={(e) =>
                          updateDraft((prev) => ({
                            ...prev,
                            voice: { ...prev.voice, speed: parseFloat(e.target.value) || 1.0 },
                          }))
                        }
                        className="w-full accent-[#00df8f] cursor-pointer"
                      />
                      <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                        <span>0.50x (Slow)</span>
                        <span>1.00x (Natural)</span>
                        <span>2.00x (Fast)</span>
                      </div>
                    </div>
                  </div>

                  <Select
                    label="Speaking Language"
                    options={getLanguageOptions(config.voice.language)}
                    value={config.voice.language}
                    onChange={(e) =>
                      updateDraft((prev) => ({
                        ...prev,
                        voice: { ...prev.voice, language: e.target.value },
                      }))
                    }
                    helperText="Language code sent to Sarvam voice synthesis."
                  />

                  <Select
                    label="TTS Synthesis Provider"
                    options={getProviderOptions(TTS_PROVIDER_OPTIONS, config.voice.provider)}
                    value={config.voice.provider}
                    onChange={(e) => {
                      const val = e.target.value;
                      updateDraft((prev) => ({
                        ...prev,
                        voice: { ...prev.voice, provider: val },
                        providers: { ...prev.providers, tts: val },
                      }));
                    }}
                    helperText="Voice engine used for speech synthesis."
                  />
                </div>
              </div>
            </Card>

          <Card
            title="Provider Configuration Stack"
            subtitle="Underlying infrastructure providers plugged into the voice runtime engine"
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
              <div className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-4 space-y-2">
                <span className="text-slate-500 font-mono text-[10px] block">SPEECH-TO-TEXT (STT)</span>
                <Select
                  label="STT Provider"
                  options={getProviderOptions(STT_PROVIDER_OPTIONS, config.providers.stt)}
                  value={config.providers.stt}
                  onChange={(e) =>
                    updateDraft((prev) => ({
                      ...prev,
                      providers: {
                        ...prev.providers,
                        stt: e.target.value,
                      },
                    }))
                  }
                  helperText="Speech-to-text recognition provider."
                />
              </div>

              <div className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-4 space-y-2">
                <span className="text-slate-500 font-mono text-[10px] block">LARGE LANGUAGE MODEL (LLM)</span>
                <Select
                  label="LLM Provider"
                  options={getProviderOptions(LLM_PROVIDER_OPTIONS, config.providers.llm)}
                  value={config.providers.llm}
                  onChange={(e) =>
                    updateDraft((prev) => ({
                      ...prev,
                      providers: {
                        ...prev.providers,
                        llm: e.target.value,
                      },
                    }))
                  }
                  helperText="Foundation model powering conversational intelligence."
                />
              </div>

              <div className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-4 space-y-2">
                <span className="text-slate-500 font-mono text-[10px] block">TEXT-TO-SPEECH (TTS)</span>
                <Select
                  label="TTS Provider"
                  options={getProviderOptions(TTS_PROVIDER_OPTIONS, config.providers.tts)}
                  value={config.providers.tts}
                  onChange={(e) => {
                    const val = e.target.value;
                    updateDraft((prev) => ({
                      ...prev,
                      providers: {
                        ...prev.providers,
                        tts: val,
                      },
                      voice: {
                        ...prev.voice,
                        provider: val,
                      },
                    }));
                  }}
                  helperText="Speech synthesis provider for generated audio."
                />
              </div>

              <div className="rounded-lg border border-[#1b1f2d] bg-[#0c0e14] p-4 space-y-2">
                <span className="text-slate-500 font-mono text-[10px] block">TELEPHONY / TRUNKING CARRIER</span>
                <Select
                  label="Telephony Provider (optional)"
                  options={getProviderOptions(TELEPHONY_PROVIDER_OPTIONS, config.providers.telephony || '')}
                  value={config.providers.telephony || ''}
                  onChange={(e) => {
                    const val = e.target.value;
                    updateDraft((prev) => ({
                      ...prev,
                      providers: {
                        ...prev.providers,
                        telephony: val ? val : null,
                      },
                    }));
                  }}
                  helperText="Select Exotel for PSTN phone numbers, or None for browser-only voice."
                />
              </div>
            </div>
          </Card>
        </div>
      );
    })()}

      {/* ========================================================= */}
      {/* TAB 11: VERSIONS & HISTORY */}
      {/* ========================================================= */}
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
                  description="Click 'Publish Version' in the top action bar to create Version 1 from current draft."
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
        onClose={() => setIsVoicePickerOpen(false)}
        selectedVoiceId={config.voice.voice_id}
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
        }}
      />
    </div>
  );
};
