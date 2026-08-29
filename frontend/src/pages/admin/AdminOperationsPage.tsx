import { Activity, AlertTriangle, CheckCircle2, RefreshCw, Server, Wrench } from 'lucide-react';
import { useEffect, useState } from 'react';

import { fetchDependencyHealth } from '../../api/enterprise';
import { fetchRuntimeStatus, type RuntimeStatus } from '../../api/platform';

export function AdminOperationsPage() {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  const [health, setHealth] = useState<Record<string, boolean>>({});
  const [error, setError] = useState('');
  const load = async () => { setError(''); try { const [status, checks] = await Promise.all([fetchRuntimeStatus(), fetchDependencyHealth()]); setRuntime(status); setHealth(checks); } catch (reason) { setError(reason instanceof Error ? reason.message : '运行状态加载失败'); } };
  useEffect(() => { void load(); }, []);
  const healthy = Object.values(health).filter(Boolean).length;
  return <div className="ru-admin-page"><header className="ru-admin-title"><div><h1>系统运行</h1><p>服务拓扑、依赖探针和后台任务策略。</p></div><div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button><button type="button" disabled title="维护任务与审批审计尚未接入"><Wrench size={16} />维护操作</button></div></header>{error ? <div className="ru-inline-error">{error}</div> : null}<section className="ru-admin-kpis"><div><Server /><span>服务名称<strong>{runtime?.service_name ?? '—'}</strong></span></div><div><Activity /><span>运行环境<strong>{runtime?.environment ?? '—'}</strong></span></div><div><CheckCircle2 /><span>健康探针<strong>{healthy}/{Object.keys(health).length}</strong></span></div><div><AlertTriangle /><span>最大重试<strong>{runtime?.worker_max_attempts ?? '—'}</strong></span></div></section><div className="ru-operations-grid"><section className="ru-admin-panel ru-service-topology"><header><strong>服务拓扑</strong><span>实时状态</span></header><div className="ru-topology-row"><span>客户端</span><i /><span>API 网关</span><i /></div><div className="ru-service-grid">{Object.entries(health).map(([name, ok]) => <article key={name}><Server size={18} /><strong>{name}</strong><span className={ok ? 'is-ok' : 'is-bad'}>{ok ? '正常' : '异常'}</span></article>)}</div></section><section className="ru-admin-panel ru-probe-table"><header><strong>探针详情</strong><span>{runtime?.services.length ?? 0} 项</span></header>{runtime?.services.map((service) => <div key={service.name}><span>{service.ok ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}<strong>{service.name}</strong></span><code>{service.detail}</code><em className={service.ok ? 'is-ok' : 'is-bad'}>{service.ok ? '正常' : '异常'}</em></div>)}</section><section className="ru-admin-panel ru-worker-policy"><header><strong>任务执行策略</strong><span>启动配置</span></header><dl><div><dt>最大尝试次数</dt><dd>{runtime?.worker_max_attempts ?? '—'}</dd></div><div><dt>队列阻塞等待</dt><dd>{runtime?.worker_block_ms ?? '—'} ms</dd></div><div><dt>维护操作</dt><dd>{runtime?.maintenance_operations_enabled ? '已启用' : '未接入'}</dd></div></dl></section></div></div>;
}
