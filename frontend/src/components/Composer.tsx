import { Paperclip, Send, Square, X } from 'lucide-react';
import { useRef, useState } from 'react';

import type { AttachmentDraft } from '../types';

interface ComposerProps {
  disabled?: boolean;
  attachments: AttachmentDraft[];
  onSend: (value: string) => void;
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
  onStop,
  onAddAttachments,
  onRemoveAttachment
}: ComposerProps) {
  const [value, setValue] = useState('');
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const canSubmit = !disabled && (value.trim().length > 0 || attachments.length > 0);

  const submit = () => {
    if (!canSubmit) return;
    onSend(value.trim() || '请分析附件内容，并给出要点总结。');
    setValue('');
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <footer className="composer-shell chatgpt-composer-shell">
      <div className="composer chatgpt-composer">
        <div className="composer-main">
          <div className="composer-hint">Press Enter to send, Shift+Enter for a new line</div>
          <div className="composer-input-wrap">
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
              placeholder="Message..."
              rows={2}
              disabled={disabled}
            />
            <div className="composer-attach-slot">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="sr-file-input"
                accept="image/png,image/jpeg,image/bmp,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.csv,.json"
                onChange={(event) => {
                  if (event.target.files?.length) onAddAttachments(event.target.files);
                }}
              />
              <button type="button" className="attach-button" onClick={() => fileInputRef.current?.click()}>
                <Paperclip size={15} />
              </button>
            </div>
          </div>

          {attachments.length > 0 ? (
            <div className="attachment-strip">
              {attachments.map((item) => (
                <div className="attachment-chip" key={item.id}>
                  {item.previewUrl ? <img className="attachment-preview" src={item.previewUrl} alt="" /> : null}
                  <div className="attachment-chip-meta">
                    <span className="attachment-name">{item.name}</span>
                    <span className="attachment-size">{formatSize(item.size)}</span>
                  </div>
                  <button type="button" className="attachment-remove" onClick={() => onRemoveAttachment(item.id)}>
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="composer-actions">
          {disabled ? (
            <button type="button" className="icon-button danger" onClick={onStop}>
              <Square size={15} />
              Stop
            </button>
          ) : null}
          <button type="button" className="icon-button primary" onClick={submit} disabled={!canSubmit}>
            <Send size={16} />
            <span>Send</span>
          </button>
        </div>
      </div>
    </footer>
  );
}
