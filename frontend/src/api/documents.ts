import { authFetch } from './auth';

export type DocumentAccessMode = 'user' | 'enterprise';
export type OriginalPreviewKind = 'pdf' | 'image' | 'text' | 'unsupported';

function contentPath(documentId: string, mode: DocumentAccessMode, purpose: 'preview' | 'download') {
  const prefix = mode === 'enterprise' ? '/api/admin/documents' : '/api/documents';
  return `${prefix}/${encodeURIComponent(documentId)}/content?purpose=${purpose}`;
}

export function originalPreviewKind(fileName: string): OriginalPreviewKind {
  const extension = fileName.slice(fileName.lastIndexOf('.')).toLowerCase();
  if (extension === '.pdf') return 'pdf';
  if (['.png', '.jpg', '.jpeg', '.bmp'].includes(extension)) return 'image';
  if (['.txt', '.md', '.csv', '.json'].includes(extension)) return 'text';
  return 'unsupported';
}

export async function fetchDocumentOriginal(documentId: string, mode: DocumentAccessMode): Promise<Blob> {
  const response = await authFetch(contentPath(documentId, mode, 'preview'));
  if (!response.ok) throw new Error(await response.text());
  return await response.blob();
}

export async function downloadDocumentOriginal(documentId: string, fileName: string, mode: DocumentAccessMode) {
  const response = await authFetch(contentPath(documentId, mode, 'download'));
  if (!response.ok) throw new Error(await response.text());
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
