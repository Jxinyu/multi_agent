import { Activity, BookOpen, CheckCircle2, ExternalLink, FileQuestion, RefreshCw, Search, ShieldCheck, Wrench } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchDependencyHealth } from '../../api/enterprise';
import type { ShellMode } from '../../app/navigation';

const quickLinks = {
  user: [{ title: '搜索企业知识', detail: '使用混合检索并核对引用证据。', path: '/app/search', icon: Search }, { title: '处理任务追问', detail: '恢复等待补充的多智能体会话。', path: '/app/tasks', icon: FileQuestion }],
  enterprise: [{ title: '管理知识文档', detail: '检查解析、向量和图谱入库状态。', path: '/enterprise/knowledge', icon: BookOpen }, { title: '检查智能体运行时', detail: '查看智能体、MCP 和当前执行策略。', path: '/enterprise/agents', icon: Wrench }],
  admin: [{ title: '调查安全事件', detail: '按操作者和结果筛选审计事件。', path: '/admin/security', icon: ShieldCheck }, { title: '检查系统运行', detail: '读取依赖探针和 Worker 策略。', path: '/admin/operations', icon: Activity }]
} satisfies Record<ShellMode, { title: string; detail: string; path: string; icon: typeof Search }[]>;

export function HelpCenterPage({ mode }: { mode: ShellMode }) {
  const navigate = useNavigate();
  const [checks, setChecks] = useState<Record<string, boolean>>({});
  const [error, setError] = useState('');
  const load = async () => { setError(''); try { setChecks(await fetchDependencyHealth()); } catch (reason) { setError(reason instanceof Error ? reason.message : '系统状态加载失败'); } };
  useEffect(() => { void load(); }, []);
  const healthy = Object.values(checks).filter(Boolean).length;

  return <div className="ru-utility-page"><header className="ru-utility-title"><div><span>使用支持</span><h1>帮助与系统状态</h1><p>从当前工作区直接进入常用流程，并核对平台依赖是否就绪。</p></div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新状态</button></header>{error ? <div className="ru-inline-error">{error}</div> : null}<div className="ru-help-layout"><section className="ru-help-links"><header><BookOpen size={17} /><strong>当前角色快捷入口</strong></header>{quickLinks[mode].map((item) => { const Icon = item.icon; return <button type="button" key={item.path} onClick={() => navigate(item.path)}><Icon size={20} /><span><strong>{item.title}</strong><small>{item.detail}</small></span><ExternalLink size={15} /></button>; })}<a href="/docs" target="_blank" rel="noreferrer"><FileQuestion size={20} /><span><strong>查看 API 文档</strong><small>打开当前部署的 FastAPI OpenAPI 页面。</small></span><ExternalLink size={15} /></a></section><section className="ru-system-status"><header><Activity size={17} /><strong>实时依赖状态</strong><span>{healthy}/{Object.keys(checks).length} 正常</span></header>{Object.entries(checks).map(([name, ok]) => <div key={name}><span>{ok ? <CheckCircle2 size={15} /> : <Activity size={15} />}<strong>{name}</strong></span><em className={ok ? 'is-ok' : 'is-bad'}>{ok ? '正常' : '异常'}</em></div>)}{!Object.keys(checks).length && !error ? <div className="ru-utility-empty"><RefreshCw className="ru-spin" /><strong>正在读取探针</strong></div> : null}</section></div><section className="ru-help-boundary"><ShieldCheck size={20} /><div><strong>企业数据边界</strong><p>回答应以引用证据和当前权限为准。涉及权限变更、生产配置或高风险维护时，请由对应管理员通过受审计流程处理。</p></div></section></div>;
}
