import type { KnowledgeBaseItem, SearchEvidence, SearchMode, UserTask } from '../types';
import { authFetch } from './auth';

export async function searchKnowledge(query: string, mode: SearchMode) {
  const response = await authFetch('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, mode })
  });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as { items: SearchEvidence[]; mode: SearchMode; elapsed_ms: number };
}

export async function fetchUserTasks(): Promise<UserTask[]> {
  const response = await authFetch('/api/tasks');
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json() as { items: UserTask[] };
  return data.items ?? [];
}

export async function fetchUserDocuments(): Promise<KnowledgeBaseItem[]> {
  const response = await authFetch('/api/documents');
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json() as { items: KnowledgeBaseItem[] };
  return data.items ?? [];
}
