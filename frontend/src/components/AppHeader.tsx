import { Bot, LayoutDashboard, MessageSquareText, ShieldAlert } from 'lucide-react';

interface AppHeaderProps {
  threadId: string;
  status: string;
  messageCount: number;
  activeWorkspace: 'chat' | 'admin';
  onWorkspaceChange: (workspace: 'chat' | 'admin') => void;
}

export function AppHeader({ threadId, status, messageCount, activeWorkspace, onWorkspaceChange }: AppHeaderProps) {
  return (
    <header className="topbar chatgpt-topbar">
      <div className="brand">
        <div className="brand-mark">
          <Bot size={18} />
        </div>
        <div>
          <div className="brand-title">Enterprise Assistant</div>
          <div className="brand-subtitle">Chat + Knowledge Base Admin</div>
        </div>
      </div>

      <div className="topbar-meta">
        <button
          type="button"
          className={`pill nav-pill ${activeWorkspace === 'chat' ? 'active' : ''}`}
          onClick={() => onWorkspaceChange('chat')}
        >
          <MessageSquareText size={14} />
          Chat
        </button>
        <button
          type="button"
          className={`pill nav-pill ${activeWorkspace === 'admin' ? 'active' : ''}`}
          onClick={() => onWorkspaceChange('admin')}
        >
          <LayoutDashboard size={14} />
          Admin
        </button>
        <span className="pill">Thread {threadId}</span>
        <span className="pill">{messageCount} messages</span>
        <span className="pill warning">
          <ShieldAlert size={14} />
          {status}
        </span>
      </div>
    </header>
  );
}
