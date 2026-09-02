import { AlertTriangle, Bell, CheckCircle2, Clock3, RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchAttentionItems, type AttentionItem, type AttentionSeverity } from '../../api/attention';
import type { ShellMode } from '../../app/navigation';

const severityLabel: Record<AttentionSeverity, string> = { critical: '需立即处理', warning: '需要关注', info: '运行信息' };

export function NotificationCenterPage({ mode }: { mode: ShellMode }) {
  const navigate = useNavigate();
  const [items, setItems] = useState<AttentionItem[]>([]);
  const [filter, setFilter] = useState<'all' | AttentionSeverity>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = async () => { setLoading(true); setError(''); try { setItems(await fetchAttentionItems(mode)); } catch (reason) { setError(reason instanceof Error ? reason.message : '通知加载失败'); } finally { setLoading(false); } };
  useEffect(() => { void load(); }, [mode]);
  const visible = useMemo(() => filter === 'all' ? items : items.filter((item) => item.severity === filter), [filter, items]);

  return <div className="ru-utility-page"><header className="ru-utility-title"><div><span>实时注意事项</span><h1>通知中心</h1><p>根据当前任务、文档、审计和服务探针即时生成，不使用固定通知数量。</p></div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button></header><section className="ru-attention-summary"><div><AlertTriangle /><span>立即处理<strong>{items.filter((item) => item.severity === 'critical').length}</strong></span></div><div><Clock3 /><span>需要关注<strong>{items.filter((item) => item.severity === 'warning').length}</strong></span></div><div><Bell /><span>运行信息<strong>{items.filter((item) => item.severity === 'info').length}</strong></span></div></section><div className="ru-utility-tabs">{(['all', 'critical', 'warning', 'info'] as const).map((value) => <button type="button" key={value} className={filter === value ? 'is-active' : ''} onClick={() => setFilter(value)}>{value === 'all' ? '全部' : severityLabel[value]}<strong>{value === 'all' ? items.length : items.filter((item) => item.severity === value).length}</strong></button>)}</div>{error ? <div className="ru-inline-error">{error}</div> : null}<section className="ru-attention-list">{loading ? <div className="ru-utility-empty"><RefreshCw className="ru-spin" /><strong>正在汇总实时状态</strong></div> : null}{!loading && !error && !visible.length ? <div className="ru-utility-empty"><CheckCircle2 /><strong>当前没有需要处理的通知</strong><span>系统状态变化后，刷新页面即可重新汇总。</span></div> : null}{visible.map((item) => <article key={item.id} className={`is-${item.severity}`}><span className="ru-attention-marker">{item.severity === 'critical' ? <AlertTriangle /> : item.severity === 'warning' ? <Clock3 /> : <Bell />}</span><div><small>{severityLabel[item.severity]}{item.occurredAt ? ` · ${new Date(item.occurredAt).toLocaleString('zh-CN')}` : ''}</small><h2>{item.title}</h2><p>{item.detail}</p></div><button type="button" onClick={() => navigate(item.actionPath)}>{item.actionLabel}</button></article>)}</section></div>;
}
