import { useEffect, useMemo, useRef, useState } from 'react';

import { createThreadId, fileToAttachmentPayload, streamChat } from '../api/chat';
import { fetchUserTask } from '../api/user';
import type {
  AttachmentDraft,
  AttachmentPayload,
  ChatMessage,
  ChatSession,
  MessageAttachment
} from '../types';

interface SessionHistoryItem {
  threadId: string;
  title: string;
  updatedAt: number;
  messages: ChatMessage[];
  status: string;
}

const HISTORY_STORAGE_KEY = 'rag-upper.sessions.v1';

const WELCOME_MESSAGE: ChatMessage = {
  id: 'welcome',
  role: 'assistant',
  content: '你好，我是企业多智能体助手。你可以输入文本，也可以上传图片、PDF、截图或办公文档。'
};

function createId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2);
}

function titleFromMessages(messages: ChatMessage[]): string {
  const firstUser = messages.find((message) => message.role === 'user');
  if (!firstUser) return '新会话';
  const text = firstUser.content.trim().replace(/\s+/g, ' ');
  return text.length > 18 ? `${text.slice(0, 18)}...` : text;
}

async function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== 'string') {
        reject(new Error('无法读取图片预览'));
        return;
      }
      resolve(result);
    };
    reader.onerror = () => reject(reader.error ?? new Error('图片预览读取失败'));
    reader.readAsDataURL(file);
  });
}

async function buildAttachmentPayloads(drafts: AttachmentDraft[]): Promise<AttachmentPayload[]> {
  const payloads: AttachmentPayload[] = [];
  for (const draft of drafts) {
    payloads.push(await fileToAttachmentPayload(draft.file));
  }
  return payloads;
}

function toMessageAttachments(drafts: AttachmentDraft[]): MessageAttachment[] {
  return drafts.map((draft) => ({
    id: draft.id,
    name: draft.name,
    size: draft.size,
    mimeType: draft.mimeType,
    previewUrl: draft.previewUrl
  }));
}

export function useChatSession() {
  const [threadId, setThreadId] = useState(() => createThreadId());
  const [status, setStatus] = useState('就绪');
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MESSAGE]);
  const [feedback, setFeedback] = useState<'helpful' | 'not_helpful' | null>(null);
  const [history, setHistory] = useState<SessionHistoryItem[]>([]);
  const [activeHistoryThreadId, setActiveHistoryThreadId] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<AttachmentDraft[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const session: ChatSession = useMemo(
    () => ({
      threadId,
      status,
      busy,
      messages,
      messageCount: messages.length,
      feedback
    }),
    [busy, feedback, messages, status, threadId]
  );

  useEffect(() => {
    try {
      localStorage.removeItem(HISTORY_STORAGE_KEY);
    } catch {
      // In-memory history remains available when browser storage is inaccessible.
    }
  }, []);

  useEffect(() => {
    setHistory((current) => {
      const entry: SessionHistoryItem = {
        threadId,
        title: titleFromMessages(messages),
        updatedAt: Date.now(),
        messages,
        status
      };
      const others = current.filter((item) => item.threadId !== threadId);
      return [entry, ...others].slice(0, 8);
    });
  }, [messages, status, threadId]);

  const appendMessage = (message: Omit<ChatMessage, 'id'>) => {
    setMessages((current) => [...current, { ...message, id: createId() }]);
  };

  const updateLastStatus = (content: string) => {
    setMessages((current) => {
      const next = [...current];
      const last = next[next.length - 1];
      if (last && last.role === 'status') {
        next[next.length - 1] = { ...last, content };
        return next;
      }
      return [...next, { id: createId(), role: 'status', content }];
    });
  };

  const resetThread = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setThreadId(createThreadId());
    setStatus('就绪');
    setBusy(false);
    setMessages([WELCOME_MESSAGE]);
    setFeedback(null);
    setActiveHistoryThreadId(null);
    setAttachments([]);
  };

  const createNewChat = () => {
    resetThread();
  };

  const stop = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    setStatus('已停止');
    appendMessage({ role: 'status', content: '本次请求已停止。' });
  };

  const resumeSession = (targetThreadId: string) => {
    const item = history.find((entry) => entry.threadId === targetThreadId);
    if (!item) return;

    abortRef.current?.abort();
    abortRef.current = null;
    setThreadId(item.threadId);
    setStatus(item.status);
    setBusy(false);
    setMessages(item.messages);
    setActiveHistoryThreadId(item.threadId);
    setAttachments([]);
  };

  const loadSession = async (targetThreadId: string) => {
    abortRef.current?.abort();
    abortRef.current = null;
    setThreadId(targetThreadId);
    setStatus('正在恢复会话');
    setBusy(true);
    setAttachments([]);
    try {
      const detail = await fetchUserTask(targetThreadId);
      const restoredMessages: ChatMessage[] = detail.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        references: message.references,
        attachments: message.attachments.map((attachment, index) => ({
          id: `${message.id}-${index}`,
          name: attachment.name,
          mimeType: attachment.mime_type
        }))
      }));
      setMessages(restoredMessages.length ? restoredMessages : [WELCOME_MESSAGE]);
      setFeedback(detail.feedback ?? null);
      setStatus(detail.status === 'waiting' ? '等待补充' : detail.status === 'completed' ? '已完成' : detail.status === 'failed' ? '错误' : detail.status === 'cancelled' ? '已停止' : '运行中');
      setActiveHistoryThreadId(targetThreadId);
      return detail;
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '会话恢复失败';
      setStatus('错误');
      setMessages([WELCOME_MESSAGE, { id: createId(), role: 'error', content: message }]);
      throw reason;
    } finally {
      setBusy(false);
    }
  };

  const addAttachments = async (files: FileList | File[]) => {
    const next = [...attachments];
    for (const file of Array.from(files)) {
      const previewUrl = file.type.startsWith('image/') ? await readFileAsDataUrl(file) : undefined;
      next.push({
        id: createId(),
        file,
        name: file.name,
        size: file.size,
        mimeType: file.type || 'application/octet-stream',
        previewUrl
      });
    }
    setAttachments(next);
  };

  const removeAttachment = (id: string) => {
    setAttachments((current) => current.filter((item) => item.id !== id));
  };

  const clearAttachments = () => {
    setAttachments([]);
  };

  const send = async (query: string) => {
    if (busy) return;

    const controller = new AbortController();
    abortRef.current = controller;

    const currentAttachments = attachments;
    const messageAttachments = toMessageAttachments(currentAttachments);
    setAttachments([]);
    setFeedback(null);

    appendMessage({ role: 'user', content: query, attachments: messageAttachments });

    setBusy(true);
    setStatus(currentAttachments.length > 0 ? '上传附件中' : '请求中');

    try {
      const payloads = await buildAttachmentPayloads(currentAttachments);
      await streamChat(
        query,
        threadId,
        payloads,
        (event) => {
          if (event.type === 'status') {
            setStatus(event.message);
            updateLastStatus(event.message);
            return;
          }

          if (event.type === 'interrupt') {
            setStatus('等待补充');
            appendMessage({ role: 'status', content: event.message });
            return;
          }

          if (event.type === 'error') {
            setStatus('错误');
            appendMessage({ role: 'error', content: event.message });
            return;
          }

          setStatus('已完成');
          appendMessage({
            role: 'assistant',
            content: event.message,
            references: event.references ?? []
          });
        },
        controller.signal
      );
    } catch (error) {
      if (controller.signal.aborted) return;
      const message = error instanceof Error ? error.message : '请求失败';
      setStatus('错误');
      appendMessage({ role: 'error', content: message });
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
      if (!controller.signal.aborted) {
        setBusy(false);
      }
    }
  };

  return {
    session,
    history,
    activeHistoryThreadId,
    attachments,
    send,
    stop,
    resetThread,
    createNewChat,
    resumeSession,
    loadSession,
    addAttachments,
    removeAttachment,
    clearAttachments
  };
}
