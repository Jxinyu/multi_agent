import type { AttachmentPayload, StreamEvent } from '../types';

export async function streamChat(
  query: string,
  threadId: string,
  attachments: AttachmentPayload[] = [],
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ query, thread_id: threadId, attachments }),
    signal
  });

  if (!response.ok || !response.body) {
    throw new Error(`HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() ?? '';

    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith('data: ')) continue;
      const payload = line.slice(6);
      if (!payload) continue;
      onEvent(JSON.parse(payload) as StreamEvent);
    }
  }
}

export function createThreadId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `thread_${crypto.randomUUID().slice(0, 8)}`;
  }
  return `thread_${Math.random().toString(36).slice(2, 10)}`;
}

export async function fileToAttachmentPayload(file: File): Promise<AttachmentPayload> {
  const dataBase64 = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== 'string') {
        reject(new Error('无法读取附件'));
        return;
      }
      const commaIndex = result.indexOf(',');
      resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error('附件读取失败'));
    reader.readAsDataURL(file);
  });

  return {
    name: file.name,
    mime_type: file.type || 'application/octet-stream',
    data_base64: dataBase64
  };
}
