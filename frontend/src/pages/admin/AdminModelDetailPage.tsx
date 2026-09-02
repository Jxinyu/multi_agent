import { AlertCircle, ArrowLeft, Box, CheckCircle2, Cpu, Gauge, HardDrive, RefreshCw, ServerOff } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { fetchModelRuntimeDetail, type ModelRuntimeDetail } from '../../api/platform';

const size = (bytes: number | null) => bytes === null ? '未提供' : `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
const value = (input: string | number | null) => input === null ? '未提供' : String(input);

function stateLabel(state: boolean | null, yes: string, no: string) {
  if (state === true) return yes;
  if (state === false) return no;
  return '待核验';
}

export function AdminModelDetailPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const name = searchParams.get('name')?.trim() ?? '';
  const [detail, setDetail] = useState<ModelRuntimeDetail | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const load = async () => {
    if (!name) { setError('缺少模型名称'); setBusy(false); return; }
    setBusy(true);
    setError('');
    try { setDetail(await fetchModelRuntimeDetail(name)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '模型运行详情加载失败'); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, [name]);

  if (busy && !detail) return <div className="ru-admin-page"><div className="ru-admin-detail-state"><RefreshCw className="is-spinning" /><strong>正在核验模型运行状态</strong></div></div>;
  if (error || !detail) return <div className="ru-admin-page"><div className="ru-admin-detail-state is-error"><AlertCircle /><strong>无法打开模型详情</strong><span>{error || '模型不存在'}</span><button type="button" onClick={() => void load()}>重试</button></div></div>;

  const available = detail.runtime_connected && detail.installed === true;
  return <div className="ru-admin-page ru-model-detail-page">
    <header className="ru-admin-title ru-admin-detail-title"><button type="button" title="返回模型清单" aria-label="返回模型清单" onClick={() => navigate('/admin/models')}><ArrowLeft size={16} /><span>返回模型</span></button><div><h1>模型运行详情</h1><p>{detail.name}</p></div><button type="button" onClick={() => void load()} disabled={busy}><RefreshCw className={busy ? 'is-spinning' : ''} size={16} />重新核验</button></header>
    <section className={`ru-model-detail-hero${available ? ' is-ok' : ''}`}><span>{available ? <CheckCircle2 size={25} /> : <ServerOff size={25} />}</span><div><small>{detail.roles.join('、') || '未分配业务角色'}</small><h2>{detail.name}</h2><p>{detail.endpoint}</p></div><strong>{stateLabel(detail.installed, '已安装', '未安装')}</strong></section>
    {detail.issues.length ? <div className="ru-admin-notice is-danger"><AlertCircle size={17} /><span><strong>部分运行信息不可用</strong>{detail.issues.join('；')}</span></div> : null}
    <section className="ru-admin-kpis ru-model-runtime-kpis">
      <div><Box /><span>服务端配置<strong>{detail.configured ? '已配置' : '未配置'}</strong></span></div>
      <div><Cpu /><span>当前加载<strong>{stateLabel(detail.running, '运行中', '未加载')}</strong></span></div>
      <div><HardDrive /><span>模型文件<strong>{size(detail.size_bytes)}</strong></span></div>
      <div><Gauge /><span>显存占用<strong>{size(detail.vram_size_bytes)}</strong></span></div>
    </section>
    <div className="ru-model-detail-grid">
      <section className="ru-admin-panel ru-model-facts"><header><strong><Cpu size={16} />模型元数据</strong><span>{detail.metadata_available ? 'Show 已核验' : 'Show 未核验'}</span></header><dl><div><dt>模型格式</dt><dd>{value(detail.format)}</dd></div><div><dt>模型族</dt><dd>{detail.families.join('、') || value(detail.family)}</dd></div><div><dt>参数规模</dt><dd>{value(detail.parameter_size)}</dd></div><div><dt>量化等级</dt><dd>{value(detail.quantization_level)}</dd></div><div><dt>最大上下文</dt><dd>{detail.maximum_context_length === null ? '未提供' : `${detail.maximum_context_length.toLocaleString('zh-CN')} tokens`}</dd></div><div><dt>能力声明</dt><dd>{detail.capabilities.join('、') || '未提供'}</dd></div></dl></section>
      <section className="ru-admin-panel ru-model-facts"><header><strong><Gauge size={16} />当前进程</strong><span>{detail.process_available ? 'Ps 已核验' : 'Ps 未核验'}</span></header><dl><div><dt>运行时连接</dt><dd>{detail.runtime_connected ? '正常' : '不可用'}</dd></div><div><dt>加载状态</dt><dd>{stateLabel(detail.running, '运行中', '未加载')}</dd></div><div><dt>加载文件量</dt><dd>{size(detail.loaded_size_bytes)}</dd></div><div><dt>显存占用</dt><dd>{size(detail.vram_size_bytes)}</dd></div><div><dt>活动上下文</dt><dd>{detail.active_context_length === null ? '未提供' : `${detail.active_context_length.toLocaleString('zh-CN')} tokens`}</dd></div><div><dt>卸载时间</dt><dd>{detail.expires_at ? new Date(detail.expires_at).toLocaleString('zh-CN') : '未加载或未提供'}</dd></div></dl></section>
    </div>
    <div className="ru-admin-notice"><Gauge size={17} /><span><strong>{detail.capacity_metrics_available ? '容量指标已接入' : '容量指标未接入'}</strong>{detail.capacity_note}</span></div>
    <p className="ru-model-checked-at">本次核验时间：{new Date(detail.checked_at).toLocaleString('zh-CN')}</p>
  </div>;
}
