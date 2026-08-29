import { Building2, ChevronDown, Mic, Paperclip, Send, Square, X } from 'lucide-react';
import { useRef, useState } from 'react';

import type { AttachmentDraft } from '../types';

interface QueryComposerProps {
  value: string;
  onChange: (value: string) => void;
  busy: boolean;
  attachments: AttachmentDraft[];
  onSend: (value: string) => void | Promise<void>;
  onStop: () => void;
  onAddAttachments: (files: FileList | File[]) => void | Promise<void>;
  onRemoveAttachment: (id: string) => void;
  compact?: boolean;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function QueryComposer({
  value,
  onChange,
  busy,
  attachments,
  onSend,
  onStop,
  onAddAttachments,
  onRemoveAttachment,
  compact = false
}: QueryComposerProps) {
  const [retrievalMode, setRetrievalMode] = useState<'精准' | '平衡' | '广泛'>('精准');
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const canSend = !busy && (value.trim().length > 0 || attachments.length > 0);

  const submit = () => {
    if (!canSend) return;
    void onSend(value.trim() || '请分析附件内容，并给出要点总结。');
    onChange('');
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div className={`ru-query-composer ${compact ? 'is-compact' : ''}`}>
      {attachments.length > 0 ? (
        <div className="ru-query-attachments">
          {attachments.map((attachment) => (
            <div key={attachment.id} className="ru-query-attachment">
              <span><strong>{attachment.name}</strong><small>{formatSize(attachment.size)}</small></span>
              <button type="button" onClick={() => onRemoveAttachment(attachment.id)} aria-label={`移除 ${attachment.name}`}><X size={14} /></button>
            </div>
          ))}
        </div>
      ) : null}

      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        rows={compact ? 1 : 3}
        placeholder="输入你的问题，Enter 发送，Shift + Enter 换行"
        disabled={busy}
      />

      <div className="ru-query-toolbar">
        <div className="ru-query-tools">
          <input
            ref={fileInputRef}
            className="ru-visually-hidden"
            type="file"
            multiple
            accept="image/png,image/jpeg,image/bmp,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.csv,.json"
            onChange={(event) => {
              if (event.target.files?.length) void onAddAttachments(event.target.files);
            }}
          />
          <button type="button" className="ru-square-control" onClick={() => fileInputRef.current?.click()} title="添加附件" aria-label="添加附件"><Paperclip size={18} /></button>
          <button type="button" className="ru-square-control" title="语音输入" aria-label="语音输入"><Mic size={18} /></button>
          <button type="button" className="ru-context-control"><Building2 size={16} /><span>数字化运营平台</span><ChevronDown size={14} /></button>
        </div>

        <div className="ru-query-submit">
          <div className="ru-retrieval-switch" aria-label="检索模式">
            {(['精准', '平衡', '广泛'] as const).map((mode) => (
              <button key={mode} type="button" className={retrievalMode === mode ? 'is-active' : ''} onClick={() => setRetrievalMode(mode)}>{mode}</button>
            ))}
          </div>
          {busy ? (
            <button type="button" className="ru-stop-button" onClick={onStop} aria-label="停止生成"><Square size={16} />停止</button>
          ) : (
            <button type="button" className="ru-send-button" onClick={submit} disabled={!canSend} aria-label="发送"><Send size={17} /><span>发送</span></button>
          )}
        </div>
      </div>
    </div>
  );
}
