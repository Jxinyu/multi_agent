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

async function getJson<T>(path: string): Promise<T> {
  const response = await authFetch(path);
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export const fetchEnterpriseOverview = () => getJson<EnterpriseOverview>('/api/enterprise/overview');
export const fetchRuntimeSummary = () => getJson<RuntimeSummary>('/api/enterprise/runtime');
export const fetchRuntimeAgentDetail = (agentId: string) => getJson<RuntimeAgentDetail>(`/api/enterprise/runtime/agents/${encodeURIComponent(agentId)}`);
export const fetchEvaluationSummary = async () => (await getJson<{ metrics: EvaluationMetric[] }>('/api/enterprise/evaluation')).metrics;
export const fetchEvaluationRunDetail = (runId: string) => getJson<EvaluationRunDetail>(`/api/enterprise/evaluation/runs/${encodeURIComponent(runId)}`);
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
