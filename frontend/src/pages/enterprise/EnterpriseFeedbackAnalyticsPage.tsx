import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  Users,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchFeedbackAnalytics, type FeedbackAnalytics } from '../../api/enterprise';

type FeedbackRecord = FeedbackAnalytics['recent_feedback'][number];
type Filter = 'all' | FeedbackRecord['rating'];

const ratingLabels: Record<FeedbackRecord['rating'], string> = {
  helpful: '有帮助',
  not_helpful: '无帮助',
};

const statusLabels: Record<FeedbackRecord['conversation_status'], string> = {
  running: '运行中',
  waiting: '等待补充',
  completed: '已完成',
  failed: '失败',
  cancelled: '已中断',
};

function percentage(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function barWidth(value: number, total: number): string {
  return value > 0 && total > 0 ? `${Math.max(4, value / total * 100)}%` : '0%';
}

function distributionTone(id: string, index: number): string {
  if (id === 'helpful') return 'is-helpful';
  if (id === 'not_helpful') return 'is-not-helpful';
  return `is-series-${index % 4}`;
}

function Distribution({
  title,
  items,
  total,
  labels,
}: {
  title: string;
  items: { id: string; count: number }[];
  total: number;
  labels: Record<string, string>;
}) {
  return <section className="ru-console-panel ru-feedback-distribution">
    <header><strong>{title}</strong><span>当前反馈快照</span></header>
    {items.length ? items.map((item, index) => <div key={item.id}>
      <i className={distributionTone(item.id, index)} />
      <span>{labels[item.id] ?? item.id}</span>
      <b><em className={distributionTone(item.id, index)} style={{ width: barWidth(item.count, total) }} /></b>
      <strong>{item.count}</strong>
      <small>{total ? `${(item.count / total * 100).toFixed(1)}%` : '—'}</small>
    </div>) : <p>当前窗口没有可分布的记录。</p>}
  </section>;
}

export function EnterpriseFeedbackAnalyticsPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<FeedbackAnalytics | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await fetchFeedbackAnalytics();
      setData(result);
      setSelectedId((current) => result.recent_feedback.some((item) => item.id === current)
        ? current
        : result.recent_feedback[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '反馈运行数据加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);
  const visible = useMemo(
    () => data?.recent_feedback.filter((item) => filter === 'all' || item.rating === filter) ?? [],
    [data, filter],
  );
  const selected = data?.recent_feedback.find((item) => item.id === selectedId) ?? null;
  const chooseFilter = (next: Filter) => {
    setFilter(next);
    const firstMatch = data?.recent_feedback.find((item) => next === 'all' || item.rating === next);
    setSelectedId(firstMatch?.id ?? null);
  };
  const openAudit = (record: FeedbackRecord) => {
    const query = new URLSearchParams({ actor: record.respondent_id, action: 'chat.feedback' });
    navigate(`/enterprise/activity?${query.toString()}`);
  };

  return <div className="ru-enterprise-page ru-feedback-page">
    <header className="ru-console-title ru-detail-title">
      <button type="button" title="返回评测与成本" aria-label="返回评测与成本" onClick={() => navigate('/enterprise/evaluation')}><ArrowLeft size={17} /></button>
      <div><h1>用户反馈分析</h1><p>按租户会话反馈记录核对当前评分、响应者和会话状态。</p></div>
      <button type="button" disabled={loading} onClick={() => void load()}><RefreshCw className={loading ? 'is-spinning' : ''} size={16} />重新统计</button>
    </header>

    {error ? <div className="ru-detail-error"><AlertTriangle size={20} /><strong>反馈数据读取失败</strong><span>{error}</span><button type="button" onClick={() => void load()}>重新读取</button></div> : null}
    {loading && !data ? <div className="ru-detail-loading"><RefreshCw className="is-spinning" size={18} />正在读取当前租户反馈</div> : null}

    {data ? <>
      <section className="ru-feedback-kpis" aria-label="反馈摘要">
        <div><MessageSquareText /><span>反馈记录<strong>{data.feedback_count}</strong><small>{data.data_window}</small></span></div>
        <div><CheckCircle2 /><span>有帮助率<strong>{percentage(data.helpful_rate)}</strong><small>{data.feedback_count} 条有效二元反馈</small></span></div>
        <div><ThumbsUp /><span>有帮助<strong>{data.helpful_count}</strong><small>当前记录值</small></span></div>
        <div><ThumbsDown /><span>无帮助<strong>{data.not_helpful_count}</strong><small>当前记录值</small></span></div>
      </section>

      <div className="ru-feedback-overview-grid">
        <Distribution title="反馈结果分布" items={data.ratings} total={data.feedback_count} labels={ratingLabels} />
        <Distribution title="会话状态分布" items={data.conversation_statuses} total={data.feedback_count} labels={statusLabels} />
        <section className="ru-console-panel ru-feedback-respondents">
          <header><strong>反馈人观察</strong><span>窗口内去重</span></header>
          <dl>
            <div><dt>反馈人数</dt><dd>{data.respondent_count}</dd></div>
            <div><dt>人均记录</dt><dd>{data.average_per_respondent ?? '—'}</dd></div>
            <div><dt>窗口状态</dt><dd>{data.window_complete ? '完整' : '已截断'}</dd></div>
            <div><dt>租户范围</dt><dd>{data.tenant_id}</dd></div>
          </dl>
        </section>
      </div>

      <div className="ru-feedback-filters" aria-label="反馈结果筛选">
        {(['all', 'helpful', 'not_helpful'] as Filter[]).map((item) => <button className={filter === item ? 'is-active' : ''} key={item} type="button" onClick={() => chooseFilter(item)}>{item === 'all' ? '全部' : ratingLabels[item]}</button>)}
        <span>显示 {visible.length}/{data.feedback_count} 条</span>
      </div>

      <div className="ru-feedback-layout">
        <section className="ru-console-panel ru-feedback-table">
          <header><strong>最近反馈记录</strong><span>按更新时间倒序</span></header>
          <div className="ru-feedback-head"><span>更新时间</span><span>反馈人</span><span>会话 ID</span><span>会话状态</span><span>反馈结果</span><span /></div>
          {visible.map((item) => <button className={selected?.id === item.id ? 'is-selected' : ''} key={item.id} type="button" onClick={() => setSelectedId(item.id)}>
            <time>{new Date(item.updated_at).toLocaleString('zh-CN')}</time>
            <span>{item.respondent_id}</span>
            <code>{item.conversation_id}</code>
            <span>{statusLabels[item.conversation_status]}</span>
            <em className={`is-${item.rating}`}>{item.rating === 'helpful' ? <ThumbsUp size={13} /> : <ThumbsDown size={13} />}{ratingLabels[item.rating]}</em>
            <i />
          </button>)}
          {!visible.length ? <div className="ru-data-empty"><MessageSquareText size={28} /><strong>{data.feedback_count ? '当前筛选没有记录' : '当前租户还没有反馈'}</strong><span>{data.feedback_count ? '切换反馈结果筛选查看其他记录。' : '用户对真实助手回答提交反馈后会显示在这里。'}</span></div> : null}
        </section>

        <aside className="ru-console-panel ru-feedback-inspector">
          <header><strong>反馈详情</strong><span>只读</span></header>
          {selected ? <>
            <div className={`ru-feedback-rating is-${selected.rating}`}>{selected.rating === 'helpful' ? <ThumbsUp size={18} /> : <ThumbsDown size={18} />}<span><small>反馈结果</small><strong>{ratingLabels[selected.rating]}</strong></span></div>
            <dl>
              <div><dt>反馈记录 ID</dt><dd>{selected.id}</dd></div>
              <div><dt>会话 ID</dt><dd>{selected.conversation_id}</dd></div>
              <div><dt>会话线程 ID</dt><dd>{selected.thread_id}</dd></div>
              <div><dt>反馈人</dt><dd>{selected.respondent_id}</dd></div>
              <div><dt>会话状态</dt><dd>{statusLabels[selected.conversation_status]}</dd></div>
              <div><dt>首次反馈</dt><dd>{new Date(selected.created_at).toLocaleString('zh-CN')}</dd></div>
              <div><dt>最后更新</dt><dd>{new Date(selected.updated_at).toLocaleString('zh-CN')}</dd></div>
            </dl>
            <button type="button" onClick={() => openAudit(selected)}>查看反馈审计 <ArrowRight size={14} /></button>
          </> : <div className="ru-data-empty"><MessageSquareText size={25} /><strong>未选择反馈</strong><span>从左侧记录中选择一项。</span></div>}
        </aside>
      </div>

      <footer className="ru-feedback-note">
        <div><ShieldCheck size={17} /><span><strong>{data.data_window}</strong>窗口{data.window_complete ? '完整' : '已截断，仍有更早记录'}；{data.history_note}</span></div>
        <div><ShieldCheck size={17} /><span><strong>内容隐私</strong>{data.privacy_note}</span></div>
        <time><Clock3 size={14} />统计于 {new Date(data.checked_at).toLocaleString('zh-CN')}</time>
      </footer>
    </> : null}
  </div>;
}
