import { AlertCircle, ArrowRight, Building2, Database, FileText, Gauge, RefreshCw, Users } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchTenantDirectory, type TenantDirectory, type TenantUsage } from '../../api/platform';

const formatBytes = (value: number | null) => value === null ? '未配置' : `${(value / 1024 / 1024).toFixed(0)} MB`;

export function AdminTenantsPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<TenantDirectory | null>(null);
  const [selected, setSelected] = useState<TenantUsage | null>(null);
  const [error, setError] = useState('');
  const load = async () => {
    setError('');
    try { const result = await fetchTenantDirectory(); setData(result); setSelected((current) => current ?? result.items[0] ?? null); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '租户数据加载失败'); }
  };
  useEffect(() => { void load(); }, []);

  return <div className="ru-admin-page">
    <header className="ru-admin-title"><div><h1>租户与资源配额</h1><p>当前部署可观测租户与已执行的全局容量边界。</p></div><div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button><button type="button" disabled title="需要接入平台租户目录与配额执行器"><Building2 size={16} />创建租户</button></div></header>
    {error ? <div className="ru-inline-error">{error}</div> : null}
    <section className="ru-admin-kpis"><div><Building2 /><span>可观测租户<strong>{data?.items.length ?? '—'}</strong></span></div><div><Users /><span>观测用户<strong>{data?.items.reduce((sum, item) => sum + item.observed_users, 0) ?? '—'}</strong></span></div><div><FileText /><span>文档总数<strong>{data?.items.reduce((sum, item) => sum + item.document_count, 0) ?? '—'}</strong></span></div><div><Gauge /><span>请求上限<strong>{selected?.request_limit_per_minute ?? '—'} / 分</strong></span></div></section>
    {!data?.registry_available ? <div className="ru-admin-notice"><AlertCircle size={17} /><span><strong>跨租户控制面未接入</strong>{data?.enforcement_note ?? '正在读取能力状态'}</span></div> : null}
    <div className="ru-admin-split"><section className="ru-admin-panel ru-tenant-table"><header><strong>部署租户</strong><span>{data?.items.length ?? 0} 条</span></header><div className="ru-admin-table-head"><span>租户 ID</span><span>认证</span><span>用户</span><span>文档</span><span>审计事件</span><span>状态</span></div>{data?.items.map((item) => <button type="button" key={item.tenant_id} className={selected?.tenant_id === item.tenant_id ? 'is-selected' : ''} onClick={() => setSelected(item)}><strong><Building2 size={15} />{item.tenant_id}</strong><span>{item.auth_mode}</span><span>{item.observed_users}</span><span>{item.healthy_document_count}/{item.document_count}</span><span>{item.audit_event_count}</span><em>{item.status === 'active' ? '活跃' : item.status}</em></button>)}</section>
      <aside className="ru-admin-panel ru-tenant-detail"><header><Database size={17} /><strong>{selected?.tenant_id ?? '租户详情'}</strong></header><h3>实际执行限制</h3><dl><div><dt>每分钟请求</dt><dd>{selected?.request_limit_per_minute ?? '—'}</dd></div><div><dt>单文件上限</dt><dd>{formatBytes(selected?.max_file_size_bytes ?? null)}</dd></div><div><dt>向量存储配额</dt><dd>{formatBytes(selected?.vector_storage_quota_bytes ?? null)}</dd></div><div><dt>图实体配额</dt><dd>{selected?.graph_entity_quota ?? '未配置'}</dd></div><div><dt>月度 Token 配额</dt><dd>{selected?.monthly_token_quota ?? '未配置'}</dd></div></dl>{selected ? <button type="button" onClick={() => navigate(`/admin/tenants/${encodeURIComponent(selected.tenant_id)}`)}>打开完整详情 <ArrowRight size={14} /></button> : null}<button type="button" disabled title="配额执行器尚未接入">调整配额</button></aside>
    </div>
  </div>;
}
