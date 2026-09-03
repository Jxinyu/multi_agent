import {
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  CircleSlash2,
  Filter,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  X
} from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { fetchAuditEvents, type AuditEvent } from '../../api/platform';

export function EnterpriseActivityPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [outcome, setOutcome] = useState('');
  const [actor, setActor] = useState(() => searchParams.get('actor')?.slice(0, 128) ?? '');
  const [action, setAction] = useState(() => searchParams.get('action')?.slice(0, 128) ?? '');
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async (append = false, clearFilters = false) => {
    setLoading(true);
    setError('');
    const nextActor = clearFilters ? '' : actor.trim();
    const nextAction = clearFilters ? '' : action.trim();
    const nextOutcome = clearFilters ? '' : outcome;
    try {
      const result = await fetchAuditEvents({
        actor: nextActor,
        action: nextAction,
        outcome: nextOutcome,
        cursor: append ? cursor ?? undefined : undefined
      });
      setItems((current) => append ? [...current, ...result.items] : result.items);
      setCursor(result.next_cursor);
      if (!append) setSelected(result.items[0] ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '租户活动加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const counts = useMemo(() => ({
    success: items.filter((item) => item.outcome === 'success').length,
    failure: items.filter((item) => item.outcome === 'failure').length,
    denied: items.filter((item) => item.outcome === 'denied').length
  }), [items]);

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    void load();
  };

  const clearFilters = () => {
    setActor('');
    setAction('');
    setOutcome('');
    void load(false, true);
  };

  return <div className="ru-enterprise-page ru-tenant-audit-page">
    <header className="ru-console-title"><div><h1>租户活动与审计</h1><p>查询当前租户内的成员操作、拒绝事件和请求链上下文。</p></div><button type="button" disabled={loading} onClick={() => void load()}><RefreshCw className={loading ? 'ru-spin' : ''} size={16} />刷新</button></header>

    {error ? <div className="ru-inline-error">{error}</div> : null}

    <section className="ru-admin-kpis ru-tenant-audit-kpis" aria-label="当前审计窗口摘要">
      <div><CheckCircle2 /><span>成功<strong>{counts.success}</strong></span></div>
      <div><ShieldAlert /><span>失败<strong>{counts.failure}</strong></span></div>
      <div><CircleSlash2 /><span>拒绝<strong>{counts.denied}</strong></span></div>
      <div><ShieldCheck /><span>当前窗口<strong>{items.length}</strong></span></div>
    </section>

    <form className="ru-audit-filters ru-tenant-audit-filters" onSubmit={applyFilters}>
      <label><Search size={15} /><input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="操作者 ID" aria-label="按操作者 ID 筛选" /></label>
      <label><Search size={15} /><input value={action} onChange={(event) => setAction(event.target.value)} placeholder="精确操作名" aria-label="按操作名筛选" /></label>
      <select value={outcome} onChange={(event) => setOutcome(event.target.value)} aria-label="按结果筛选"><option value="">全部结果</option><option value="success">成功</option><option value="failure">失败</option><option value="denied">拒绝</option></select>
      <button type="submit" disabled={loading}><Filter size={15} />应用</button>
      <button type="button" disabled={loading || (!actor && !action && !outcome)} onClick={clearFilters}><X size={15} />清除</button>
    </form>

    <div className="ru-admin-split ru-tenant-audit-layout">
      <section className="ru-admin-panel ru-audit-table">
        <header><strong>租户活动流</strong><span>{loading ? '读取中' : `${items.length} 条`}</span></header>
        <div className="ru-audit-head"><span>时间</span><span>结果</span><span>操作者</span><span>操作</span><span>资源</span></div>
        {items.map((item) => <div key={item.id} className={`ru-audit-row${selected?.id === item.id ? ' is-selected' : ''}`}>
          <button type="button" className="ru-audit-row-main" aria-label={`预览活动 ${item.action}`} onClick={() => setSelected(item)}><time>{new Date(item.occurred_at).toLocaleString('zh-CN')}</time><em className={`is-${item.outcome}`}>{item.outcome}</em><span>{item.actor_id}</span><strong>{item.action}</strong><span>{item.resource_type}</span></button>
          <button type="button" className="ru-audit-row-open" aria-label={`打开活动 ${item.action} 的完整详情`} title="打开完整详情" onClick={() => navigate(`/enterprise/activity/${item.id}`)}><ArrowRight size={14} /></button>
        </div>)}
        {!loading && !items.length ? <div className="ru-data-empty"><ShieldCheck size={28} /><strong>当前筛选没有活动</strong><span>调整操作者、操作名或结果后重新查询。</span></div> : null}
        {cursor ? <button className="ru-load-more" type="button" disabled={loading} onClick={() => void load(true)}><ChevronDown size={15} />加载更早事件</button> : null}
      </section>

      <aside className="ru-admin-panel ru-audit-detail">
        <header><ShieldCheck size={17} /><strong>活动检查器</strong></header>
        {selected ? <><dl><div><dt>事件 ID</dt><dd>{selected.id}</dd></div><div><dt>请求 ID</dt><dd>{selected.request_id ?? '未记录'}</dd></div><div><dt>操作者类型</dt><dd>{selected.actor_type}</dd></div><div><dt>来源</dt><dd>{selected.source}</dd></div><div><dt>资源</dt><dd>{selected.resource_type}{selected.resource_id ? ` · ${selected.resource_id}` : ''}</dd></div></dl><h3>事件元数据</h3><pre>{JSON.stringify(selected.metadata, null, 2)}</pre><button type="button" onClick={() => navigate(`/enterprise/activity/${selected.id}`)}>查看请求链 <ArrowRight size={14} /></button></> : <p>选择活动查看上下文。</p>}
      </aside>
    </div>
  </div>;
}
