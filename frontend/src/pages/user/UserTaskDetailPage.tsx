import { AlertCircle, ArrowLeft, CheckCircle2, Clock3, ExternalLink, MessageSquareText, Paperclip, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchUserTask } from '../../api/user';
import { MessageList } from '../../components/MessageList';
import type { ChatMessage, UserTask, UserTaskDetail } from '../../types';

const statusLabel: Record<UserTask['status'], string> = {
  running: '运行中',
  waiting: '等待补充',
  completed: '已完成',
  failed: '失败',
  cancelled: '已中断'
};

function toChatMessages(detail: UserTaskDetail): ChatMessage[] {
  return detail.messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content,
    references: message.references,
    attachments: message.attachments.map((attachment, index) => ({
      id: `${message.id}-${index}`,
      name: attachment.name,
      mimeType: attachment.mime_type
    }))
  }));
}

export function UserTaskDetailPage() {
  const { taskId = '' } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<UserTaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      setDetail(await fetchUserTask(taskId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '任务详情加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [taskId]);

  if (loading) {
    return <div className="ru-task-detail-page"><div className="ru-task-detail-state"><RefreshCw className="is-spinning" /><strong>正在恢复会话详情</strong></div></div>;
  }

  if (error || !detail) {
    return <div className="ru-task-detail-page"><button className="ru-back-command" type="button" onClick={() => navigate('/app/tasks')}><ArrowLeft size={16} />返回任务列表</button><div className="ru-task-detail-state is-error"><AlertCircle /><strong>无法读取会话详情</strong><p>{error || '任务不存在'}</p><span>旧版审计任务只保留状态，不包含可恢复的问答正文。</span></div></div>;
  }

  const messages = toChatMessages(detail);
  return (
    <div className="ru-task-detail-page">
      <header className="ru-task-detail-title">
        <button type="button" onClick={() => navigate('/app/tasks')} aria-label="返回任务列表"><ArrowLeft size={18} /></button>
        <div><span>服务端会话记录</span><h1>{detail.title}</h1><p>{detail.id}</p></div>
        <button className="ru-primary-command" type="button" onClick={() => navigate(`/app/chat/${detail.id}`)}><ExternalLink size={16} />{detail.status === 'waiting' ? '补充信息' : '进入会话'}</button>
      </header>
      <div className="ru-task-detail-layout">
        <aside className="ru-task-metadata">
          <section><header><strong>执行概况</strong><span className={`ru-task-status is-${detail.status}`}>{detail.status === 'completed' ? <CheckCircle2 size={14} /> : <Clock3 size={14} />}{statusLabel[detail.status]}</span></header><dl><div><dt>创建时间</dt><dd>{new Date(detail.created_at).toLocaleString('zh-CN')}</dd></div><div><dt>最近更新</dt><dd>{new Date(detail.updated_at).toLocaleString('zh-CN')}</dd></div><div><dt>消息数量</dt><dd>{detail.messages.length}</dd></div><div><dt>附件数量</dt><dd>{detail.attachment_count}</dd></div></dl></section>
          <section><header><MessageSquareText size={16} /><strong>人工协作</strong></header>{detail.waiting_prompt ? <p className="ru-waiting-prompt">{detail.waiting_prompt}</p> : <p>当前没有等待处理的人工追问。</p>}</section>
          <section><header><Paperclip size={16} /><strong>反馈状态</strong></header><p>{detail.feedback === 'helpful' ? '已标记为有帮助' : detail.feedback === 'not_helpful' ? '已标记为需要改进' : '尚未提交回答反馈'}</p></section>
        </aside>
        <section className="ru-task-transcript"><header><MessageSquareText size={17} /><strong>完整问答记录</strong><span>{messages.length} 条</span></header>{messages.length ? <MessageList messages={messages} /> : <div className="ru-task-detail-state"><MessageSquareText /><strong>暂无可展示消息</strong></div>}</section>
      </div>
    </div>
  );
}
