import { ChevronDown, ChevronRight, FileText, ImageIcon, Link } from 'lucide-react';
import { useState } from 'react';

import type { ChatMessage } from '../types';

interface MessageItemProps {
  message: ChatMessage;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function MessageItem({ message }: MessageItemProps) {
  const isUser = message.role === 'user';
  const isStatus = message.role === 'status' || message.role === 'error';
  const hasReferences = Boolean(message.references && message.references.length > 0);
  const hasAttachments = Boolean(message.attachments && message.attachments.length > 0);
  const [referencesOpen, setReferencesOpen] = useState(true);

  return (
    <div className={`message-row ${isUser ? 'message-row-user' : 'message-row-ai'}`}>
      <div className={`message-avatar ${isUser ? 'user-avatar' : 'assistant-avatar'}`}>{isUser ? 'You' : 'AI'}</div>
      <div
        className={`message-bubble ${
          isUser ? 'message-bubble-user' : isStatus ? 'message-bubble-status' : 'message-bubble-ai'
        }`}
      >
        {hasAttachments ? (
          <div className="message-attachments">
            {message.attachments?.map((attachment) => {
              const isImage = attachment.mimeType.startsWith('image/');
              return (
                <div className="message-attachment" key={attachment.id}>
                  {attachment.previewUrl ? (
                    <img className="message-attachment-thumb" src={attachment.previewUrl} alt="" />
                  ) : (
                    <div className="message-attachment-icon">
                      {isImage ? <ImageIcon size={16} /> : <FileText size={16} />}
                    </div>
                  )}
                  <div className="message-attachment-meta">
                    <span className="message-attachment-name">{attachment.name}</span>
                    <span className="message-attachment-size">{formatSize(attachment.size)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
        {message.content ? <div className="message-text">{message.content}</div> : null}
        {hasReferences ? (
          <div className="message-references">
            <button
              type="button"
              className="message-references-toggle"
              onClick={() => setReferencesOpen((current) => !current)}
            >
              {referencesOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <Link size={14} />
              <span>Sources</span>
            </button>
            {referencesOpen ? (
              <ul>
                {message.references?.map((ref, index) => (
                  <li key={`${message.id}-${index}`}>{ref}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
