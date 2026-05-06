import { Bot, Server, ShieldAlert, Sparkles } from 'lucide-react';

interface AppHeaderProps {
  threadId: string;
  status: string;
  messageCount: number;
}

export function AppHeader({ threadId, status, messageCount }: AppHeaderProps) {
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark">
          <Bot size={18} />
        </div>
        <div>
          <div className="brand-title">企业智能助手</div>
          <div className="brand-subtitle">内部知识检索与多代理调度</div>
        </div>
      </div>
      <div className="topbar-meta">
        <span className="pill">
          <Server size={14} />
          {threadId}
        </span>
        <span className="pill">
          <Sparkles size={14} />
          {messageCount} 条消息
        </span>
        <span className="pill warning">
          <ShieldAlert size={14} />
          {status}
        </span>
      </div>
    </header>
  );
}
