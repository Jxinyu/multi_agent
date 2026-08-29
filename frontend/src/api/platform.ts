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

export interface RuntimeStatus {
  environment: string;
  service_name: string;
  services: { name: string; ok: boolean; detail: string }[];
  worker_max_attempts: number;
  worker_block_ms: number;
  maintenance_operations_enabled: boolean;
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

async function getJson<T>(path: string): Promise<T> {
  const response = await authFetch(path);
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export const fetchTenantDirectory = () => getJson<TenantDirectory>('/api/platform/tenants');
export const fetchRuntimeStatus = () => getJson<RuntimeStatus>('/api/platform/runtime');
export const fetchModelInventory = () => getJson<ModelInventory>('/api/platform/models');
export const fetchPlatformSettings = () => getJson<PlatformSettings>('/api/platform/settings');

export function fetchAuditEvents(options: { outcome?: string; actor?: string; cursor?: string } = {}) {
  const params = new URLSearchParams({ limit: '30' });
  if (options.outcome) params.set('outcome', options.outcome);
  if (options.actor) params.set('actor_id', options.actor);
  if (options.cursor) params.set('cursor', options.cursor);
  return getJson<{ items: AuditEvent[]; next_cursor: string | null }>(`/api/admin/audit-events?${params}`);
}
