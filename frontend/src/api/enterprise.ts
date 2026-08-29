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

async function getJson<T>(path: string): Promise<T> {
  const response = await authFetch(path);
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export const fetchEnterpriseOverview = () => getJson<EnterpriseOverview>('/api/enterprise/overview');
export const fetchRuntimeSummary = () => getJson<RuntimeSummary>('/api/enterprise/runtime');
export const fetchEvaluationSummary = async () => (await getJson<{ metrics: EvaluationMetric[] }>('/api/enterprise/evaluation')).metrics;
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
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json() as { checks: Record<string, boolean> };
  return data.checks;
}
