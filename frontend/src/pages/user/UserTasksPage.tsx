import { AlertCircle, CheckCircle2, Clock3, RefreshCw, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchUserTasks } from '../../api/user';
import type { UserTask } from '../../types';

const statusLabel = { running: '运行中', waiting: '等待我处理', completed: '已完成', failed: '失败', cancelled: '已中断' };

export function UserTasksPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<UserTask[]>([]);
  const [filter, setFilter] = useState<'all' | UserTask['status']>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await fetchUserTasks();
      setItems(result);
      setSelectedId((current) => current ?? result[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '任务加载失败');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);
  const visible = useMemo(() => filter === 'all' ? items : items.filter((item) => item.status === filter), [filter, items]);
  const selected = items.find((item) => item.id === selectedId) ?? null;

  return (
    <div className="ru-tasks-page">
      <section className="ru-task-list-panel">
        <header className="ru-page-title"><div><h1>任务与追问</h1><p>查看多智能体任务状态并继续待补充会话。</p></div><button type="button" onClick={() => void load()} aria-label="刷新任务"><RefreshCw size={17} /></button></header>
        <div className="ru-task-tabs">
          {(['all', 'running', 'waiting', 'completed', 'failed', 'cancelled'] as const).map((value) => (
            <button key={value} type="button" className={filter === value ? 'is-active' : ''} onClick={() => setFilter(value)}>
              {value === 'all' ? '全部' : statusLabel[value]} <strong>{value === 'all' ? items.length : items.filter((item) => item.status === value).length}</strong>
            </button>
          ))}
        </div>
        <div className="ru-task-toolbar"><div><Search size={15} /><input placeholder="搜索任务 ID" aria-label="搜索任务" /></div><span>按最近更新排序</span></div>
        <div className="ru-task-table">
          <div className="ru-task-table-head"><span>任务 ID</span><span>状态</span><span>附件</span><span>创建时间</span><span>操作</span></div>
          {loading ? <div className="ru-data-empty"><RefreshCw className="is-spinning" size={28} /><strong>正在加载任务</strong></div> : null}
          {error ? <div className="ru-inline-error">{error}</div> : null}
          {!loading && !error && visible.length === 0 ? <div className="ru-data-empty"><Clock3 size={30} /><strong>暂无此类任务</strong><span>从 AI 工作台发起问题后，执行状态会出现在这里。</span></div> : null}
          {visible.map((item) => (
            <button key={item.id} type="button" className={selectedId === item.id ? 'is-selected' : ''} onClick={() => setSelectedId(item.id)}>
              <span><strong>{item.id}</strong><small>多智能体会话任务</small></span>
              <span className={`ru-task-status is-${item.status}`}>{item.status === 'completed' ? <CheckCircle2 size={13} /> : item.status === 'failed' || item.status === 'cancelled' ? <AlertCircle size={13} /> : <Clock3 size={13} />}{statusLabel[item.status]}</span>
              <span>{item.attachment_count} 个</span>
              <time>{new Date(item.created_at).toLocaleString('zh-CN')}</time>
              <span className="ru-table-action">{item.status === 'waiting' ? '处理' : '查看'}</span>
            </button>
          ))}
        </div>
      </section>
      <aside className="ru-task-detail">
        {selected ? (
          <>
            <header><div><span className={`ru-task-status is-${selected.status}`}>{statusLabel[selected.status]}</span><h2>{selected.id}</h2></div></header>
            <section><h3>执行概况</h3><dl><div><dt>当前状态</dt><dd>{statusLabel[selected.status]}</dd></div><div><dt>创建时间</dt><dd>{new Date(selected.created_at).toLocaleString('zh-CN')}</dd></div><div><dt>附件数量</dt><dd>{selected.attachment_count}</dd></div></dl></section>
            <section><h3>{selected.status === 'waiting' ? '需要你的补充' : '任务操作'}</h3><p>{selected.status === 'waiting' ? 'Supervisor 正在等待补充信息。进入会话后提交回答即可从断点继续。' : '可进入会话查看完整问答、路由状态和引用证据。'}</p><button className="ru-primary-command" type="button" onClick={() => navigate(`/app/chat/${selected.id}`)}>{selected.status === 'waiting' ? '进入会话并补充' : '查看会话'}</button></section>
          </>
        ) : <div className="ru-data-empty"><Clock3 size={30} /><strong>选择一个任务</strong><span>右侧将显示执行状态和可用操作。</span></div>}
      </aside>
    </div>
  );
}
