import { ArrowLeft, Bot, CheckCircle2, CircleSlash2, ExternalLink, FileCode2, Network, RefreshCw, ShieldCheck, Wrench } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchDependencyHealth, fetchRuntimeAgentDetail, type RuntimeAgentDetail } from '../../api/enterprise';

export function EnterpriseAgentDetailPage() {
  const navigate = useNavigate();
  const { agentId = '' } = useParams();
  const [detail, setDetail] = useState<RuntimeAgentDetail | null>(null);
  const [health, setHealth] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const agent = await fetchRuntimeAgentDetail(agentId);
      setDetail(agent);
      void fetchDependencyHealth().then(setHealth).catch(() => setHealth({}));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '智能体详情加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [agentId]);

  if (loading) {
    return <div className="ru-enterprise-page"><div className="ru-detail-loading"><RefreshCw className="ru-spin" /><strong>正在读取当前运行清单</strong></div></div>;
  }

  if (error || !detail) {
    return <div className="ru-enterprise-page"><div className="ru-detail-error"><CircleSlash2 /><strong>无法打开智能体详情</strong><span>{error || '智能体不存在'}</span><button type="button" onClick={() => void load()}>重试</button></div></div>;
  }

  return <div className="ru-enterprise-page ru-agent-detail-page">
    <header className="ru-console-title ru-detail-title">
      <button type="button" onClick={() => navigate('/enterprise/agents')}><ArrowLeft size={16} />返回编排</button>
      <div><h1>{detail.label}</h1><p>{detail.description}</p></div>
      <button className="is-primary" type="button" onClick={() => navigate('/app')}><ExternalLink size={16} />进入测试运行</button>
    </header>

    <section className="ru-agent-detail-hero">
      <div className="ru-agent-emblem"><Bot size={32} /></div>
      <div><span>已发布 · 只读运行清单</span><h2>{detail.id.toUpperCase()}</h2><p>{detail.description}</p></div>
      <dl>
        <div><dt>模型</dt><dd>{detail.model_provider} / {detail.model_name}</dd></div>
        <div><dt>输出契约</dt><dd>{detail.output_schema}</dd></div>
        <div><dt>工具调用上限</dt><dd>{detail.tool_call_limit} 次/运行</dd></div>
      </dl>
    </section>

    <div className="ru-agent-detail-grid">
      <section className="ru-console-panel ru-agent-capabilities">
        <header><strong><Wrench size={16} />能力与工具</strong><span>{detail.capabilities.length} 项</span></header>
        {detail.capabilities.map((item, index) => <div key={item}><span>{String(index + 1).padStart(2, '0')}</span><strong>{item}</strong><CheckCircle2 size={15} /></div>)}
      </section>

      <section className="ru-console-panel ru-agent-connections">
        <header><strong><Network size={16} />MCP 连接</strong><span>启动配置</span></header>
        {detail.connections.map((connection) => {
          const probe = connection.id === 'rag' ? health['mcp-rag'] : undefined;
          const state = !connection.configured ? '未配置' : probe === undefined ? '已配置，未独立探测' : probe ? '配置且探针正常' : '配置但探针异常';
          const statusClass = !connection.configured || probe === false ? 'is-unhealthy' : probe === true ? 'is-healthy' : 'is-muted';
          const StatusIcon = !connection.configured || probe === false ? CircleSlash2 : probe === true ? CheckCircle2 : Network;
          return <div key={connection.id}><span className={statusClass}><StatusIcon size={15} /></span><div><strong>{connection.label}</strong><small>{state}</small></div><code>{connection.id}</code></div>;
        })}
      </section>

      <section className="ru-console-panel ru-agent-guardrails">
        <header><strong><ShieldCheck size={16} />回答边界</strong><span>当前提示词策略</span></header>
        {detail.guardrails.map((item) => <div key={item}><ShieldCheck size={15} /><span>{item}</span></div>)}
      </section>

      <section className="ru-console-panel ru-agent-runtime-card">
        <header><strong><FileCode2 size={16} />运行来源</strong><span>代码发布</span></header>
        <dl>
          <div><dt>摘要触发</dt><dd>{detail.summarization_trigger_messages} 条消息</dd></div>
          <div><dt>摘要保留</dt><dd>{detail.summarization_keep_messages} 条消息</dd></div>
          <div><dt>在线编辑</dt><dd>{detail.editable ? '已启用' : '未启用'}</dd></div>
        </dl>
        <code>{detail.source_module}</code>
        <p>当前版本由代码与启动配置发布，页面不伪造草稿、版本或在线编辑能力。</p>
      </section>
    </div>
  </div>;
}
