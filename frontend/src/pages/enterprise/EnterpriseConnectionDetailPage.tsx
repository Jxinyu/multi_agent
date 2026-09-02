import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Bot,
  CheckCircle2,
  CircleSlash2,
  Clock3,
  FileKey2,
  Network,
  PlugZap,
  RefreshCw,
  Route,
  ShieldCheck,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchRuntimeConnectionDetail, type RuntimeConnectionDetail } from '../../api/enterprise';

const healthMeta = {
  healthy: { label: '探针正常', className: 'is-healthy', Icon: CheckCircle2 },
  unhealthy: { label: '探针异常', className: 'is-unhealthy', Icon: AlertTriangle },
  unconfigured: { label: '未配置', className: 'is-muted', Icon: CircleSlash2 },
};

export function EnterpriseConnectionDetailPage() {
  const navigate = useNavigate();
  const { connectionId = '' } = useParams();
  const [detail, setDetail] = useState<RuntimeConnectionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      setDetail(await fetchRuntimeConnectionDetail(connectionId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'MCP 连接详情加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [connectionId]);

  if (loading && !detail) {
    return <div className="ru-enterprise-page"><div className="ru-detail-loading"><RefreshCw className="is-spinning" /><strong>正在执行连接探针</strong></div></div>;
  }
  if (error || !detail) {
    return <div className="ru-enterprise-page"><div className="ru-detail-error"><CircleSlash2 /><strong>无法打开 MCP 连接</strong><span>{error || '连接不存在'}</span><button type="button" onClick={() => void load()}>重试</button></div></div>;
  }

  const meta = healthMeta[detail.health];
  const StatusIcon = meta.Icon;
  return (
    <div className="ru-enterprise-page ru-connection-detail-page">
      <header className="ru-console-title ru-detail-title">
        <button type="button" title="返回智能体编排" aria-label="返回智能体编排" onClick={() => navigate('/enterprise/agents')}>
          <ArrowLeft size={17} />
        </button>
        <div><h1>MCP 连接详情</h1><p>核对发布配置、实时可达性和受影响智能体。</p></div>
        <button type="button" disabled={loading} onClick={() => void load()}><RefreshCw className={loading ? 'is-spinning' : ''} size={16} />重新探测</button>
      </header>

      <section className="ru-connection-detail-hero">
        <div className="ru-connection-emblem"><PlugZap size={29} /></div>
        <div><span>只读发布连接</span><h2>{detail.label}</h2><code>{detail.id}</code></div>
        <strong className={meta.className}><StatusIcon size={17} />{meta.label}</strong>
      </section>

      <section className="ru-connection-kpis" aria-label="MCP 连接摘要">
        <div><Network /><span>配置状态<strong>{detail.configured ? '已配置' : '未配置'}</strong><small>{detail.configuration_source}</small></span></div>
        <div><Route /><span>传输协议<strong>{detail.transport}</strong><small>{detail.probe_method}</small></span></div>
        <div><Clock3 /><span>本次延迟<strong>{detail.latency_ms === null ? '—' : `${detail.latency_ms} ms`}</strong><small>{detail.http_status === null ? '无 HTTP 状态' : `HTTP ${detail.http_status}`}</small></span></div>
        <div><Bot /><span>影响智能体<strong>{detail.affected_agents.length}</strong><small>来自当前发布目录</small></span></div>
      </section>

      {detail.health !== 'healthy' ? <div className={`ru-connection-alert is-${detail.health}`}><StatusIcon size={17} /><span><strong>{meta.label}</strong>{detail.probe_message}</span></div> : null}

      <div className="ru-connection-detail-grid">
        <section className="ru-console-panel ru-connection-probe">
          <header><strong><Network size={16} />连接与探针</strong><span>即时读取</span></header>
          <dl>
            <div><dt>端点提示</dt><dd>{detail.endpoint_hint}</dd></div>
            <div><dt>探针方法</dt><dd>{detail.probe_method}</dd></div>
            <div><dt>成功条件</dt><dd>{detail.success_condition}</dd></div>
            <div><dt>本次结果</dt><dd>{detail.probe_message}</dd></div>
            <div><dt>探测时间</dt><dd>{new Date(detail.checked_at).toLocaleString('zh-CN')}</dd></div>
          </dl>
        </section>

        <section className="ru-console-panel ru-connection-capabilities">
          <header><strong><PlugZap size={16} />连接能力</strong><span>{detail.capabilities.length} 项</span></header>
          {detail.capabilities.map((capability, index) => <div key={capability}><span>{String(index + 1).padStart(2, '0')}</span><strong>{capability}</strong></div>)}
        </section>

        <section className="ru-console-panel ru-connection-agents">
          <header><strong><Bot size={16} />受影响智能体</strong><span>{detail.affected_agents.length} 个</span></header>
          {detail.affected_agents.map((agent) => <button type="button" key={agent.id} onClick={() => navigate(`/enterprise/agents/${agent.id}`)}><Bot size={15} /><span><strong>{agent.label}</strong><small>{agent.id}</small></span><ArrowRight size={14} /></button>)}
          {!detail.affected_agents.length ? <p>当前发布目录没有智能体使用此连接。</p> : null}
        </section>

        <section className="ru-console-panel ru-connection-boundary">
          <header><strong><ShieldCheck size={16} />运行边界</strong><span>安全与运维</span></header>
          <div><FileKey2 size={16} /><span><strong>凭据策略</strong>{detail.credential_policy}</span></div>
          <div><Clock3 size={16} /><span><strong>历史状态</strong>{detail.history_available ? '已接入时序记录' : '未接入时序记录，本页只代表当前探针'}</span></div>
          <div><CircleSlash2 size={16} /><span><strong>在线修改</strong>{detail.mutable ? '已启用' : '未启用，连接由启动配置发布'}</span></div>
        </section>
      </div>
    </div>
  );
}
