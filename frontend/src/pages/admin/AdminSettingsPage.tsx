import { FileLock2, RefreshCw, Settings2, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';

import { fetchPlatformSettings, type PlatformSettings } from '../../api/platform';

export function AdminSettingsPage() {
  const [data, setData] = useState<PlatformSettings | null>(null);
  const [error, setError] = useState('');
  const load = async () => { setError(''); try { setData(await fetchPlatformSettings()); } catch (reason) { setError(reason instanceof Error ? reason.message : '配置加载失败'); } };
  useEffect(() => { void load(); }, []);
  return <div className="ru-admin-page"><header className="ru-admin-title"><div><h1>平台配置</h1><p>启动配置与环境变量的只读脱敏视图。</p></div><div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button><button type="button" disabled title="生产配置需通过部署系统变更"><Settings2 size={16} />编辑配置</button></div></header>{error ? <div className="ru-inline-error">{error}</div> : null}<div className="ru-admin-notice"><FileLock2 size={17} /><span><strong>{data?.mutable ? '可编辑配置' : '配置由部署系统托管'}</strong>{data?.source ?? '正在读取配置来源'}</span></div><div className="ru-settings-grid">{data?.groups.map((group) => <section className="ru-admin-panel ru-setting-group" key={group.id}><header><ShieldCheck size={17} /><strong>{group.label}</strong></header>{group.items.map((item) => <div key={item.key}><span>{item.label}<small>{item.key}</small></span><code>{item.value}</code></div>)}</section>)}</div></div>;
}
