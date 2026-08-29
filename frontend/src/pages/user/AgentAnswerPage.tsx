import { Check, Circle, Copy, Download, FileText, RotateCcw, ThumbsDown, ThumbsUp } from 'lucide-react';
import { useMemo, useState } from 'react';

import { MessageList } from '../../components/MessageList';
import { QueryComposer } from '../../components/QueryComposer';
import type { AttachmentDraft, ChatSession } from '../../types';

interface AgentAnswerPageProps {
  session: ChatSession;
  attachments: AttachmentDraft[];
  onSend: (query: string) => Promise<void>;
  onStop: () => void;
  onAddAttachments: (files: FileList | File[]) => void | Promise<void>;
  onRemoveAttachment: (id: string) => void;
}

const routeSteps = ['意图识别', '领域智能体', '混合检索', '证据校验', '答案整合'];

export function AgentAnswerPage({ session, attachments, onSend, onStop, onAddAttachments, onRemoveAttachment }: AgentAnswerPageProps) {
  const [draft, setDraft] = useState('');
  const references = useMemo(
    () => [...session.messages].reverse().find((message) => message.references?.length)?.references ?? [],
    [session.messages]
  );
  const currentStep = session.busy ? Math.min(3, Math.max(1, session.messages.filter((message) => message.role === 'status').length)) : 5;

  return (
    <section className="ru-answer-page">
      <div className="ru-answer-main">
        <header className="ru-answer-header">
          <div><h1>多智能体回答</h1><span>线程 {session.threadId} · {session.status}</span></div>
          <div className="ru-answer-actions">
            <button type="button" title="复制答案"><Copy size={16} /></button>
            <button type="button" title="导出"><Download size={16} /></button>
            <button type="button" title="有帮助"><ThumbsUp size={16} /></button>
            <button type="button" title="没帮助"><ThumbsDown size={16} /></button>
            <button type="button" title="重新生成"><RotateCcw size={16} /></button>
          </div>
        </header>

        <div className="ru-route-trace" aria-label="智能体执行过程">
          <strong>执行过程 <span>Supervisor</span></strong>
          <div>
            {routeSteps.map((step, index) => {
              const position = index + 1;
              const completed = position < currentStep || (!session.busy && currentStep === 5);
              const active = session.busy && position === currentStep;
              return (
                <div className={`ru-route-step ${completed ? 'is-complete' : ''} ${active ? 'is-active' : ''}`} key={step}>
                  <span>{completed ? <Check size={15} /> : <Circle size={15} />}</span>
                  <small>{step}</small>
                </div>
              );
            })}
          </div>
        </div>

        <div className="ru-answer-stream">
          <MessageList messages={session.messages} />
        </div>

        <QueryComposer
          compact
          value={draft}
          onChange={setDraft}
          busy={session.busy}
          attachments={attachments}
          onSend={onSend}
          onStop={onStop}
          onAddAttachments={onAddAttachments}
          onRemoveAttachment={onRemoveAttachment}
        />
      </div>

      <aside className="ru-evidence-panel">
        <header><strong>证据 {references.length > 0 ? `1/${references.length}` : '0/0'}</strong><button type="button">打开原文</button></header>
        {references.length > 0 ? (
          <>
            <div className="ru-evidence-source"><FileText size={19} /><div><strong>{references[0]}</strong><span>来自当前授权知识范围</span></div></div>
            <div className="ru-evidence-highlight"><span>匹配内容</span><p>{references[0]}</p></div>
            <dl><div><dt>引用编号</dt><dd>[1]</dd></div><div><dt>访问范围</dt><dd>已授权</dd></div><div><dt>线程</dt><dd>{session.threadId}</dd></div></dl>
          </>
        ) : (
          <div className="ru-evidence-empty"><FileText size={24} /><strong>暂无可展示证据</strong><span>回答返回引用后将在此处显示，系统不会生成占位来源。</span></div>
        )}
      </aside>
    </section>
  );
}
