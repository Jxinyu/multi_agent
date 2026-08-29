import { ChevronDown, Filter, RefreshCw, Search, ShieldAlert, ShieldCheck } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { fetchAuditEvents, type AuditEvent } from '../../api/platform';

export function AdminSecurityPage() {
  const [items, setItems] = useState<AuditEvent[]>([]);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [outcome, setOutcome] = useState('');
  const [actor, setActor] = useState('');
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState('');
  const load = async (append = false) => {
    setError('');
    try { const result = await fetchAuditEvents({ outcome, actor: actor.trim(), cursor: append ? cursor ?? undefined : undefined }); setItems((old) => append ? [...old, ...result.items] : result.items); setCursor(result.next_cursor); setSelected((current) => append ? current : result.items[0] ?? null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '审计事件加载失败'); }
  };
  useEffect(() => { void load(); }, []);
  const counts = useMemo(() => ({ failure: items.filter((item) => item.outcome === 'failure').length, denied: items.filter((item) => item.outcome === 'denied').length, success: items.filter((item) => item.outcome === 'success').length }), [items]);

  return <div className="ru-admin-page"><header className="ru-admin-title"><div><h1>安全审计</h1><p>租户隔离的审计流、请求标识和操作上下文。</p></div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button></header>{error ? <div className="ru-inline-error">{error}</div> : null}<section className="ru-admin-kpis"><div><ShieldAlert /><span>失败<strong>{counts.failure}</strong></span></div><div><ShieldAlert /><span>拒绝<strong>{counts.denied}</strong></span></div><div><ShieldCheck /><span>成功<strong>{counts.success}</strong></span></div><div><Filter /><span>当前窗口<strong>{items.length}</strong></span></div></section><section className="ru-audit-filters"><label><Search size={15} /><input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="操作者 ID" /></label><select value={outcome} onChange={(event) => setOutcome(event.target.value)}><option value="">全部结果</option><option value="success">成功</option><option value="failure">失败</option><option value="denied">拒绝</option></select><button type="button" onClick={() => void load()}><Filter size={15} />应用筛选</button></section><div className="ru-admin-split"><section className="ru-admin-panel ru-audit-table"><header><strong>实时审计事件</strong><span>{items.length} 条</span></header><div className="ru-audit-head"><span>时间</span><span>结果</span><span>操作者</span><span>操作</span><span>资源</span></div>{items.map((item) => <button type="button" key={item.id} className={selected?.id === item.id ? 'is-selected' : ''} onClick={() => setSelected(item)}><time>{new Date(item.occurred_at).toLocaleString('zh-CN')}</time><em className={`is-${item.outcome}`}>{item.outcome}</em><span>{item.actor_id}</span><strong>{item.action}</strong><span>{item.resource_type}</span></button>)}{cursor ? <button className="ru-load-more" type="button" onClick={() => void load(true)}><ChevronDown size={15} />加载更早事件</button> : null}</section><aside className="ru-admin-panel ru-audit-detail"><header><ShieldCheck size={17} /><strong>事件检查器</strong></header>{selected ? <><dl><div><dt>事件 ID</dt><dd>{selected.id}</dd></div><div><dt>请求 ID</dt><dd>{selected.request_id ?? '未记录'}</dd></div><div><dt>租户</dt><dd>{selected.tenant_id}</dd></div><div><dt>来源</dt><dd>{selected.source}</dd></div><div><dt>资源 ID</dt><dd>{selected.resource_id ?? '无'}</dd></div></dl><h3>事件元数据</h3><pre>{JSON.stringify(selected.metadata, null, 2)}</pre></> : <p>选择事件查看详情。</p>}</aside></div></div>;
}
