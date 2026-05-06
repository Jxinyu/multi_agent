import { Paperclip, RotateCcw, Send, Square, X } from 'lucide-react';
import { useRef, useState } from 'react';

import type { AttachmentDraft } from '../types';

interface ComposerProps {
  disabled?: boolean;
  attachments: AttachmentDraft[];
  onSend: (value: string) => void;
  onReset: () => void;
  onStop: () => void;
  onAddAttachments: (files: FileList | File[]) => void;
  onRemoveAttachment: (id: string) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function Composer({
  disabled,
  attachments,
  onSend,
  onReset,
  onStop,
  onAddAttachments,
  onRemoveAttachment
}: ComposerProps) {
  const [value, setValue] = useState('');
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const canSubmit = !disabled && (value.trim().length > 0 || attachments.length > 0);

  const submit = () => {
    const text = value.trim();
    if (!canSubmit) return;
    onSend(text || '请分析附件内容，并给出要点总结。');
    setValue('');
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <footer className="composer-shell">
      <div className="composer">
        <div className="composer-main">
          <textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            className="composer-input"
            placeholder="输入业务问题，Enter 发送，Shift+Enter 换行"
            rows={2}
            disabled={disabled}
          />

          {attachments.length > 0 ? (
            <div className="attachment-strip">
              {attachments.map((item) => (
                <div className="attachment-chip" key={item.id}>
                  {item.previewUrl ? <img className="attachment-preview" src={item.previewUrl} alt="" /> : null}
                  <div className="attachment-chip-meta">
                    <span className="attachment-name">{item.name}</span>
                    <span className="attachment-size">{formatSize(item.size)}</span>
                  </div>
                  <button
                    type="button"
                    className="attachment-remove"
                    onClick={() => onRemoveAttachment(item.id)}
                    title="移除附件"
                  >
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="composer-actions">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="sr-file-input"
            accept="image/png,image/jpeg,image/bmp,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.csv,.json"
            onChange={(event) => {
              if (event.target.files?.length) {
                onAddAttachments(event.target.files);
              }
            }}
          />
          <button type="button" className="icon-button secondary" onClick={() => fileInputRef.current?.click()}>
            <Paperclip size={16} />
            <span>附件</span>
          </button>
          {disabled ? (
            <button type="button" className="icon-button danger" onClick={onStop} title="停止">
              <Square size={15} />
            </button>
          ) : null}
          <button type="button" className="icon-button secondary" onClick={onReset} title="新会话">
            <RotateCcw size={16} />
          </button>
          <button type="button" className="icon-button primary" onClick={submit} disabled={!canSubmit}>
            <Send size={16} />
            <span>发送</span>
          </button>
        </div>
      </div>
    </footer>
  );
}
