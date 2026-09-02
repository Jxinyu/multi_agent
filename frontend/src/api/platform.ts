import { authFetch } from './auth';

export interface TenantUsage {
  tenant_id: string;
  status: string;
  auth_mode: string;
  observed_users: number;
  document_count: number;
  healthy_document_count: number;
  audit_event_count: number;
  request_limit_per_minute: number;
  max_file_size_bytes: number;
  vector_storage_quota_bytes: number | null;
  graph_entity_quota: number | null;
  monthly_token_quota: number | null;
}

export interface TenantDirectory {
  items: TenantUsage[];
  registry_available: boolean;
  enforcement_note: string;
}

export interface DistributionItem {
  id: string;
  count: number;
}

export interface TenantDetail {
  usage: TenantUsage;
  registry_available: boolean;
  audit_window_complete: boolean;
  audit_window_size: number;
  observed_actor_ids: string[];
  document_statuses: DistributionItem[];
  parsing_modes: DistributionItem[];
  audit_outcomes: DistributionItem[];
  frequent_actions: DistributionItem[];
  recent_documents: {
    id: string;
    file_name: string;
    owner_id: string;
    status: string;
    mode: string;
    upload_time: string;
  }[];
  recent_events: AuditEvent[];
  enforcement_note: string;
}

export interface RuntimeStatus {
  environment: string;
  service_name: string;
  services: { name: string; ok: boolean; detail: string }[];
  worker_max_attempts: number;
  worker_block_ms: number;
  maintenance_operations_enabled: boolean;
}

export interface WorkerRuntimeSnapshot {
  checked_at: string;
  stream_name: string;
  dead_letter_stream_name: string;
  group_name: string;
  queue: {
    available: boolean;
    group_initialized: boolean;
    stream_length: number;
    dead_letter_length: number;
    pending: number;
    lag: number | null;
    consumers: { name: string; pending: number; idle_ms: number; inactive_ms: number | null }[];
    error: string | null;
  };
  status_counts: { status: string; count: number }[];
  active_jobs: {
    id: string;
    document_id: string;
    file_name: string | null;
    operation: string;
    mode: string;
    status: string;
    attempts: number;
    updated_at: string;
  }[];
  worker_max_attempts: number;
  worker_block_ms: number;
  heartbeat_available: boolean;
  observation_note: string;
}

export interface ServiceProbeDetail {
  service: { name: string; ok: boolean; detail: string };
  checked_at: string;
  method: string;
  success_condition: string;
  operational_role: string;
  timeout_seconds: number;
  history_available: boolean;
  configuration_source: string;
}

export interface ModelInventory {
  connected: boolean;
  endpoint: string;
  models: { name: string; size_bytes: number | null; modified_at: string | null; roles: string[] }[];
  error: string | null;
}

export interface PlatformSettings {
  groups: { id: string; label: string; items: { key: string; label: string; value: string }[] }[];
  mutable: boolean;
  source: string;
}

export interface AuditEvent {
  id: string;
  tenant_id: string;
  actor_id: string;
  actor_type: string;
  source: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  outcome: 'success' | 'failure' | 'denied';
  request_id: string | null;
  metadata: Record<string, unknown>;
  occurred_at: string;
}

export interface AuditEventDetail {
  item: AuditEvent;
  related_events: AuditEvent[];
  trace_complete: boolean;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await authFetch(path);
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export const fetchTenantDirectory = () => getJson<TenantDirectory>('/api/platform/tenants');
export const fetchTenantDetail = (tenantId: string) => getJson<TenantDetail>(`/api/platform/tenants/${encodeURIComponent(tenantId)}`);
export const fetchRuntimeStatus = () => getJson<RuntimeStatus>('/api/platform/runtime');
export const fetchWorkerRuntime = () => getJson<WorkerRuntimeSnapshot>('/api/platform/runtime/worker');
export const fetchServiceProbeDetail = (serviceName: string) => getJson<ServiceProbeDetail>(`/api/platform/runtime/services/${encodeURIComponent(serviceName)}`);
export const fetchModelInventory = () => getJson<ModelInventory>('/api/platform/models');
export const fetchPlatformSettings = () => getJson<PlatformSettings>('/api/platform/settings');

export function fetchAuditEvents(options: { outcome?: string; actor?: string; action?: string; cursor?: string } = {}) {
  const params = new URLSearchParams({ limit: '30' });
  if (options.outcome) params.set('outcome', options.outcome);
  if (options.actor) params.set('actor_id', options.actor);
  if (options.action) params.set('action', options.action);
  if (options.cursor) params.set('cursor', options.cursor);
  return getJson<{ items: AuditEvent[]; next_cursor: string | null }>(`/api/admin/audit-events?${params}`);
}

export const fetchAuditEventDetail = (eventId: string) => getJson<AuditEventDetail>(`/api/admin/audit-events/${encodeURIComponent(eventId)}`);
