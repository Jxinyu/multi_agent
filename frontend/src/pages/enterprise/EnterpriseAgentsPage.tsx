import { ArrowRight, Bot, CheckCircle2, ExternalLink, Network, PlugZap, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchDependencyHealth, fetchRuntimeSummary, type RuntimeSummary } from '../../api/enterprise';

export function EnterpriseAgentsPage() {
  const navigate = useNavigate();
  const [runtime, setRuntime] = useState<RuntimeSummary | null>(null);
  const [health, setHealth] = useState<Record<string, boolean>>({});
  const load = async () => { const [summary, checks] = await Promise.all([fetchRuntimeSummary(), fetchDependencyHealth()]); setRuntime(summary); setHealth(checks); };
  useEffect(() => { void load(); }, []);
  return <div className="ru-enterprise-page"><header className="ru-console-title"><div><h1>智能体与 MCP</h1><p>当前发布拓扑、领域能力和连接配置。</p></div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button><button className="is-primary" type="button" onClick={() => navigate('/app')}><ExternalLink size={16} />测试运行</button></header><section className="ru-runtime-canvas"><div className="ru-pipeline-row">{runtime?.pipeline.map((step, index) => <div key={step}><span>{index === 0 ? <Network size={17} /> : index === 1 ? <Bot size={17} /> : <PlugZap size={17} />}</span><strong>{step}</strong>{index < runtime.pipeline.length - 1 ? <i /> : null}</div>)}</div><div className="ru-agent-grid">{runtime?.agents.map((agent) => <article key={agent.id}><header><Bot size={17} /><strong>{agent.id.toUpperCase()} 智能体</strong><CheckCircle2 size={14} /></header><p>{agent.description}</p><dl><div><dt>模型</dt><dd>Qwen</dd></div><div><dt>工具上限</dt><dd>4 次/运行</dd></div></dl><button type="button" onClick={() => navigate(`/enterprise/agents/${agent.id}`)}>查看运行详情 <ArrowRight size={14} /></button></article>)}</div></section><div className="ru-runtime-bottom"><section className="ru-console-panel"><header><strong>MCP 连接</strong><span>配置状态</span></header><div className="ru-connection-table"><div><span>连接</span><span>类型</span><span>配置</span><span>健康</span></div>{runtime?.connections.map((connection) => <div key={connection.id}><strong>{connection.label}</strong><span>MCP</span><span className={connection.configured ? 'is-healthy' : 'is-muted'}>{connection.configured ? '已配置' : '未配置'}</span><span>{connection.id === 'rag' ? (health['mcp-rag'] ? '正常' : '异常') : '未探测'}</span></div>)}</div></section><section className="ru-console-panel ru-runtime-policy"><header><strong>运行策略</strong><span>当前生效</span></header><dl><div><dt>检索方式</dt><dd>Milvus + Neo4j</dd></div><div><dt>审计重试</dt><dd>相同意见快速失败</dd></div><div><dt>工具调用</dt><dd>每个子智能体最多 4 次</dd></div><div><dt>人机协作</dt><dd>LangGraph Interrupt</dd></div></dl></section></div></div>;
}
