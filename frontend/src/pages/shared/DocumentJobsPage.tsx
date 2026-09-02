import { ArrowLeft, ArrowRight, CheckCircle2, ChevronDown, Filter, LoaderCircle, RefreshCw, Search, ShieldAlert, X } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { fetchDocumentJobs, type DocumentJob } from '../../api/jobs';
import { jobModeLabel, jobOperationLabel, jobStatusLabel } from './jobStatus';

interface DocumentJobsPageProps {
  mode: 'user' | 'enterprise';
}

export function DocumentJobsPage({ mode }: DocumentJobsPageProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState<DocumentJob[]>([]);
  const [total, setTotal] = useState(0);
  const [documentId, setDocumentId] = useState(searchParams.get('document_id') ?? '');
  const [status, setStatus] = useState('');
  const [operation, setOperation] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const backPath = mode === 'enterprise' ? '/enterprise/knowledge' : '/app/documents';
  const detailBase = mode === 'enterprise' ? '/enterprise/knowledge/jobs' : '/app/documents/jobs';

  const load = async (append = false, clear = false) => {
    setLoading(true);
    setError('');
    const nextDocumentId = clear ? '' : documentId.trim();
    const nextStatus = clear ? '' : status;
    const nextOperation = clear ? '' : operation;
    try {
      const result = await fetchDocumentJobs({
        mode,
        documentId: nextDocumentId,
        status: nextStatus,
        operation: nextOperation,
        offset: append ? items.length : 0
      });
      setItems((current) => append ? [...current, ...result.items] : result.items);
      setTotal(result.total);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '文档任务加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const counts = useMemo(() => ({
    active: items.filter((item) => item.status === 'queued' || item.status === 'processing').length,
    failed: items.filter((item) => item.status === 'failed').length,
    succeeded: items.filter((item) => item.status === 'succeeded').length
  }), [items]);

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    void load();
  };

  const clearFilters = () => {
    setDocumentId('');
    setStatus('');
    setOperation('');
    void load(false, true);
  };

  return <div className={`ru-job-page is-${mode}`}>
    <header className="ru-job-title"><button type="button" aria-label="返回文档" onClick={() => navigate(backPath)}><ArrowLeft size={17} /></button><div><span>{mode === 'enterprise' ? '企业知识库' : '我的文档'}</span><h1>文档任务记录</h1><p>查询当前租户真实入库与清理任务，跟踪排队、重试和失败原因。</p></div><button type="button" disabled={loading} onClick={() => void load()}><RefreshCw className={loading ? 'ru-spin' : ''} size={16} />刷新</button></header>

    {error ? <div className="ru-inline-error">{error}</div> : null}

    <section className="ru-job-kpis" aria-label="任务摘要"><div><Search /><span>匹配任务<strong>{total}</strong></span></div><div><LoaderCircle /><span>排队或执行<strong>{counts.active}</strong></span></div><div><ShieldAlert /><span>已加载失败<strong>{counts.failed}</strong></span></div><div><CheckCircle2 /><span>已加载成功<strong>{counts.succeeded}</strong></span></div></section>

    <form className="ru-job-filters" onSubmit={applyFilters}><label><Search size={15} /><input value={documentId} onChange={(event) => setDocumentId(event.target.value)} placeholder="文档 ID" aria-label="按文档 ID 筛选" /></label><select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="按任务状态筛选"><option value="">全部状态</option><option value="queued">等待执行</option><option value="processing">执行中</option><option value="succeeded">已成功</option><option value="failed">已失败</option></select><select value={operation} onChange={(event) => setOperation(event.target.value)} aria-label="按任务类型筛选"><option value="">全部类型</option><option value="ingest">文档入库</option><option value="delete">文档清理</option></select><button type="submit" disabled={loading}><Filter size={15} />应用</button><button type="button" disabled={loading || (!documentId && !status && !operation)} onClick={clearFilters}><X size={15} />清除</button></form>

    <section className="ru-job-table"><header><strong>任务历史</strong><span>{items.length}/{total} 条</span></header><div className="ru-job-head"><span>文档</span><span>任务</span><span>执行后端</span><span>状态</span><span>尝试</span><span>更新时间</span><span /></div>{items.map((item) => <button type="button" key={item.id} onClick={() => navigate(`${detailBase}/${item.id}`)}><span><strong>{item.file_name ?? '文档已删除'}</strong><small>{item.document_id}</small></span><span>{jobOperationLabel[item.operation] ?? item.operation}</span><span>{jobModeLabel[item.mode] ?? item.mode}</span><em className={`is-${item.status}`}>{jobStatusLabel[item.status] ?? item.status}</em><span>{item.attempts}</span><time>{new Date(item.updated_at).toLocaleString('zh-CN')}</time><ArrowRight size={15} /></button>)}{!loading && !items.length ? <div className="ru-data-empty"><LoaderCircle size={28} /><strong>当前筛选没有任务</strong><span>提交文档入库后，任务会在这里保留可追踪记录。</span></div> : null}{items.length < total ? <button className="ru-job-load-more" type="button" disabled={loading} onClick={() => void load(true)}><ChevronDown size={15} />加载更多</button> : null}</section>
  </div>;
}
