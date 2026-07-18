import { useState } from 'react';

import { AdminPanel } from './components/AdminPanel';
import { AppHeader } from './components/AppHeader';
import { Composer } from './components/Composer';
import { MessageList } from './components/MessageList';
import { SessionSidebar } from './components/SessionSidebar';
import { useChatSession } from './hooks/useChatSession';

export default function App() {
  const [activeWorkspace, setActiveWorkspace] = useState<'chat' | 'admin'>('chat');
  const {
    session,
    history,
    activeHistoryThreadId,
    attachments,
    send,
    stop,
    resetThread,
    resumeSession,
    addAttachments,
    removeAttachment
  } = useChatSession();

  if (activeWorkspace === 'admin') {
    return (
      <div className="admin-app-shell">
        <AppHeader
          threadId={session.threadId}
          status={session.status}
          messageCount={session.messageCount}
          activeWorkspace={activeWorkspace}
          onWorkspaceChange={setActiveWorkspace}
        />
        <AdminPanel />
      </div>
    );
  }

  return (
    <div className="app-shell chat-app-shell">
      <AppHeader
        threadId={session.threadId}
        status={session.status}
        messageCount={session.messageCount}
        activeWorkspace={activeWorkspace}
        onWorkspaceChange={setActiveWorkspace}
      />

      <div className="workspace chatgpt-layout">
        <SessionSidebar
          items={history}
          activeThreadId={activeHistoryThreadId ?? session.threadId}
          onSelect={resumeSession}
          onNewChat={resetThread}
          activeWorkspace={activeWorkspace}
        />

        <main className="workspace-main chatgpt-main">
          <div className="chat-surface">
            {session.messages.length > 0 ? (
              <MessageList messages={session.messages} />
            ) : (
              <div className="chat-empty-state">
                <div className="chat-empty-copy">
                  <div className="chat-badge">ChatGPT-style workspace</div>
                  <h1>一个更克制、更清晰的对话界面</h1>
                  <p>左侧是历史会话，主区域是对话流，底部是输入栏。后台管理已拆成独立页面，便于后续扩展更多功能。</p>
                </div>
                <div className="chat-suggestion-grid">
                  <button type="button" className="suggestion-card" onClick={resetThread}>
                    <strong>新建会话</strong>
                    <span>从干净上下文开始一个新的工作线程。</span>
                  </button>
                  <button type="button" className="suggestion-card" onClick={() => setActiveWorkspace('admin')}>
                    <strong>进入后台</strong>
                    <span>打开独立后台管理页面，管理知识库和后续功能。</span>
                  </button>
                  <button type="button" className="suggestion-card" onClick={() => void 0}>
                    <strong>上传附件</strong>
                    <span>把业务资料、说明文档和数据文件直接带入对话。</span>
                  </button>
                </div>
              </div>
            )}
          </div>

          <Composer
            disabled={session.busy}
            attachments={attachments}
            onSend={send}
            onStop={stop}
            onAddAttachments={addAttachments}
            onRemoveAttachment={removeAttachment}
          />
        </main>
      </div>
    </div>
  );
}
