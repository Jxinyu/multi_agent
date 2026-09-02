import { Activity, AlertCircle, ArrowLeft, CheckCircle2, Clock3, RefreshCw, Server, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchServiceProbeDetail, type ServiceProbeDetail } from '../../api/platform';

export function AdminServiceDetailPage() {
  const { serviceName = '' } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ServiceProbeDetail | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const load = async () => {
    setBusy(true);
    setError('');
    try { setDetail(await fetchServiceProbeDetail(serviceName)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '服务探针加载失败'); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, [serviceName]);

  if (busy && !detail) return <div className="ru-admin-page"><div className="ru-admin-detail-state"><RefreshCw className="is-spinning" /><strong>正在执行服务探针</strong></div></div>;
  if (error || !detail) return <div className="ru-admin-page"><div className="ru-admin-detail-state is-error"><AlertCircle /><strong>无法执行服务探针</strong><span>{error || '探针不存在'}</span><button type="button" onClick={() => void load()}>重试</button></div></div>;
  const statusLabel = detail.service.ok ? '探针正常' : '探针异常';

  return <div className="ru-admin-page">
    <header className="ru-admin-title ru-admin-detail-title"><button type="button" onClick={() => navigate('/admin/operations')}><ArrowLeft size={16} />返回运行</button><div><h1>服务探针详情</h1><p>{detail.service.name}</p></div><button type="button" onClick={() => void load()} disabled={busy}><RefreshCw className={busy ? 'is-spinning' : ''} size={16} />重新探测</button></header>
    <section className={`ru-service-detail-hero${detail.service.ok ? ' is-ok' : ' is-bad'}`}><span>{detail.service.ok ? <CheckCircle2 size={25} /> : <AlertCircle size={25} />}</span><div><small>实时健康检查</small><h2>{detail.service.name}</h2><p>{detail.operational_role}</p></div><strong>{statusLabel}</strong></section>
    <div className="ru-service-detail-grid"><section className="ru-admin-panel"><header><strong><Activity size={16} />探针契约</strong><span>发布代码</span></header><dl><div><dt>检查方法</dt><dd>{detail.method}</dd></div><div><dt>成功条件</dt><dd>{detail.success_condition}</dd></div><div><dt>超时上限</dt><dd>{detail.timeout_seconds} 秒</dd></div><div><dt>配置来源</dt><dd>{detail.configuration_source}</dd></div></dl></section><section className="ru-admin-panel ru-service-result"><header><strong><Server size={16} />本次结果</strong><span>{statusLabel}</span></header><pre>{detail.service.detail}</pre><p><Clock3 size={14} />{new Date(detail.checked_at).toLocaleString('zh-CN')}</p></section></div>
    <div className="ru-admin-notice"><ShieldCheck size={17} /><span><strong>{detail.history_available ? '已接入历史监控' : '未接入时序历史'}</strong>当前页面展示一次实时探测结果，不推断可用率、SLA 或故障持续时间。</span></div>
  </div>;
}
