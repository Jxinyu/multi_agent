import { ArrowRight, Box, Cpu, HardDrive, RefreshCw, ServerOff } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchModelInventory, type ModelInventory } from '../../api/platform';

const size = (bytes: number | null) => bytes === null ? '未知' : `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;

function installationLabel(installed: boolean | null) {
  if (installed === true) return '已安装';
  if (installed === false) return '未安装';
  return '待核验';
}

export function AdminModelsPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<ModelInventory | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const load = async () => {
    setBusy(true);
    setError('');
    try { setData(await fetchModelInventory()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '模型清单加载失败'); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, []);

  const installed = data?.models.filter((model) => model.installed === true) ?? [];
  const total = installed.reduce((sum, model) => sum + (model.size_bytes ?? 0), 0);
  const assigned = data?.models.filter((model) => model.configured).length ?? 0;

  return <div className="ru-admin-page">
    <header className="ru-admin-title"><div><h1>模型与容量</h1><p>核对服务端配置、Ollama 安装状态和实时加载状态，不估算并发容量。</p></div><button type="button" onClick={() => void load()} disabled={busy}><RefreshCw className={busy ? 'is-spinning' : ''} size={16} />刷新</button></header>
    {error ? <div className="ru-inline-error">{error}</div> : null}
    {data && !data.connected ? <div className="ru-admin-notice is-danger"><ServerOff size={17} /><span><strong>Ollama 不可用</strong>{data.error}；已配置模型的安装状态暂时无法核验。</span></div> : null}
    <section className="ru-admin-kpis">
      <div><Cpu /><span>运行时<strong>{data?.connected ? '已连接' : '未连接'}</strong></span></div>
      <div><Box /><span>已安装模型<strong>{data?.connected ? installed.length : '—'}</strong></span></div>
      <div><HardDrive /><span>已核验文件量<strong>{data?.connected ? size(total) : '—'}</strong></span></div>
      <div><Cpu /><span>已配置模型<strong>{data ? assigned : '—'}</strong></span></div>
    </section>
    <section className="ru-admin-panel ru-model-table">
      <header><strong>Ollama 模型清单</strong><code>{data?.endpoint ?? '正在连接'}</code></header>
      <div className="ru-model-head"><span>模型</span><span>角色</span><span>文件大小</span><span>最近修改</span><span>状态</span><span /></div>
      {data?.models.map((model) => <button type="button" key={model.name} onClick={() => navigate(`/admin/models/detail?name=${encodeURIComponent(model.name)}`)}>
        <strong><Cpu size={16} />{model.name}</strong>
        <span>{model.roles.join('、') || '未分配'}</span>
        <span>{model.installed === true ? size(model.size_bytes) : '—'}</span>
        <time>{model.modified_at ? new Date(model.modified_at).toLocaleString('zh-CN') : '—'}</time>
        <em className={model.installed === true ? 'is-installed' : model.installed === false ? 'is-missing' : 'is-unknown'}>{installationLabel(model.installed)}</em>
        <ArrowRight size={15} />
      </button>)}
      {data?.connected && !data.models.length ? <p className="ru-admin-empty">运行时已连接，且服务端没有配置或安装模型。</p> : null}
    </section>
    <div className="ru-admin-notice"><Cpu size={17} /><span><strong>容量数据未推测</strong>当前接口不提供 QPS、请求队列和 GPU 利用率；接入 GPU Exporter 与指标存储后才能展示可验证容量。</span></div>
  </div>;
}
