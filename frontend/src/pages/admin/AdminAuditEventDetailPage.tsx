import { Activity, ArrowLeft, CheckCircle2, CircleSlash2, Copy, FileSearch, RefreshCw, ShieldAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchAuditEventDetail, type AuditEventDetail } from '../../api/platform';

interface AdminAuditEventDetailPageProps {
  mode?: 'admin' | 'enterprise';
}

export function AdminAuditEventDetailPage({ mode = 'admin' }: AdminAuditEventDetailPageProps) {
  const navigate = useNavigate();
  const { eventId = '' } = useParams();
  const [detail, setDetail] = useState<AuditEventDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const load = async () => {
    setLoading(true);
    setError('');
    try { setDetail(await fetchAuditEventDetail(eventId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '审计事件加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [eventId]);

  const pageClass = mode === 'enterprise' ? 'ru-enterprise-page' : 'ru-admin-page';
  const backPath = mode === 'enterprise' ? '/enterprise/activity' : '/admin/security';
  const titleClass = mode === 'enterprise' ? 'ru-console-title ru-admin-detail-title' : 'ru-admin-title ru-admin-detail-title';
  if (loading) return <div className={pageClass}><div className="ru-admin-detail-state"><RefreshCw className="ru-spin" /><strong>正在读取审计事件与请求链</strong></div></div>;
  if (error || !detail) return <div className={pageClass}><div className="ru-admin-detail-state is-error"><CircleSlash2 /><strong>无法打开审计事件</strong><span>{error || '事件不存在'}</span><button type="button" onClick={() => void load()}>重试</button></div></div>;
  const item = detail.item;

  const copyTrace = async () => {
    if (!item.request_id) return;
    await navigator.clipboard.writeText(item.request_id);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  return <div className={`${pageClass} ru-audit-event-page`}>
    <header className={titleClass}><button type="button" onClick={() => navigate(backPath)}><ArrowLeft size={16} />{mode === 'enterprise' ? '返回活动' : '返回审计'}</button><div><h1>{mode === 'enterprise' ? '租户活动详情' : '审计事件详情'}</h1><p>{item.id}</p></div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button></header>

    <section className={`ru-audit-event-hero is-${item.outcome}`}><span>{item.outcome === 'success' ? <CheckCircle2 size={28} /> : <ShieldAlert size={28} />}</span><div><small>{new Date(item.occurred_at).toLocaleString('zh-CN')}</small><h2>{item.action}</h2><p>{item.actor_id} · {item.source} · {item.actor_type}</p></div><strong>{item.outcome}</strong></section>

    <div className="ru-audit-event-grid">
      <section className="ru-admin-panel ru-audit-event-fields"><header><strong><FileSearch size={16} />事件上下文</strong><span>租户作用域</span></header><dl><div><dt>事件 ID</dt><dd>{item.id}</dd></div><div><dt>租户</dt><dd>{item.tenant_id}</dd></div><div><dt>操作者</dt><dd>{item.actor_id}</dd></div><div><dt>资源类型</dt><dd>{item.resource_type}</dd></div><div><dt>资源 ID</dt><dd>{item.resource_id ?? '未记录'}</dd></div><div><dt>请求 ID</dt><dd>{item.request_id ?? '未记录'}</dd></div></dl>{item.request_id ? <button type="button" onClick={() => void copyTrace()}><Copy size={15} />{copied ? '已复制' : '复制请求 ID'}</button> : null}</section>
      <section className="ru-admin-panel ru-audit-event-metadata"><header><strong>事件元数据</strong><span>{Object.keys(item.metadata).length} 个字段</span></header>{Object.keys(item.metadata).length ? <pre>{JSON.stringify(item.metadata, null, 2)}</pre> : <p>该事件没有附加元数据。</p>}</section>
      <section className="ru-admin-panel ru-audit-trace"><header><strong><Activity size={16} />同一请求链</strong><span>{detail.related_events.length} 个事件</span></header>{detail.related_events.map((event, index) => <div key={event.id} className={event.id === item.id ? 'is-current' : ''}><span>{index + 1}</span><time>{new Date(event.occurred_at).toLocaleTimeString('zh-CN')}</time><strong>{event.action}</strong><em className={`is-${event.outcome}`}>{event.outcome}</em><small>{event.resource_type}{event.resource_id ? ` · ${event.resource_id}` : ''}</small></div>)}{!detail.trace_complete ? <p className="ru-trace-limit">请求链超过 50 个事件，当前仅展示前 50 个。</p> : null}</section>
    </div>
  </div>;
}
