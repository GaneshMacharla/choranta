export type UserRole = 'ADMIN' | 'OPERATOR' | 'CLIENT';
export type UserStatus = 'ACTIVE' | 'INACTIVE';

export interface User {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  status: UserStatus;
  created_at: string;
}

export type BusinessType = 
  | 'CLINIC' 
  | 'HOSPITAL' 
  | 'SALON' 
  | 'REAL_ESTATE' 
  | 'HOTEL' 
  | 'RESTAURANT' 
  | 'CORPORATE' 
  | 'COACHING'
  | 'OTHER';

export type ClientStatus = 'ACTIVE' | 'INACTIVE';

export interface Client {
  id: string;
  /** Short unique id shown to admins and the client, e.g. CL-10001 */
  client_code?: string | null;
  name: string;
  business_type: BusinessType;
  description?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  timezone: string;
  status: ClientStatus;
  /** Admin override of simultaneous calls; null = the platform default */
  max_concurrent_calls?: number | null;
  agent_count: number;
  created_at: string;
  updated_at: string;
}

export interface ClientCreateInput {
  name: string;
  business_type: BusinessType;
  description?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  timezone?: string;
}

export interface ClientUpdateInput {
  name?: string;
  business_type?: BusinessType;
  description?: string;
  contact_name?: string;
  contact_email?: string;
  contact_phone?: string;
  timezone?: string;
  status?: ClientStatus;
  /** 0 clears the override */
  max_concurrent_calls?: number;
}

export type AgentStatus = 'DRAFT' | 'TESTING' | 'READY' | 'DEPLOYED' | 'PAUSED' | 'ARCHIVED';

export interface Agent {
  id: string;
  client_id: string;
  client_name?: string | null;
  name: string;
  role: string;
  description?: string | null;
  status: AgentStatus;
  created_at: string;
  updated_at: string;
}

export interface AgentCreateInput {
  client_id: string;
  name: string;
  role: string;
  description?: string;
  template_id?: string;
}

export interface AgentUpdateInput {
  name?: string;
  role?: string;
  description?: string;
  status?: AgentStatus;
}

export interface AgentVersion {
  id: string;
  agent_id: string;
  version_number: number;
  configuration_json: Record<string, any>;
  status: string;
  created_at: string;
  created_by?: string | null;
}

export interface RecentClientItem {
  id: string;
  name: string;
  business_type: BusinessType;
  status: ClientStatus;
  agent_count: number;
  created_at: string;
}

export interface RecentAgentItem {
  id: string;
  client_id: string;
  client_name?: string | null;
  name: string;
  role: string;
  status: AgentStatus;
  created_at: string;
}

export interface DashboardSummary {
  total_clients: number;
  active_clients: number;
  total_agents: number;
  active_agents: number;
  recent_clients: RecentClientItem[];
  recent_agents: RecentAgentItem[];
}

// ==========================================
// PHASE 2: AGENT SPEC & CONFIGURATION TYPES
// ==========================================

export interface AgentIdentity {
  name: string;
  organization: string;
  persona: string;
}

export interface BusinessHours {
  timezone?: string;
  monday_friday?: string;
  [key: string]: any;
}

export interface ContactInformation {
  name?: string | null;
  email?: string | null;
  phone?: string | null;
  [key: string]: any;
}

export interface AgentBusinessContext {
  business_name: string;
  business_type: string;
  business_hours: BusinessHours;
  location: string;
  contact_information: ContactInformation;
  call_direction?: CallDirection;
}

export type CallDirection = 'inbound' | 'outbound' | 'both';

export interface AgentInstructions {
  primary_goal: string;
  responsibilities: string[];
  rules: string[];
  restrictions: string[];
  escalation_rules: string[];
  /** Call script: questions to ask in order, points to mention, the next step to agree */
  discovery_questions?: string[];
  offer_points?: string[];
  next_step?: string;
  /** Key of the standard call script this employee uses (taken on publish); '' = its own script above */
  script_source?: string;
}

export interface AgentConversationStyle {
  tone: string;
  verbosity: string;
  greeting: string;
  farewell: string;
  interruption_behavior: string;
  limits: AgentCallLimits;
}

/** Per-agent call limits; null = platform default. */
export interface AgentCallLimits {
  max_call_duration_s: number | null;
  silence_reprompt_s: number | null;
  silence_hangup_s: number | null;
  max_reply_chars: number | null;
  max_tool_rounds: number | null;
  end_call_phrases: string[];
}

export const EMPTY_CALL_LIMITS: AgentCallLimits = {
  max_call_duration_s: null,
  silence_reprompt_s: null,
  silence_hangup_s: null,
  max_reply_chars: null,
  max_tool_rounds: null,
  end_call_phrases: [],
};

export interface AgentLanguageConfig {
  primary: string;
  supported: string[];
}

export interface AgentVoiceConfig {
  provider: string;
  voice_id?: string | null;
  language: string;
  speed: number;
}

export interface AgentProviderConfig {
  stt: string;
  llm: string;
  tts: string;
  telephony?: string | null;
}

export interface AgentVariable {
  name: string;
  description: string;
  data_type: string;
  default_value?: any;
  required: boolean;
  source?: string;
  extraction_instructions: string;
}

export interface AgentVariablesConfig {
  inputs: AgentVariable[];
  outputs: AgentVariable[];
}

export interface AgentTemplatePreview {
  role?: string;
  persona?: string;
  sample_greeting?: string;
  key_capabilities?: string[];
  input_variables?: string[];
  output_variables?: string[];
  enabled_tools?: string[];
}

export interface AgentTemplate {
  id: string;
  name: string;
  role?: string;
  description: string;
  category: string;
  capabilities?: string[];
  supported_capabilities?: string[];
  is_featured?: boolean;
  recommended_role?: string;
  preview?: AgentTemplatePreview;
  /** Client business types this template suits (e.g. CLINIC), used to recommend it */
  business_types?: string[];
  call_direction?: CallDirection;
  default_config?: Record<string, any>;
  default_configuration?: Record<string, any>;
}

export interface AgentConfigurationData {
  identity: AgentIdentity;
  business_context: AgentBusinessContext;
  instructions: AgentInstructions;
  conversation: AgentConversationStyle;
  languages: AgentLanguageConfig;
  knowledge_sources: string[];
  tools: string[];
  integrations: string[];
  variables: AgentVariablesConfig;
  voice: AgentVoiceConfig;
  providers: AgentProviderConfig;
}

export interface ValidationIssue {
  field: string;
  message: string;
  severity: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

export interface FieldDiff {
  field: string;
  old_value: any;
  new_value: any;
}

export interface VersionComparison {
  base_version_number: number;
  compare_version_number: number;
  changes: FieldDiff[];
  summary: string;
}

export interface KnowledgeSource {
  id: string;
  name: string;
  type: string;
  status: string;
  description?: string | null;
  /** What the AI employee reads on calls (notes, or FAQ as Q:/A: pairs) */
  content?: string | null;
  /** Set when written inside one AI employee's Knowledge tab; null = shared library */
  owner_agent_id?: string | null;
  /** The client whose knowledge base this belongs to */
  client_id?: string | null;
  metadata?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  input_schema: Record<string, any>;
  output_schema: Record<string, any>;
  executor_type: string;
  timeout: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface Integration {
  id: string;
  name: string;
  description?: string | null;
  category: string;
  provider: string;
  connection_status: string;
  metadata?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface CartesiaVoice {
  id: string;
  name: string;
  gender?: string | null;
  language?: string | null;
  description?: string | null;
  tagline?: string | null;
  country?: string | null;
  preview_url?: string | null;
  is_default: boolean;
  provider: string;
  /** 1 = one of Choranta's top picks for business calls */
  tier?: number | null;
}

// ==========================================
// PHASE 3A: VOICE RUNTIME FOUNDATION TYPES
// ==========================================

export interface ReadinessCheckResult {
  ready: boolean;
  errors: string[];
  warnings: string[];
  agent_id: string;
  version_id: string;
  version_number?: number | null;
}

export interface RuntimeSession {
  id: string;
  client_id: string;
  agent_id: string;
  agent_version_id: string;
  status: string;
  started_at?: string | null;
  ended_at?: string | null;
  metadata: Record<string, any>;
  usage: Record<string, any>;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface RuntimeEvent {
  id: string;
  session_id: string;
  client_id: string;
  agent_id: string;
  agent_version_id: string;
  event_type: string;
  payload: Record<string, any>;
  timestamp: string;
  created_at: string;
}

export interface SimulateTurnResult {
  session_id: string;
  transcript: string;
  assistant_response: string;
  audio_duration_seconds: number;
  tool_calls_executed: number;
  usage: Record<string, any>;
  events?: RuntimeEvent[];
}

export type StreamTurnEvent =
  | { type: 'delta'; text: string }
  | { type: 'tool'; status: 'started' | 'completed'; tool_name: string; success?: boolean }
  | {
      type: 'done';
      transcript: string;
      assistant_response: string;
      display_text: string;
      tool_calls_executed: number;
      /** The AI employee hung up (finished, or the caller went off-topic); the session is over */
      call_ended?: boolean;
      usage: Record<string, any>;
      events: RuntimeEvent[];
    }
  | { type: 'error'; message: string };



export interface AgentDraftRequest {
  client_id: string;
  name: string;
  role: string;
  call_direction: CallDirection;
  primary_language: string;
  supported_languages: string[];
  description: string;
  business_notes: string;
}

export interface AgentDraftResponse {
  configuration: AgentConfigurationData;
  draft_source: 'ai' | 'fallback';
  message?: string | null;
}
