export type Role = 'user' | 'assistant' | 'status' | 'error';

export type ChatReference = string;

export interface MessageAttachment {
  id: string;
  name: string;
  size?: number;
  mimeType: string;
  previewUrl?: string;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  references?: ChatReference[];
  attachments?: MessageAttachment[];
}

export interface AttachmentDraft {
  id: string;
  file: File;
  name: string;
  size: number;
  mimeType: string;
  previewUrl?: string;
}

export interface AttachmentPayload {
  name: string;
  mime_type: string;
  data_base64: string;
}

export type StreamEvent =
  | { type: 'status'; message: string }
  | { type: 'complete'; message: string; references?: ChatReference[] }
  | { type: 'interrupt'; message: string; references?: ChatReference[] }
  | { type: 'error'; message: string };

export interface CurrentUser {
  user_id: string;
  username: string;
  tenant_id: string;
  role: string;
  permissions: string[];
}

export interface KnowledgeBaseItem {
  id: string;
  file_name: string;
  title: string;
  tenant_id: string;
  owner_id: string;
  acl: string[];
  upload_time: string;
  mode: string;
  status: string;
  chunk_count: number;
  error?: string | null;
  ingest_progress?: number;
  ingest_total?: number;
  ingest_message?: string | null;
  batch_id?: string | null;
  version: number;
  checksum: string;
  backend_status: Record<string, string>;
}

export interface DocumentDetail {
  item: KnowledgeBaseItem;
  preview?: string | null;
  preview_truncated: boolean;
}

export interface ChatSession {
  threadId: string;
  status: string;
  busy: boolean;
  messages: ChatMessage[];
  messageCount: number;
  feedback?: 'helpful' | 'not_helpful' | null;
}

export type SearchMode = 'milvus' | 'graph' | 'mg';

export interface SearchEvidence {
  id: string;
  source: string;
  content: string;
  score: number | null;
  kind: string;
  backend: string;
  document_id?: string | null;
  version?: number | null;
  chunk_index?: number | null;
}

export interface UserTask {
  id: string;
  status: 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled';
  created_at: string;
  updated_at: string;
  attachment_count: number;
  title: string;
  detail_available: boolean;
}

export interface UserTaskMessage {
  id: string;
  role: Role;
  content: string;
  references: string[];
  attachments: { name: string; mime_type: string }[];
  created_at: string;
}

export interface UserTaskDetail {
  id: string;
  status: UserTask['status'];
  title: string;
  created_at: string;
  updated_at: string;
  attachment_count: number;
  waiting_prompt?: string | null;
  feedback?: 'helpful' | 'not_helpful' | null;
  messages: UserTaskMessage[];
}
