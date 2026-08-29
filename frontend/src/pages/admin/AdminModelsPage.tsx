import { Box, Cpu, HardDrive, RefreshCw, ServerOff } from 'lucide-react';
import { useEffect, useState } from 'react';

import { fetchModelInventory, type ModelInventory } from '../../api/platform';

const size = (bytes: number | null) => bytes === null ? '未知' : `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;

export function AdminModelsPage() {
  const [data, setData] = useState<ModelInventory | null>(null);
  const [error, setError] = useState('');
  const load = async () => { setError(''); try { setData(await fetchModelInventory()); } catch (reason) { setError(reason instanceof Error ? reason.message : '模型清单加载失败'); } };
  useEffect(() => { void load(); }, []);
  const total = data?.models.reduce((sum, model) => sum + (model.size_bytes ?? 0), 0) ?? 0;
  return <div className="ru-admin-page"><header className="ru-admin-title"><div><h1>模型与容量</h1><p>读取本地 Ollama 运行时实际安装模型，不估算并发容量。</p></div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button></header>{error ? <div className="ru-inline-error">{error}</div> : null}{data && !data.connected ? <div className="ru-admin-notice is-danger"><ServerOff size={17} /><span><strong>Ollama 不可用</strong>{data.error}</span></div> : null}<section className="ru-admin-kpis"><div><Cpu /><span>运行时<strong>{data?.connected ? '已连接' : '未连接'}</strong></span></div><div><Box /><span>已安装模型<strong>{data?.models.length ?? '—'}</strong></span></div><div><HardDrive /><span>文件总量<strong>{size(total)}</strong></span></div><div><Cpu /><span>已分配角色<strong>{data?.models.filter((item) => item.roles.length).length ?? '—'}</strong></span></div></section><section className="ru-admin-panel ru-model-table"><header><strong>Ollama 模型清单</strong><code>{data?.endpoint ?? '正在连接'}</code></header><div className="ru-model-head"><span>模型</span><span>角色</span><span>文件大小</span><span>最近修改</span><span>状态</span></div>{data?.models.map((model) => <div key={model.name}><strong><Cpu size={16} />{model.name}</strong><span>{model.roles.join('、') || '未分配'}</span><span>{size(model.size_bytes)}</span><time>{model.modified_at ? new Date(model.modified_at).toLocaleString('zh-CN') : '未知'}</time><em>可用</em></div>)}{data?.connected && !data.models.length ? <p className="ru-admin-empty">运行时已连接，但没有安装模型。</p> : null}</section><div className="ru-admin-notice"><Cpu size={17} /><span><strong>容量数据未推测</strong>Ollama 未提供 QPS、显存与队列指标；接入 GPU Exporter 后才能展示可验证容量。</span></div></div>;
}
