export type Role = 'user' | 'assistant' | 'status' | 'error';

export type ChatReference = string;

export interface MessageAttachment {
  id: string;
  name: string;
  size: number;
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
  acl: string;
  upload_time: string;
  mode: string;
  file_path: string;
  file_path_md?: string | null;
  status: string;
  chunk_count: number;
  error?: string | null;
  ingest_progress?: number;
  ingest_total?: number;
  ingest_message?: string | null;
  batch_id?: string | null;
}

export interface ChatSession {
  threadId: string;
  status: string;
  busy: boolean;
  messages: ChatMessage[];
  messageCount: number;
}
