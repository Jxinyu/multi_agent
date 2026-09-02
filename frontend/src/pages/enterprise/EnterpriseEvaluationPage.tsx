import { ArrowRight, BarChart3, Database, ExternalLink } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { downloadEvaluationReport, fetchEvaluationSummary, type EvaluationMetric } from '../../api/enterprise';

const format = (metric: EvaluationMetric, value: number) => metric.unit === 'ratio' ? `${(value * 100).toFixed(2)}%` : value.toFixed(0);

export function EnterpriseEvaluationPage() {
  const navigate = useNavigate();
  const [metrics, setMetrics] = useState<EvaluationMetric[]>([]);
  const [error, setError] = useState('');
  useEffect(() => { void fetchEvaluationSummary().then(setMetrics).catch((reason) => setError(reason instanceof Error ? reason.message : '评测加载失败')); }, []);

  const runs = useMemo(() => {
    const unique = new Map<string, { runId: string; source: string; sampleCount: number; labels: string[] }>();
    for (const metric of metrics) {
      const current = unique.get(metric.run_id);
      if (current) current.labels.push(metric.label);
      else unique.set(metric.run_id, { runId: metric.run_id, source: metric.source, sampleCount: metric.sample_count, labels: [metric.label] });
    }
    return [...unique.values()];
  }, [metrics]);

  return <div className="ru-enterprise-page">
    <header className="ru-console-title">
      <div><h1>评测、反馈与成本</h1><p>仅展示仓库中已完成且可追溯的离线实验结果。</p></div>
      <button type="button" onClick={() => void downloadEvaluationReport()}><ExternalLink size={16} />证据报告</button>
    </header>
    {error ? <div className="ru-inline-error">{error}</div> : null}
    <section className="ru-eval-kpis">{metrics.map((metric) => {
      const lift = metric.baseline === 0 ? null : (metric.current - metric.baseline) / metric.baseline;
      return <article key={metric.id}><span>{metric.id.includes('recall') ? <Database size={15} /> : <BarChart3 size={15} />}{metric.label}</span><strong>{format(metric, metric.current)}</strong><small>基线 {format(metric, metric.baseline)} · {lift === null ? '绝对值口径' : `${lift >= 0 ? '+' : ''}${(lift * 100).toFixed(2)}%`}</small></article>;
    })}</section>
    <div className="ru-eval-layout">
      <section className="ru-console-panel ru-eval-chart"><header><strong>基线与当前方案对比</strong><span>同一实验口径</span></header>{metrics.map((metric) => {
        const max = Math.max(metric.baseline, metric.current, 0.0001);
        return <div key={metric.id}><label><strong>{metric.label}</strong><span>样本 {metric.sample_count}</span></label><div><span>基线</span><i><b style={{ width: `${metric.baseline / max * 100}%` }} /></i><em>{format(metric, metric.baseline)}</em></div><div><span>当前</span><i><b className="is-current" style={{ width: `${metric.current / max * 100}%` }} /></i><em>{format(metric, metric.current)}</em></div></div>;
      })}</section>
      <section className="ru-console-panel ru-eval-sources"><header><strong>实验来源</strong><span>{runs.length} 个运行</span></header>{runs.map((run) => <article key={run.runId}><strong>{run.runId}</strong><span>{run.source}</span><small>样本数：{run.sampleCount} · 指标：{run.labels.join('、')}</small><button type="button" onClick={() => navigate(`/enterprise/evaluation/${run.runId}`)}>查看完整运行 <ArrowRight size={14} /></button></article>)}</section>
    </div>
  </div>;
}
