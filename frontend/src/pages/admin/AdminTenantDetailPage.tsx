import { AlertCircle, ArrowLeft, Building2, FileText, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchTenantDetail, type TenantDetail } from '../../api/platform';

function Distribution({ title, items }: { title: string; items: { id: string; count: number }[] }) {
  const maximum = Math.max(1, ...items.map((item) => item.count));
  return <section className="ru-admin-panel ru-admin-distribution"><header><strong>{title}</strong><span>{items.length} 项</span></header><div>{items.length ? items.map((item) => <div key={item.id}><span>{item.id}</span><i><b style={{ width: `${(item.count / maximum) * 100}%` }} /></i><strong>{item.count}</strong></div>) : <p>当前没有可统计数据。</p>}</div></section>;
}

export function AdminTenantDetailPage() {
  const { tenantId = '' } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<TenantDetail | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const load = async () => {
    setBusy(true);
    setError('');
    try { setDetail(await fetchTenantDetail(tenantId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '租户详情加载失败'); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, [tenantId]);

  if (busy && !detail) return <div className="ru-admin-page"><div className="ru-admin-detail-state"><RefreshCw className="is-spinning" /><strong>正在汇总租户数据</strong></div></div>;
  if (error || !detail) return <div className="ru-admin-page"><div className="ru-admin-detail-state is-error"><AlertCircle /><strong>无法打开租户详情</strong><span>{error || '租户不存在'}</span><button type="button" onClick={() => void load()}>重试</button></div></div>;
  const { usage } = detail;

  return <div className="ru-admin-page">
    <header className="ru-admin-title ru-admin-detail-title"><button type="button" onClick={() => navigate('/admin/tenants')}><ArrowLeft size={16} />返回租户</button><div><h1>租户运行详情</h1><p>{usage.tenant_id}</p></div><button type="button" onClick={() => void load()} disabled={busy}><RefreshCw className={busy ? 'is-spinning' : ''} size={16} />刷新</button></header>
    <section className="ru-tenant-detail-hero"><span><Building2 size={24} /></span><div><small>当前令牌租户</small><h2>{usage.tenant_id}</h2><p>{usage.auth_mode} 认证 · {usage.status === 'active' ? '活跃' : usage.status}</p></div><strong><ShieldCheck size={16} />租户作用域</strong></section>
    <section className="ru-admin-kpis"><div><Users /><span>已观测身份<strong>{usage.observed_users}</strong></span></div><div><FileText /><span>文档<strong>{usage.healthy_document_count}/{usage.document_count}</strong></span></div><div><ShieldCheck /><span>审计窗口<strong>{detail.audit_window_size}</strong></span></div><div><RefreshCw /><span>窗口完整性<strong>{detail.audit_window_complete ? '完整' : '截断'}</strong></span></div></section>
    <div className="ru-admin-notice"><AlertCircle size={17} /><span><strong>{detail.registry_available ? '租户目录已连接' : '跨租户目录未接入'}</strong>{detail.enforcement_note}</span></div>
    <div className="ru-tenant-analysis-grid"><Distribution title="文档状态" items={detail.document_statuses} /><Distribution title="解析路由" items={detail.parsing_modes} /><Distribution title="审计结果" items={detail.audit_outcomes} /><Distribution title="高频操作" items={detail.frequent_actions} /></div>
    <div className="ru-tenant-activity-grid"><section className="ru-admin-panel ru-tenant-recent"><header><strong>最近文档</strong><span>{detail.recent_documents.length} 条</span></header>{detail.recent_documents.length ? detail.recent_documents.map((item) => <div key={item.id}><FileText size={15} /><span><strong>{item.file_name}</strong><small>{item.owner_id} · {item.mode}</small></span><em>{item.status}</em></div>) : <p>当前租户没有文档。</p>}</section><section className="ru-admin-panel ru-tenant-recent"><header><strong>最近审计事件</strong><span>{detail.recent_events.length} 条</span></header>{detail.recent_events.length ? detail.recent_events.map((item) => <button type="button" key={item.id} onClick={() => navigate(`/admin/security/${item.id}`)}><ShieldCheck size={15} /><span><strong>{item.action}</strong><small>{item.actor_id} · {new Date(item.occurred_at).toLocaleString('zh-CN')}</small></span><em className={`is-${item.outcome}`}>{item.outcome}</em></button>) : <p>当前审计窗口为空。</p>}</section></div>
  </div>;
}
