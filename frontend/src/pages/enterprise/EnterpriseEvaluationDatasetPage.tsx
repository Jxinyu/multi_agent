import { AlertTriangle, ArrowLeft, CheckCircle2, Database, ExternalLink, FileCheck2, FileWarning, RefreshCw, ShieldCheck } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchEvaluationDatasetDetail, type EvaluationDatasetDetail } from '../../api/enterprise';

const integrityLabel = {
  verified: '摘要一致',
  mismatch: '摘要不一致',
  not_distributed: '未随仓库分发',
  missing: '仓库文件缺失'
} as const;

function formatBytes(bytes: number | null) {
  if (bytes === null) return '未提供';
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function EnterpriseEvaluationDatasetPage() {
  const navigate = useNavigate();
  const { runId = '' } = useParams();
  const [detail, setDetail] = useState<EvaluationDatasetDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = async () => {
    setLoading(true);
    setError('');
    try { setDetail(await fetchEvaluationDatasetDetail(runId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '数据集登记加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [runId]);

  const artifactSummary = useMemo(() => {
    const items = detail?.artifacts ?? [];
    return {
      verified: items.filter((item) => item.integrity === 'verified').length,
      repository: items.filter((item) => item.distribution === 'repository').length,
      localAvailable: items.filter((item) => item.distribution === 'local_cache' && item.available).length,
      localTotal: items.filter((item) => item.distribution === 'local_cache').length,
      damaged: items.filter((item) => item.integrity === 'mismatch' || item.integrity === 'missing').length
    };
  }, [detail]);
  const maxDistribution = Math.max(...(detail?.distributions.map((item) => item.count) ?? [1]), 1);

  if (loading && !detail) return <div className="ru-enterprise-page"><div className="ru-detail-loading"><RefreshCw className="ru-spin" /><strong>正在核验数据集登记与文件摘要</strong></div></div>;
  if (error || !detail) return <div className="ru-enterprise-page"><div className="ru-detail-error"><Database /><strong>无法打开数据集详情</strong><span>{error || '数据集登记不存在'}</span><button type="button" onClick={() => void load()}>重试</button></div></div>;

  return <div className="ru-enterprise-page ru-dataset-detail-page">
    <header className="ru-console-title ru-detail-title"><button type="button" title="返回评测运行" aria-label="返回评测运行" onClick={() => navigate(`/enterprise/evaluation/${detail.run_id}`)}><ArrowLeft size={16} />返回运行</button><div><h1>评测数据集详情</h1><p>{detail.run_id}</p></div><button type="button" disabled={loading} onClick={() => void load()}><RefreshCw className={loading ? 'ru-spin' : ''} size={16} />重新核验</button></header>

    <section className={`ru-dataset-hero${artifactSummary.damaged ? ' is-damaged' : ''}`}><span>{artifactSummary.damaged ? <FileWarning size={27} /> : <FileCheck2 size={27} />}</span><div><small>{detail.benchmark_type}</small><h2>{detail.name}</h2><p>{detail.split}</p></div><strong>{artifactSummary.damaged ? '存在完整性问题' : '登记可核验'}</strong></section>

    <section className="ru-dataset-kpis">
      <div><Database /><span>评测样本<strong>{detail.sample_count.toLocaleString('zh-CN')}</strong></span></div>
      <div><ShieldCheck /><span>摘要一致<strong>{artifactSummary.verified}/{detail.artifacts.length}</strong></span></div>
      <div><FileCheck2 /><span>仓库产物<strong>{artifactSummary.repository}</strong></span></div>
      <div><Database /><span>本地原始缓存<strong>{artifactSummary.localAvailable}/{artifactSummary.localTotal}</strong></span></div>
    </section>

    <div className="ru-dataset-overview-grid">
      <section className="ru-console-panel ru-dataset-method"><header><strong>抽样与划分</strong><span>登记版本 v{detail.registry_version}</span></header><dl><div><dt>固定种子</dt><dd>{detail.seed ?? '不使用随机抽样'}</dd></div><div><dt>数据划分</dt><dd>{detail.split}</dd></div><div><dt>原始样本正文</dt><dd>{detail.raw_samples_exposed ? '接口返回' : '接口不返回'}</dd></div></dl><p>{detail.selection_rule}</p></section>
      <section className="ru-console-panel ru-dataset-distribution"><header><strong>样本分布</strong><span>{detail.distributions.length} 组</span></header>{detail.distributions.map((item) => <div key={item.label}><span>{item.label}</span><i><b style={{ width: `${item.count / maxDistribution * 100}%` }} /></i><strong>{item.count}</strong></div>)}</section>
      <section className="ru-console-panel ru-dataset-sources"><header><strong>公开来源</strong><span>{detail.source_urls.length} 项</span></header>{detail.source_urls.map((item) => <a key={item.url} href={item.url} target="_blank" rel="noreferrer"><ExternalLink size={15} /><span><strong>{item.label}</strong><small>{item.url}</small></span></a>)}{!detail.source_urls.length ? <p>该数据集为项目生成的固定控制集，没有外部下载来源。</p> : null}</section>
    </div>

    <section className="ru-console-panel ru-dataset-artifacts"><header><strong>文件完整性</strong><span>SHA-256 · {new Date(detail.checked_at).toLocaleString('zh-CN')}</span></header><div className="ru-dataset-artifact-head"><span>文件与作用</span><span>分发方式</span><span>文件大小</span><span>摘要</span><span>状态</span></div>{detail.artifacts.map((item) => <article key={item.path} className={`is-${item.integrity}`}><span>{item.integrity === 'verified' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}<span><strong>{item.path}</strong><small>{item.role}{item.record_count === null ? '' : ` · ${item.record_count} 条记录`}</small></span></span><span>{item.distribution === 'repository' ? '随仓库分发' : '本地下载缓存'}</span><span>{formatBytes(item.actual_size_bytes ?? item.expected_size_bytes)}</span><code title={item.actual_sha256 ?? item.expected_sha256}>{(item.actual_sha256 ?? item.expected_sha256).slice(0, 16)}</code><em>{integrityLabel[item.integrity]}</em></article>)}</section>

    <div className="ru-dataset-controls-grid"><section className="ru-console-panel"><header><strong>防泄漏控制</strong><span>{detail.leakage_controls.length} 项</span></header>{detail.leakage_controls.map((item, index) => <div key={item}><span>{index + 1}</span><p>{item}</p></div>)}</section><section className="ru-console-panel is-limitation"><header><strong>解释边界</strong><span>{detail.limitations.length} 项</span></header>{detail.limitations.map((item) => <div key={item}><AlertTriangle size={15} /><p>{item}</p></div>)}</section></div>
    <div className="ru-dataset-note"><ShieldCheck size={16} /><span><strong>登记策略</strong>{detail.registry_note}</span></div>
  </div>;
}
