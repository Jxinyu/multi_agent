import { AlertTriangle, ArrowLeft, ArrowRight, Clock3, Database, Inbox, RefreshCw, ServerCog, UsersRound } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchWorkerRuntime, type WorkerRuntimeSnapshot } from '../../api/platform';
import { jobOperationLabel, jobStatusLabel } from '../shared/jobStatus';

const elapsed = (milliseconds: number) => {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} 小时`;
  return `${Math.floor(hours / 24)} 天`;
};

export function AdminWorkerRuntimePage() {
  const navigate = useNavigate();
  const [data, setData] = useState<WorkerRuntimeSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setError('');
    try { setData(await fetchWorkerRuntime()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Worker 运行状态加载失败'); }
    finally { setLoading(false); }
  };

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 10000);
    return () => window.clearInterval(timer);
  }, []);

  const statusTotal = useMemo(() => data?.status_counts.reduce((sum, item) => sum + item.count, 0) ?? 0, [data]);
  const needsReview = Boolean(data?.active_jobs.length && data.queue.available && data.queue.pending === 0 && data.queue.lag === 0);

  return <div className="ru-admin-page ru-worker-runtime-page"><header className="ru-admin-title ru-admin-detail-title"><button type="button" onClick={() => navigate('/admin/operations')}><ArrowLeft size={16} />返回运行</button><div><h1>Worker 队列运行</h1><p>{data ? `采样于 ${new Date(data.checked_at).toLocaleString('zh-CN')}` : '正在读取 Redis Stream 与任务表'}</p></div><button type="button" disabled={loading} onClick={() => void load()}><RefreshCw className={loading ? 'ru-spin' : ''} size={16} />刷新</button></header>
    {error ? <div className="ru-inline-error">{error}</div> : null}
    {data && !data.queue.available ? <div className="ru-admin-notice is-danger"><AlertTriangle size={17} /><span><strong>Redis 队列快照不可用</strong>{data.queue.error}；数据库任务状态仍按当前租户展示。</span></div> : null}
    {needsReview ? <div className="ru-admin-notice"><AlertTriangle size={17} /><span><strong>任务状态需要核查</strong>数据库存在排队或执行中的任务，但当前消费者组 pending 与 lag 均为 0；请结合更新时间和 Worker 日志调查。</span></div> : null}

    <section className="ru-admin-kpis"><div><Database /><span>Stream 消息总量<strong>{data?.queue.available ? data.queue.stream_length : '—'}</strong></span></div><div><Inbox /><span>消费者组 Lag<strong>{data?.queue.available ? data.queue.lag ?? '未知' : '—'}</strong></span></div><div><Clock3 /><span>Pending<strong>{data?.queue.available ? data.queue.pending : '—'}</strong></span></div><div><AlertTriangle /><span>死信消息<strong>{data?.queue.available ? data.queue.dead_letter_length : '—'}</strong></span></div></section>

    <div className="ru-worker-runtime-grid"><section className="ru-admin-panel ru-worker-consumers"><header><strong><UsersRound size={16} />消费者注册</strong><span>{data?.queue.consumers.length ?? 0} 个</span></header>{data?.queue.consumers.map((consumer) => <div key={consumer.name}><span><ServerCog size={16} /><strong>{consumer.name}</strong></span><span>Pending<strong>{consumer.pending}</strong></span><span>距上次投递<strong>{elapsed(consumer.idle_ms)}</strong></span><span>Inactive<strong>{consumer.inactive_ms === null ? '未提供' : elapsed(consumer.inactive_ms)}</strong></span></div>)}{data?.queue.available && !data.queue.consumers.length ? <p>消费者组当前没有注册记录。</p> : null}</section>

      <section className="ru-admin-panel ru-worker-active"><header><strong><Clock3 size={16} />当前租户活动任务</strong><span>{data?.active_jobs.length ?? 0} 条</span></header>{data?.active_jobs.map((job) => <button type="button" key={job.id} onClick={() => navigate(`/admin/operations/worker/jobs/${job.id}`)}><span><strong>{job.file_name ?? '文档已删除'}</strong><small>{job.document_id}</small></span><span>{jobOperationLabel[job.operation] ?? job.operation}</span><em className={`is-${job.status}`}>{jobStatusLabel[job.status] ?? job.status}</em><time>更新于 {new Date(job.updated_at).toLocaleString('zh-CN')}</time><ArrowRight size={15} /></button>)}{data && !data.active_jobs.length ? <p>当前租户没有排队或执行中的数据库任务。</p> : null}</section>

      <section className="ru-admin-panel ru-worker-facts"><header><strong>队列与策略事实</strong><span>{statusTotal} 条租户任务</span></header><dl><div><dt>Stream</dt><dd>{data?.stream_name ?? '—'}</dd></div><div><dt>消费者组</dt><dd>{data?.group_name ?? '—'}</dd></div><div><dt>死信 Stream</dt><dd>{data?.dead_letter_stream_name ?? '—'}</dd></div><div><dt>最大尝试</dt><dd>{data?.worker_max_attempts ?? '—'}</dd></div><div><dt>阻塞读取</dt><dd>{data?.worker_block_ms ?? '—'} ms</dd></div><div><dt>独立心跳</dt><dd>{data?.heartbeat_available ? '已接入' : '未接入'}</dd></div></dl><p>{data?.observation_note}</p></section>

      <section className="ru-admin-panel ru-worker-distribution"><header><strong>当前租户任务状态</strong><span>数据库事实</span></header>{data?.status_counts.map((item) => <div key={item.status}><span>{jobStatusLabel[item.status] ?? item.status}</span><i><b style={{ width: `${statusTotal ? Math.max(4, item.count / statusTotal * 100) : 0}%` }} /></i><strong>{item.count}</strong></div>)}{data && !data.status_counts.length ? <p>当前租户没有任务记录。</p> : null}</section></div>
  </div>;
}
