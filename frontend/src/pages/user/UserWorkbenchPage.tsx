import { BarChart3, BriefcaseBusiness, FileSearch, ReceiptText, ShieldCheck, UploadCloud, Wrench } from 'lucide-react';
import { useState } from 'react';

import { QueryComposer } from '../../components/QueryComposer';
import type { AttachmentDraft, ChatMessage, ChatSession } from '../../types';

interface SessionHistoryItem {
  threadId: string;
  title: string;
  updatedAt: number;
  messages: ChatMessage[];
  status: string;
}

interface UserWorkbenchPageProps {
  session: ChatSession;
  history: SessionHistoryItem[];
  attachments: AttachmentDraft[];
  onSend: (query: string) => Promise<void>;
  onStop: () => void;
  onAddAttachments: (files: FileList | File[]) => void | Promise<void>;
  onRemoveAttachment: (id: string) => void;
  onResume: (threadId: string) => void;
}

const shortcuts = [
  { label: 'HR 制度查询', detail: '查员工手册与政策', icon: ShieldCheck, prompt: '请说明员工差旅报销需要准备哪些材料？' },
  { label: '财务报销咨询', detail: '查流程与标准', icon: ReceiptText, prompt: '跨部门差旅报销的审批流程和费用标准是什么？' },
  { label: '合同审查助手', detail: '审合同条款与风险', icon: FileSearch, prompt: '请检查供应商合同中的自动续约和提前终止风险。' },
  { label: '技术故障排查', detail: '查方案与处理步骤', icon: Wrench, prompt: '请分析服务响应变慢的常见根因和排查顺序。' },
  { label: '跨域分析洞察', detail: '多维分析与结论', icon: BarChart3, prompt: '请从财务、法务和运营三个角度分析采购流程风险。' },
  { label: '上传文档提问', detail: '基于文档问答', icon: UploadCloud, prompt: '请总结我上传的文档并列出关键风险。' }
];

function formatHistoryTime(timestamp: number): string {
  const date = new Date(timestamp);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

export function UserWorkbenchPage({
  session,
  history,
  attachments,
  onSend,
  onStop,
  onAddAttachments,
  onRemoveAttachment,
  onResume
}: UserWorkbenchPageProps) {
  const [draft, setDraft] = useState('');
  const recent = history.slice(0, 5);

  return (
    <section className="ru-workbench-page">
      <div className="ru-workbench-intro">
        <span className="ru-eyebrow">企业多智能体工作区</span>
        <h1>今天需要解决什么？</h1>
        <p>基于企业知识与智能体，为你提供可追溯、可核验的答案。</p>
      </div>

      <div className="ru-shortcut-row" aria-label="快捷任务">
        {shortcuts.map((shortcut) => {
          const Icon = shortcut.icon;
          return (
            <button key={shortcut.label} type="button" onClick={() => setDraft(shortcut.prompt)}>
              <Icon size={25} />
              <span><strong>{shortcut.label}</strong><small>{shortcut.detail}</small></span>
            </button>
          );
        })}
      </div>

      {session.busy ? (
        <div className="ru-running-task" role="status">
          <div className="ru-signal-bars"><span /><span /><span /><span /></div>
          <div><strong>正在处理当前问题</strong><span>{session.status}</span><div><i /></div></div>
          <dl><div><dt>智能体</dt><dd>Supervisor</dd></div><div><dt>线程</dt><dd>{session.threadId}</dd></div></dl>
          <button type="button" onClick={onStop}>取消</button>
        </div>
      ) : null}

      <div className="ru-recent-section">
        <div className="ru-section-heading"><h2>最近工作</h2><span>{recent.length} 个会话</span></div>
        <div className="ru-recent-table" role="list">
          {recent.length > 0 ? recent.map((item) => (
            <button type="button" role="listitem" key={item.threadId} onClick={() => onResume(item.threadId)}>
              <BriefcaseBusiness size={17} />
              <strong>{item.title}</strong>
              <span className={`ru-status-dot ${item.status === '错误' ? 'is-error' : item.status === '已完成' ? 'is-complete' : ''}`}>{item.status}</span>
              <span>{item.messages.length} 条消息</span>
              <time>{formatHistoryTime(item.updatedAt)}</time>
            </button>
          )) : <div className="ru-empty-row">还没有会话记录，选择快捷任务或直接输入问题。</div>}
        </div>
      </div>

      <QueryComposer
        value={draft}
        onChange={setDraft}
        busy={session.busy}
        attachments={attachments}
        onSend={onSend}
        onStop={onStop}
        onAddAttachments={onAddAttachments}
        onRemoveAttachment={onRemoveAttachment}
      />
    </section>
  );
}
