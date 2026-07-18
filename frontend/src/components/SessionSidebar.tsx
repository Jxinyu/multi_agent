import { History, MessageSquareText, Plus } from 'lucide-react';

import type { ChatMessage } from '../types';

interface SessionItem {
  threadId: string;
  title: string;
  updatedAt: number;
  messages: ChatMessage[];
  status: string;
}

interface SessionSidebarProps {
  items: SessionItem[];
  activeThreadId: string | null;
  onSelect: (threadId: string) => void;
  onNewChat: () => void;
  activeWorkspace: 'chat' | 'admin';
}

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  });
}

export function SessionSidebar({ items, activeThreadId, onSelect, onNewChat, activeWorkspace }: SessionSidebarProps) {
  return (
    <aside className="sidebar chatgpt-sidebar">
      <div className="sidebar-header">
        <History size={16} />
        <span>History</span>
      </div>

      {activeWorkspace === 'chat' ? (
        <button type="button" className="new-thread-card" onClick={onNewChat}>
          <Plus size={14} />
          <span>New chat</span>
        </button>
      ) : null}

      <div className="sidebar-section-label">Recent conversations</div>
      <div className="sidebar-list">
        {items.length === 0 ? (
          <div className="sidebar-empty">No history yet</div>
        ) : (
          items.map((item) => (
            <button
              key={item.threadId}
              type="button"
              className={`session-card ${activeThreadId === item.threadId ? 'active' : ''}`}
              onClick={() => onSelect(item.threadId)}
            >
              <div className="session-card-title">
                <MessageSquareText size={14} />
                <span>{item.title}</span>
              </div>
              <div className="session-card-meta">
                <span>{item.status}</span>
                <span>{item.messages.length} msgs</span>
              </div>
              <div className="session-card-time">{formatTime(item.updatedAt)}</div>
            </button>
          ))
        )}
      </div>
    </aside>
  );
}
