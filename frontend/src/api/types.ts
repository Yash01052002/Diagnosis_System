// TypeScript mirrors of the backend Pydantic schemas. Kept deliberately close
// to app/schemas so a change on the server surfaces here as a type error.

// ---------------------------------------------------------------------------
// Enums (string unions match the StrEnum values on the server)
// ---------------------------------------------------------------------------
export type RoleName = "admin" | "engineer" | "viewer";

export type DeviceStatus =
  | "active"
  | "inactive"
  | "maintenance"
  | "decommissioned";

export type CrashSeverity = "low" | "medium" | "high" | "critical";

export type CrashStatus =
  | "new"
  | "triaged"
  | "investigating"
  | "resolved"
  | "ignored"
  | "duplicate";

export type FaultType =
  | "hard_fault"
  | "bus_fault"
  | "mem_manage_fault"
  | "usage_fault"
  | "stack_overflow"
  | "watchdog_reset"
  | "assertion_failed"
  | "malloc_failed"
  | "panic"
  | "unknown";

export type CrashGroupStatus =
  | "open"
  | "investigating"
  | "resolved"
  | "ignored"
  | "regressed";

export type DocumentSourceType =
  | "stm32_reference"
  | "freertos_doc"
  | "arm_cortex_m"
  | "engineering_note"
  | "troubleshooting"
  | "application_note"
  | "previous_crash"
  | "other";

export type DocumentStatus = "pending" | "processing" | "indexed" | "failed";

export type ConfidenceLabel = "certain" | "likely" | "uncertain";

// ---------------------------------------------------------------------------
// Common
// ---------------------------------------------------------------------------
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Auth & users
// ---------------------------------------------------------------------------
export interface Role {
  id: string;
  name: RoleName;
  description?: string | null;
}

export interface User {
  id: string;
  email: string;
  full_name?: string | null;
  is_active: boolean;
  is_verified: boolean;
  last_login_at?: string | null;
  created_at: string;
  updated_at: string;
  roles: Role[];
}

export interface UserSummary {
  id: string;
  email: string;
  full_name?: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface LoginResponse extends TokenPair {
  user: User;
}

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------
export interface Device {
  id: string;
  device_id: string;
  serial_number: string;
  firmware_version: string;
  hardware_model: string;
  location?: string | null;
  description?: string | null;
  status: DeviceStatus;
  last_online_at?: string | null;
  created_at: string;
  updated_at: string;
  owner?: UserSummary | null;
  tags: string[];
}

export interface DeviceSummary {
  id: string;
  device_id: string;
  serial_number: string;
  hardware_model: string;
  status: DeviceStatus;
}

export interface DeviceStats {
  device_id: string;
  total_crashes: number;
  open_crashes: number;
  crashes_last_24h: number;
  last_crash_at?: string | null;
}

export interface DeviceApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at?: string | null;
  expires_at?: string | null;
  revoked_at?: string | null;
}

export interface DeviceApiKeyCreated extends DeviceApiKey {
  api_key: string;
}

// ---------------------------------------------------------------------------
// Crashes
// ---------------------------------------------------------------------------
export interface Frame {
  address: number;
  address_hex: string;
  origin: string;
  function?: string | null;
  offset?: number | null;
  source_file?: string | null;
  line?: number | null;
  resolved: boolean;
  thumb: boolean;
  inlined: boolean;
  display: string;
}

export interface Symbolication {
  symbolized: boolean;
  build_version?: string | null;
  pc?: Frame | null;
  lr?: Frame | null;
  frames: Frame[];
  resolved_count: number;
  frame_count: number;
  warnings: string[];
}

export interface CrashGroupSummary {
  id: string;
  signature: string;
  title: string;
  status: CrashGroupStatus;
  occurrence_count: number;
}

export interface CrashListItem {
  id: string;
  device: DeviceSummary;
  firmware_version: string;
  occurred_at: string;
  fault_type: FaultType;
  task_name?: string | null;
  program_counter?: number | null;
  severity: CrashSeverity;
  status: CrashStatus;
  top_function?: string | null;
  crash_signature?: string | null;
  group_id?: string | null;
  confidence_score?: number | null;
}

export interface Crash {
  id: string;
  device: DeviceSummary;
  firmware_version: string;
  build_version?: string | null;
  occurred_at: string;
  received_at: string;
  fault_type: FaultType;
  exception_type?: string | null;
  task_name?: string | null;
  program_counter?: number | null;
  link_register?: number | null;
  stack_pointer?: number | null;
  register_dump?: Record<string, unknown> | null;
  stack_dump?: Record<string, unknown> | null;
  severity: CrashSeverity;
  status: CrashStatus;
  notes?: string | null;
  symbolication?: Symbolication | null;
  symbolicated_at?: string | null;
  top_function?: string | null;
  crash_signature?: string | null;
  group?: CrashGroupSummary | null;
  ai_diagnosis?: string | null;
  suggested_fix?: string | null;
  confidence_score?: number | null;
  diagnosed_at?: string | null;
  parse_warnings?: Record<string, unknown> | null;
  parser_version?: string | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Crash groups
// ---------------------------------------------------------------------------
export interface CrashGroup {
  id: string;
  signature: string;
  title: string;
  fault_type: FaultType;
  task_name?: string | null;
  top_function?: string | null;
  status: CrashGroupStatus;
  severity: CrashSeverity;
  occurrence_count: number;
  device_count: number;
  first_seen_at: string;
  last_seen_at: string;
  affected_firmware_versions: string[];
  notes?: string | null;
  regressed_at?: string | null;
  signature_components?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Knowledge base & diagnoses (Phase 3)
// ---------------------------------------------------------------------------
export interface KnowledgeDocument {
  id: string;
  title: string;
  source_type: DocumentSourceType;
  original_filename?: string | null;
  content_type: string;
  status: DocumentStatus;
  chunk_count: number;
  embedding_model?: string | null;
  error_message?: string | null;
  doc_metadata?: Record<string, unknown> | null;
  indexed_at?: string | null;
  created_at: string;
  uploaded_by?: UserSummary | null;
}

export interface KnowledgeBaseStats {
  documents: number;
  chunks: number;
  embedding_provider: string;
  vector_store: string;
}

export interface RetrievedChunk {
  document_id: string;
  document_title?: string | null;
  source_type?: string | null;
  chunk_index: number;
  score: number;
  content: string;
}

export interface SearchResponse {
  query: string;
  results: RetrievedChunk[];
  empty: boolean;
}

export interface DiagnosisSource {
  document_id?: string | null;
  document_title?: string | null;
  source_type?: string | null;
  chunk_index?: number | null;
  score?: number | null;
  excerpt?: string | null;
}

export interface Diagnosis {
  id: string;
  crash_id?: string | null;
  group_id?: string | null;
  root_cause: string;
  recommended_fix?: string | null;
  summary?: string | null;
  confidence_score: number;
  confidence_label: ConfidenceLabel;
  is_uncertain: boolean;
  top_relevance?: number | null;
  sources: DiagnosisSource[];
  provider: string;
  model: string;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  latency_ms?: number | null;
  warnings: string[];
  created_at: string;
  requested_by?: UserSummary | null;
}
