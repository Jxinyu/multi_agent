import { History, MessageSquareText } from 'lucide-react';

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
}

function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  });
}

export function SessionSidebar({ items, activeThreadId, onSelect }: SessionSidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <History size={16} />
        <span>最近会话</span>
      </div>
      <div className="sidebar-list">
        {items.length === 0 ? (
          <div className="sidebar-empty">暂无历史会话</div>
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
                <span>{item.messages.length} 条</span>
              </div>
              <div className="session-card-time">{formatTime(item.updatedAt)}</div>
            </button>
          ))
        )}
      </div>
    </aside>
  );
}
