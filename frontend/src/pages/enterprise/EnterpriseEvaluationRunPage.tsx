import { ArrowLeft, BarChart3, Database, Download, FlaskConical, RefreshCw, ShieldCheck } from 'lucide-react';
import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { downloadEvaluationReport, fetchEvaluationRunDetail, type EvaluationRunDetail, type EvaluationRunValue } from '../../api/enterprise';

function formatValue(item: EvaluationRunValue): string {
  if (item.unit === 'ratio') return `${(item.value * 100).toFixed(2)}%`;
  if (item.unit === 'seconds') return `${item.value.toFixed(item.value < 10 ? 3 : 1)} s`;
  return item.value.toFixed(0);
}

export function EnterpriseEvaluationRunPage() {
  const navigate = useNavigate();
  const { runId = '' } = useParams();
  const [detail, setDetail] = useState<EvaluationRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try { setDetail(await fetchEvaluationRunDetail(runId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '评测运行加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [runId]);

  const metricIds = useMemo(() => detail?.variants[0]?.values.map((item) => item.id) ?? [], [detail]);

  if (loading) return <div className="ru-enterprise-page"><div className="ru-detail-loading"><RefreshCw className="ru-spin" /><strong>正在读取版本化实验结果</strong></div></div>;
  if (error || !detail) return <div className="ru-enterprise-page"><div className="ru-detail-error"><FlaskConical /><strong>无法打开评测运行</strong><span>{error || '评测运行不存在'}</span><button type="button" onClick={() => void load()}>重试</button></div></div>;

  return <div className="ru-enterprise-page ru-evaluation-run-page">
    <header className="ru-console-title ru-detail-title">
      <button type="button" onClick={() => navigate('/enterprise/evaluation')}><ArrowLeft size={16} />返回评测</button>
      <div><h1>{detail.title}</h1><p>{detail.run_id}</p></div>
      <button className="is-primary" type="button" onClick={() => void downloadEvaluationReport()}><Download size={16} />下载证据报告</button>
    </header>

    <section className="ru-evaluation-run-meta">
      <div><BarChart3 /><span>评测类型<strong>{detail.category}</strong></span></div>
      <div><Database /><span>数据集<strong>{detail.dataset}</strong></span></div>
      <div><FlaskConical /><span>样本与划分<strong>{detail.sample_count} · {detail.split}</strong></span></div>
      <div><ShieldCheck /><span>结果来源<strong>版本库固定产物</strong></span></div>
    </section>

    <section className="ru-console-panel ru-run-comparison">
      <header><strong>方案横向对比</strong><span>{detail.variants.length} 个方案 · {metricIds.length} 项指标</span></header>
      <div className="ru-run-table-scroll">
        <div className="ru-run-table" style={{ '--variant-count': detail.variants.length } as CSSProperties}>
          <div className="ru-run-table-head"><span>指标</span>{detail.variants.map((variant) => <span key={variant.id}><strong>{variant.label}</strong><small>{variant.role}</small></span>)}</div>
          {metricIds.map((metricId) => {
            const first = detail.variants[0].values.find((item) => item.id === metricId);
            return <div className="ru-run-table-row" key={metricId}><strong>{first?.label ?? metricId}</strong>{detail.variants.map((variant) => { const value = variant.values.find((item) => item.id === metricId); return <span key={variant.id} className={variant.role === '当前方案' ? 'is-current' : ''}>{value ? formatValue(value) : '—'}</span>; })}</div>;
          })}
        </div>
      </div>
    </section>

    <div className="ru-evaluation-evidence-grid">
      <section className="ru-console-panel ru-run-methodology"><header><strong>验证口径</strong><span>可复核说明</span></header>{detail.notes.map((note, index) => <div key={note}><span>{index + 1}</span><p>{note}</p></div>)}</section>
      <section className="ru-console-panel ru-run-provenance"><header><strong>结果追溯</strong><span>只读</span></header><dl><div><dt>运行 ID</dt><dd>{detail.run_id}</dd></div><div><dt>样本数</dt><dd>{detail.sample_count}</dd></div><div><dt>数据划分</dt><dd>{detail.split}</dd></div></dl><code>{detail.source}</code><p>页面直接读取该 JSON 产物；未运行新实验时不会自动改写数值。</p></section>
    </div>
  </div>;
}
