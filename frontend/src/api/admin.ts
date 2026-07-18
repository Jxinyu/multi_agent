import type { CurrentUser, KnowledgeBaseItem } from '../types';
import { authFetch, openAuthenticatedXhr } from './auth';

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const response = await authFetch('/api/auth/me');
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const data = (await response.json()) as { user: CurrentUser };
  return data.user;
}

export async function fetchKnowledgeBaseItems(): Promise<KnowledgeBaseItem[]> {
  const response = await authFetch('/api/admin/documents');
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const data = (await response.json()) as { items: KnowledgeBaseItem[] };
  return data.items ?? [];
}

export async function fetchKnowledgeBaseProgress(id: string): Promise<KnowledgeBaseItem> {
  const response = await authFetch(`/api/admin/documents/${id}`);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const data = (await response.json()) as { item: KnowledgeBaseItem };
  return data.item;
}

export interface ResumableUploadOptions {
  title?: string;
  mode: 'rag' | 'graphrag';
  onProgress?: (progress: { fileName: string; uploadedBytes: number; totalBytes: number; percent: number }) => void;
}

function uploadChunkWithProgress(
  url: string,
  formData: FormData,
  onProgress: (loaded: number, total: number) => void
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = openAuthenticatedXhr('POST', url);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(event.loaded, event.total);
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(xhr.responseText || `HTTP ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error('网络错误，分片上传失败'));
    xhr.onabort = () => reject(new Error('分片上传已取消'));
    xhr.send(formData);
  });
}

async function parseUploadResponse(response: Response): Promise<KnowledgeBaseItem[]> {
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const data = (await response.json()) as { items?: KnowledgeBaseItem[]; item?: KnowledgeBaseItem };
  return data.items ?? (data.item ? [data.item] : []);
}

export async function uploadKnowledgeBaseDocuments(formData: FormData): Promise<KnowledgeBaseItem[]> {
  const response = await authFetch('/api/admin/documents/upload', {
    method: 'POST',
    body: formData
  });
  return parseUploadResponse(response);
}

async function uploadSingleResumableFile(file: File, options: ResumableUploadOptions): Promise<KnowledgeBaseItem[]> {
  const initResponse = await authFetch('/api/admin/uploads/resumable/init', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_name: file.name, file_size: file.size, title: options.title ?? '', mode: options.mode })
  });
  if (!initResponse.ok) throw new Error(await initResponse.text());
  const initData = (await initResponse.json()) as { upload_id: string; uploaded_chunks: number[]; chunk_size: number };
  const uploaded = new Set(initData.uploaded_chunks ?? []);
  const chunkSize = initData.chunk_size || 2 * 1024 * 1024;
  const totalChunks = Math.max(1, Math.ceil(file.size / chunkSize));

  const alreadyUploadedBytes = Math.min(file.size, uploaded.size * chunkSize);
  options.onProgress?.({
    fileName: file.name,
    uploadedBytes: alreadyUploadedBytes,
    totalBytes: file.size,
    percent: file.size === 0 ? 100 : Math.round((alreadyUploadedBytes / file.size) * 100)
  });

  for (let index = 0; index < totalChunks; index += 1) {
    const start = index * chunkSize;
    const end = Math.min(file.size, start + chunkSize);
    if (uploaded.has(index)) continue;
    const formData = new FormData();
    formData.append('chunk_index', String(index));
    formData.append('chunk', file.slice(start, end), file.name);
    await uploadChunkWithProgress(`/api/admin/uploads/resumable/${initData.upload_id}/chunk`, formData, (loaded) => {
      const uploadedBytes = Math.min(file.size, start + loaded);
      options.onProgress?.({
        fileName: file.name,
        uploadedBytes,
        totalBytes: file.size,
        percent: file.size === 0 ? 100 : Math.max(1, Math.round((uploadedBytes / file.size) * 100))
      });
    });
    options.onProgress?.({
      fileName: file.name,
      uploadedBytes: end,
      totalBytes: file.size,
      percent: file.size === 0 ? 100 : Math.round((end / file.size) * 100)
    });
  }

  const completeResponse = await authFetch('/api/admin/uploads/resumable/complete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ upload_id: initData.upload_id })
  });
  return parseUploadResponse(completeResponse);
}

export async function uploadKnowledgeBaseDocumentsResumable(files: File[], options: ResumableUploadOptions): Promise<KnowledgeBaseItem[]> {
  const uploadedItems: KnowledgeBaseItem[] = [];
  for (const file of files) {
    uploadedItems.push(...await uploadSingleResumableFile(file, options));
  }
  return uploadedItems;
}

export async function ingestKnowledgeBaseDocument(id: string, mode: 'rag' | 'graphrag'): Promise<KnowledgeBaseItem> {
  const response = await authFetch(`/api/admin/documents/${id}/ingest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode })
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const data = (await response.json()) as { items?: KnowledgeBaseItem[]; item?: KnowledgeBaseItem };
  const item = data.item ?? data.items?.[0];
  if (!item) throw new Error('入库响应缺少文档数据');
  return item;
}

export async function bulkIngestKnowledgeBaseDocuments(ids: string[], mode: 'rag' | 'graphrag'): Promise<KnowledgeBaseItem[]> {
  const response = await authFetch('/api/admin/documents/bulk/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, mode })
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const data = (await response.json()) as { items: KnowledgeBaseItem[] };
  return data.items ?? [];
}

export async function deleteKnowledgeBaseDocument(id: string): Promise<void> {
  const response = await authFetch(`/api/admin/documents/${id}`, {
    method: 'DELETE'
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
}

export async function bulkDeleteKnowledgeBaseDocuments(ids: string[]): Promise<void> {
  const response = await authFetch('/api/admin/documents/bulk/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids })
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
}

export async function deleteKnowledgeBase(): Promise<void> {
  const response = await authFetch('/api/admin/knowledge-base', {
    method: 'DELETE'
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
}
