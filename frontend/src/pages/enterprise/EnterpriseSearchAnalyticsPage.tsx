import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  DatabaseZap,
  RefreshCw,
  Search,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchSearchAnalytics, type SearchAnalytics } from '../../api/enterprise';

const modeLabels: Record<string, string> = {
  milvus: '向量检索',
  graph: '图谱检索',
  mg: '混合检索',
};

function percentage(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function width(value: number, maximum: number): string {
  return value > 0 && maximum > 0 ? `${Math.max(4, value / maximum * 100)}%` : '0%';
}

function DistributionRows({
  items,
  total,
  emptyText,
  danger = false,
}: {
  items: { id: string; count: number }[];
  total: number;
  emptyText: string;
  danger?: boolean;
}) {
  const maximum = Math.max(...items.map((item) => item.count), 0);
  if (!items.length) return <div className="ru-search-analytics-empty">{emptyText}</div>;
  return <div className={`ru-search-distribution${danger ? ' is-danger' : ''}`}>{items.map((item, index) => (
    <div key={item.id}>
      <i className={`is-series-${index % 4}`} />
      <span>{modeLabels[item.id] ?? item.id}</span>
      <b><em className={`is-series-${index % 4}`} style={{ width: width(item.count, maximum) }} /></b>
      <strong>{item.count}</strong>
      <small>{total ? `${(item.count / total * 100).toFixed(1)}%` : '—'}</small>
    </div>
  ))}</div>;
}

export function EnterpriseSearchAnalyticsPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<SearchAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      setData(await fetchSearchAnalytics());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '检索运行数据加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);
  const latencyRows = useMemo(() => data ? [
    { label: '平均值', value: data.latency.average_ms },
    { label: 'P50', value: data.latency.p50_ms },
    { label: 'P95', value: data.latency.p95_ms },
    { label: '最大值', value: data.latency.maximum_ms },
  ] : [], [data]);
  const latencyMaximum = Math.max(...latencyRows.map((item) => item.value ?? 0), 0);

  return <div className="ru-enterprise-page ru-search-analytics-page">
    <header className="ru-console-title ru-detail-title">
      <button type="button" title="返回企业总览" aria-label="返回企业总览" onClick={() => navigate('/enterprise')}><ArrowLeft size={17} /></button>
      <div><h1>检索运行分析</h1><p>按租户审计事件核对检索结果、延迟和失败分布。</p></div>
      <button type="button" disabled={loading} onClick={() => void load()}><RefreshCw className={loading ? 'is-spinning' : ''} size={16} />重新统计</button>
    </header>

    {error ? <div className="ru-detail-error"><AlertTriangle size={20} /><strong>运行数据读取失败</strong><span>{error}</span><button type="button" onClick={() => void load()}>重新读取</button></div> : null}
    {loading && !data ? <div className="ru-detail-loading"><RefreshCw className="is-spinning" size={18} />正在聚合租户检索事件</div> : null}

    {data ? <>
      <section className="ru-search-analytics-kpis" aria-label="检索运行摘要">
        <div><Search /><span>检索事件<strong>{data.search_event_count}</strong><small>审计窗口内成功与失败</small></span></div>
        <div><CheckCircle2 /><span>成功率<strong>{percentage(data.success_rate)}</strong><small>{data.completed_count}/{data.search_event_count} 条事件</small></span></div>
        <div><Clock3 /><span>P95 延迟<strong>{data.latency.p95_ms === null ? '—' : `${data.latency.p95_ms} ms`}</strong><small>{data.latency.sample_count} 条有效耗时</small></span></div>
        <div><DatabaseZap /><span>零命中率<strong>{percentage(data.results.zero_result_rate)}</strong><small>{data.results.zero_result_count}/{data.results.sample_count} 条有效结果</small></span></div>
      </section>

      <div className="ru-search-analytics-grid">
        <section className="ru-console-panel ru-search-latency-panel">
          <header><strong>成功检索延迟</strong><span>毫秒 · 最近样本</span></header>
          {data.latency.sample_count ? <div className="ru-search-latency-rows">{latencyRows.map((item) => <div key={item.label}>
            <span>{item.label}</span><strong>{item.value ?? '—'}</strong><i><b style={{ width: width(item.value ?? 0, latencyMaximum) }} /></i><small>ms</small>
          </div>)}</div> : <div className="ru-search-analytics-empty">窗口内没有有效耗时样本</div>}
        </section>

        <section className="ru-console-panel ru-search-outcome-panel">
          <header><strong>检索结果</strong><span>按事件数</span></header>
          <div className="ru-search-outcomes">
            <div><CheckCircle2 /><span>成功<strong>{data.completed_count}</strong></span><i><b style={{ width: width(data.completed_count, data.search_event_count) }} /></i><small>{percentage(data.success_rate)}</small></div>
            <div className="is-failure"><XCircle /><span>失败<strong>{data.failed_count}</strong></span><i><b style={{ width: width(data.failed_count, data.search_event_count) }} /></i><small>{data.search_event_count ? `${(data.failed_count / data.search_event_count * 100).toFixed(1)}%` : '—'}</small></div>
          </div>
        </section>

        <section className="ru-console-panel ru-search-mode-panel">
          <header><strong>检索模式分布</strong><span>有记录的模式</span></header>
          <DistributionRows items={data.modes} total={data.modes.reduce((sum, item) => sum + item.count, 0)} emptyText="窗口内没有模式记录" />
        </section>
      </div>

      <div className="ru-search-event-layout">
        <section className="ru-console-panel ru-search-events-panel">
          <header><strong>最近检索事件</strong><span>{data.recent_events.length} 条可见</span></header>
          <div className="ru-search-event-head"><span>时间</span><span>操作者</span><span>模式</span><span>结果</span><span>延迟</span><span>命中数</span><span /></div>
          {data.recent_events.map((event) => <button key={event.id} type="button" onClick={() => navigate(`/enterprise/activity/${event.id}`)}>
            <time>{new Date(event.occurred_at).toLocaleString('zh-CN')}</time>
            <span>{event.actor_id}</span>
            <span>{event.mode ? modeLabels[event.mode] ?? event.mode : '未记录'}</span>
            <em className={`is-${event.outcome}`}>{event.outcome === 'success' ? '成功' : '失败'}</em>
            <span>{event.elapsed_ms === null ? '未记录' : `${event.elapsed_ms} ms`}</span>
            <span>{event.result_count ?? '未记录'}</span>
            <ArrowRight size={14} />
          </button>)}
          {!data.recent_events.length ? <div className="ru-data-empty"><Search size={28} /><strong>当前窗口没有检索事件</strong><span>执行真实检索后，成功或失败记录会出现在这里。</span></div> : null}
        </section>

        <section className="ru-console-panel ru-search-errors-panel">
          <header><strong>失败类型</strong><span>按失败事件数</span></header>
          <DistributionRows items={data.error_types} total={data.failed_count} emptyText="窗口内没有已记录失败类型" danger />
          <p><AlertTriangle size={14} />失败事件当前不记录完整耗时，因此不会混入成功延迟统计。</p>
        </section>
      </div>

      <footer className="ru-search-window-note">
        <div><ShieldCheck size={17} /><span><strong>{data.data_window}</strong>实际读取 {data.audit_window_size} 条，{data.audit_window_complete ? '窗口完整' : '仍有更早事件未纳入'}；指标仅代表本次窗口。</span></div>
        <div><ShieldCheck size={17} /><span><strong>查询隐私</strong>{data.privacy_note}</span></div>
        <time>统计于 {new Date(data.checked_at).toLocaleString('zh-CN')}</time>
      </footer>
    </> : null}
  </div>;
}
