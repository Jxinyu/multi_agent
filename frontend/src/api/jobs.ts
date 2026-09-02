import { authFetch } from './auth';

export interface DocumentJob {
  id: string;
  document_id: string;
  file_name: string | null;
  operation: string;
  mode: string;
  status: 'queued' | 'processing' | 'succeeded' | 'failed';
  attempts: number;
  error: string | null;
  requested_by: string | null;
  request_id: string | null;
  created_at: string;
  updated_at: string;
}

interface JobQuery {
  mode: 'user' | 'enterprise';
  documentId?: string;
  status?: string;
  operation?: string;
  limit?: number;
  offset?: number;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await authFetch(path);
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export function fetchDocumentJobs(options: JobQuery) {
  const prefix = options.mode === 'enterprise' ? '/api/admin/jobs' : '/api/jobs';
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0)
  });
  if (options.documentId) params.set('document_id', options.documentId);
  if (options.status) params.set('status', options.status);
  if (options.operation) params.set('operation', options.operation);
  return getJson<{ items: DocumentJob[]; total: number }>(`${prefix}?${params}`);
}

export const fetchDocumentJob = (jobId: string, mode: 'user' | 'enterprise') => (
  getJson<DocumentJob>(`${mode === 'enterprise' ? '/api/admin/jobs' : '/api/jobs'}/${encodeURIComponent(jobId)}`)
);
