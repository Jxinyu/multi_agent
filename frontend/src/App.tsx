import { AppHeader } from './components/AppHeader';
import { Composer } from './components/Composer';
import { MessageList } from './components/MessageList';
import { SessionSidebar } from './components/SessionSidebar';
import { useChatSession } from './hooks/useChatSession';

export default function App() {
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

  return (
    <div className="app-shell">
      <AppHeader threadId={session.threadId} status={session.status} messageCount={session.messageCount} />

      <div className="workspace layout-grid">
        <SessionSidebar
          items={history}
          activeThreadId={activeHistoryThreadId ?? session.threadId}
          onSelect={resumeSession}
        />
        <section className="workspace-main">
          <MessageList messages={session.messages} />
        </section>
      </div>

      <Composer
        disabled={session.busy}
        attachments={attachments}
        onSend={send}
        onStop={stop}
        onReset={resetThread}
        onAddAttachments={addAttachments}
        onRemoveAttachment={removeAttachment}
      />
    </div>
  );
}
