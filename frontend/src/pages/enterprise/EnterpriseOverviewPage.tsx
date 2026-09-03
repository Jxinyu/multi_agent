import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Clock3, Database, RefreshCw, Search, Users } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchDependencyHealth, fetchEnterpriseOverview, type EnterpriseOverview } from '../../api/enterprise';

export function EnterpriseOverviewPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<EnterpriseOverview | null>(null);
  const [health, setHealth] = useState<Record<string, boolean>>({});
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true); setError('');
    try {
      const [overview, checks] = await Promise.all([fetchEnterpriseOverview(), fetchDependencyHealth()]);
      setData(overview); setHealth(checks);
    } catch (reason) { setError(reason instanceof Error ? reason.message : '总览加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);
  const completionRate = useMemo(() => data?.conversation_count ? data.completed_count / data.conversation_count : 0, [data]);
  const statusWidth = (count: number | undefined) => data?.conversation_count ? `${(count ?? 0) / data.conversation_count * 100}%` : '0%';
  const documentHealth = data?.document_count ? data.healthy_document_count / data.document_count : 0;

  return (
    <div className="ru-enterprise-page">
      <header className="ru-console-title"><div><h1>企业运营总览</h1><p>{data?.data_window ?? '正在读取租户运行数据'}</p></div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button></header>
      {error ? <div className="ru-inline-error">{error}</div> : null}
      <section className="ru-kpi-strip">
        <div><span><Users size={15} />观测用户</span><strong>{data?.observed_actors.length ?? '—'}</strong><small>来自租户审计事件</small></div>
        <div><span><CheckCircle2 size={15} />问答完成率</span><strong>{loading ? '—' : `${(completionRate * 100).toFixed(1)}%`}</strong><small>{data?.completed_count ?? 0}/{data?.conversation_count ?? 0} 个会话</small></div>
        <div><span><Database size={15} />文档健康</span><strong>{loading ? '—' : `${(documentHealth * 100).toFixed(1)}%`}</strong><small>{data?.healthy_document_count ?? 0}/{data?.document_count ?? 0} 个文档</small></div>
        <div className="ru-kpi-drilldown"><span><Search size={15} />检索调用</span><strong>{data?.search_count ?? '—'}</strong><small>平均 {data?.average_search_ms ?? '—'} ms</small><button type="button" title="查看检索运行分析" aria-label="查看检索运行分析" onClick={() => navigate('/enterprise/search-analytics')}><ArrowRight size={14} /></button></div>
        <div><span><AlertTriangle size={15} />失败任务</span><strong>{data?.failed_count ?? '—'}</strong><small>等待补充 {data?.waiting_count ?? 0}</small></div>
      </section>
      <div className="ru-overview-grid">
        <section className="ru-console-panel ru-activity-chart"><header><strong>会话状态分布</strong><span>最新状态</span></header><div className="ru-bar-stack"><i style={{ width: statusWidth(data?.completed_count) }} /><i style={{ width: statusWidth(data?.failed_count) }} /><i style={{ width: statusWidth(data?.waiting_count) }} /><i style={{ width: statusWidth(data?.running_count) }} /></div><div className="ru-chart-legend"><span><b className="is-green" />完成 {data?.completed_count ?? 0}</span><span><b className="is-red" />失败/中断 {data?.failed_count ?? 0}</span><span><b className="is-amber" />等待 {data?.waiting_count ?? 0}</span><span><b className="is-cobalt" />运行 {data?.running_count ?? 0}</span></div></section>
        <section className="ru-console-panel ru-dependency-panel"><header><strong>依赖健康</strong><span>实时探针</span></header>{Object.entries(health).map(([name, ok]) => <div key={name}><span>{name}</span><strong className={ok ? 'is-healthy' : 'is-unhealthy'}>{ok ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}{ok ? '正常' : '异常'}</strong></div>)}</section>
        <section className="ru-console-panel ru-event-panel"><header><strong>最近审计事件</strong><span>{data?.recent_events.length ?? 0} 条</span></header><div className="ru-event-table"><div><span>时间</span><span>操作者</span><span>事件</span><span>结果</span></div>{data?.recent_events.map((event) => <div key={event.id}><time>{new Date(event.occurred_at).toLocaleTimeString('zh-CN')}</time><span>{event.actor_id}</span><strong>{event.action}</strong><span className={`is-${event.outcome}`}>{event.outcome}</span></div>)}</div></section>
        <section className="ru-console-panel ru-todo-panel"><header><strong>今日待办</strong><span>按风险排序</span></header><button type="button"><AlertTriangle size={15} /><span>失败或中断任务</span><strong>{data?.failed_count ?? 0}</strong></button><button type="button"><Clock3 size={15} /><span>等待人工补充</span><strong>{data?.waiting_count ?? 0}</strong></button><button type="button"><Activity size={15} /><span>未健康依赖</span><strong>{Object.values(health).filter((ok) => !ok).length}</strong></button></section>
      </div>
    </div>
  );
}
