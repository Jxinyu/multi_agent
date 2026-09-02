import type { CurrentUser, KnowledgeBaseItem } from '../types';
import { authFetch } from './auth';

export interface EnterpriseEvent {
  id: string;
  actor_id: string;
  action: string;
  outcome: string;
  resource_type: string;
  resource_id?: string | null;
  occurred_at: string;
  metadata: Record<string, unknown>;
}

export interface EnterpriseOverview {
  observed_actors: string[];
  conversation_count: number;
  completed_count: number;
  failed_count: number;
  waiting_count: number;
  running_count: number;
  document_count: number;
  healthy_document_count: number;
  search_count: number;
  average_search_ms: number | null;
  recent_events: EnterpriseEvent[];
  data_window: string;
}

export interface ObservedMemberDetail {
  actor_id: string;
  actor_type: string;
  identity_source: string;
  is_current_user: boolean;
  role: string | null;
  permissions: string[];
  groups: string[];
  event_count: number;
  window_complete: boolean;
  first_seen_at: string | null;
  last_seen_at: string | null;
  outcomes: { id: string; count: number }[];
  actions: { id: string; count: number }[];
  resource_types: { id: string; count: number }[];
  recent_events: EnterpriseEvent[];
  directory_managed: boolean;
}

export interface RuntimeSummary {
  agents: { id: string; description: string }[];
  connections: { id: string; label: string; configured: boolean }[];
  pipeline: string[];
}

export interface RuntimeAgentDetail {
  id: string;
  label: string;
  description: string;
  source_module: string;
  model_provider: string;
  model_name: string;
  output_schema: string;
  tool_call_limit: number;
  summarization_trigger_messages: number;
  summarization_keep_messages: number;
  capabilities: string[];
  guardrails: string[];
  connections: { id: string; label: string; configured: boolean }[];
  editable: boolean;
}

export interface RuntimeConnectionDetail {
  id: string;
  label: string;
  configured: boolean;
  transport: string;
  endpoint_hint: string;
  health: 'healthy' | 'unhealthy' | 'unconfigured';
  checked_at: string;
  http_status: number | null;
  latency_ms: number | null;
  probe_method: string;
  success_condition: string;
  probe_message: string;
  credential_policy: string;
  configuration_source: string;
  capabilities: string[];
  affected_agents: { id: string; label: string }[];
  history_available: boolean;
  mutable: boolean;
}

export interface KnowledgeIndexRuntime {
  checked_at: string;
  tenant_id: string;
  document_count: number;
  ready_document_count: number;
  expected_vector_chunks: number;
  expected_graph_chunks: number;
  orphan_document_count: number;
  milvus: {
    available: boolean;
    collection_name: string;
    collection_exists: boolean;
    indexed_chunks: number | null;
    indexed_documents: number | null;
    embedding_dimensions: number | null;
    sparse_search_enabled: boolean | null;
    scan_complete: boolean;
    error: string | null;
  };
  neo4j: {
    available: boolean;
    indexed_chunks: number | null;
    indexed_documents: number | null;
    entity_count: number | null;
    relationship_count: number | null;
    scan_complete: boolean;
    error: string | null;
  };
  state_counts: Record<string, number>;
  document_checks: {
    document_id: string;
    file_name: string;
    status: string;
    mode: string;
    expected_chunks: number;
    vector_chunks: number | null;
    graph_chunks: number | null;
    vector_expected: boolean;
    graph_expected: boolean;
    state: 'consistent' | 'mismatch' | 'pending' | 'unknown';
    issue: string | null;
  }[];
  document_checks_complete: boolean;
  observation_note: string;
}

export interface EvaluationMetric {
  id: string;
  label: string;
  baseline: number;
  current: number;
  unit: 'ratio' | 'count';
  sample_count: number;
  source: string;
  run_id: string;
}

export interface EvaluationRunValue {
  id: string;
  label: string;
  value: number;
  unit: 'ratio' | 'count' | 'seconds';
}

export interface EvaluationRunVariant {
  id: string;
  label: string;
  role: string;
  values: EvaluationRunValue[];
}

export interface EvaluationRunDetail {
  run_id: string;
  title: string;
  category: string;
  dataset: string;
  split: string;
  sample_count: number;
  source: string;
  variants: EvaluationRunVariant[];
  notes: string[];
}

export interface EvaluationDatasetDetail {
  registry_version: number;
  checked_at: string;
  run_id: string;
  name: string;
  benchmark_type: string;
  sample_count: number;
  split: string;
  seed: number | null;
  selection_rule: string;
  source_urls: { label: string; url: string }[];
  distributions: { label: string; count: number }[];
  artifacts: {
    path: string;
    role: string;
    distribution: 'repository' | 'local_cache';
    expected_size_bytes: number;
    actual_size_bytes: number | null;
    expected_sha256: string;
    actual_sha256: string | null;
    record_count: number | null;
    available: boolean;
    integrity: 'verified' | 'mismatch' | 'not_distributed' | 'missing';
  }[];
  leakage_controls: string[];
  limitations: string[];
  raw_samples_exposed: boolean;
  registry_note: string;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await authFetch(path);
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export const fetchEnterpriseOverview = () => getJson<EnterpriseOverview>('/api/enterprise/overview');
export const fetchObservedMemberDetail = (actorId: string) => getJson<ObservedMemberDetail>(`/api/enterprise/members/${encodeURIComponent(actorId)}`);
export const fetchRuntimeSummary = () => getJson<RuntimeSummary>('/api/enterprise/runtime');
export const fetchRuntimeAgentDetail = (agentId: string) => getJson<RuntimeAgentDetail>(`/api/enterprise/runtime/agents/${encodeURIComponent(agentId)}`);
export const fetchRuntimeConnectionDetail = (connectionId: string) => getJson<RuntimeConnectionDetail>(`/api/enterprise/runtime/connections/${encodeURIComponent(connectionId)}`);
export const fetchKnowledgeIndexRuntime = () => getJson<KnowledgeIndexRuntime>('/api/enterprise/knowledge/runtime');
export const fetchEvaluationSummary = async () => (await getJson<{ metrics: EvaluationMetric[] }>('/api/enterprise/evaluation')).metrics;
export const fetchEvaluationRunDetail = (runId: string) => getJson<EvaluationRunDetail>(`/api/enterprise/evaluation/runs/${encodeURIComponent(runId)}`);
export const fetchEvaluationDatasetDetail = (runId: string) => getJson<EvaluationDatasetDetail>(`/api/enterprise/evaluation/runs/${encodeURIComponent(runId)}/dataset`);
export const fetchEnterpriseDocuments = async () => (await getJson<{ items: KnowledgeBaseItem[] }>('/api/admin/documents')).items;
export const fetchEnterpriseCurrentUser = async () => (await getJson<{ user: CurrentUser }>('/api/auth/me')).user;

export async function downloadEvaluationReport(): Promise<void> {
  const response = await authFetch('/api/enterprise/evaluation/report');
  if (!response.ok) throw new Error(await response.text());
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = '企业多智能体量化实验汇总.md';
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function fetchDependencyHealth(): Promise<Record<string, boolean>> {
  const response = await fetch('/api/health/ready');
  const data = await response.json() as { checks: Record<string, boolean> };
  if (!data.checks || typeof data.checks !== 'object') throw new Error(`健康检查响应无效（HTTP ${response.status}）`);
  return data.checks;
}
