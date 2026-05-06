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

export interface ChatSession {
  threadId: string;
  status: string;
  busy: boolean;
  messages: ChatMessage[];
  messageCount: number;
}
