import { ArrowLeft, CheckCircle2, CircleSlash2, Clock3, Database, FileText, RefreshCw, RotateCw, UserRound } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchKnowledgeBaseDocumentDetail } from '../../api/admin';
import { fetchDocumentJob, type DocumentJob } from '../../api/jobs';
import { fetchUserDocument } from '../../api/user';
import type { DocumentDetail } from '../../types';
import { isActiveJob, jobModeLabel, jobOperationLabel, jobStatusLabel } from './jobStatus';

interface DocumentJobDetailPageProps {
  mode: 'user' | 'enterprise' | 'admin';
}

export function DocumentJobDetailPage({ mode }: DocumentJobDetailPageProps) {
  const navigate = useNavigate();
  const { jobId = '' } = useParams();
  const [job, setJob] = useState<DocumentJob | null>(null);
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [documentError, setDocumentError] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const listPath = mode === 'admin' ? '/admin/operations/worker' : mode === 'enterprise' ? '/enterprise/knowledge/jobs' : '/app/documents/jobs';
  const documentBase = mode === 'user' ? '/app/documents' : '/enterprise/knowledge';
  const backLabel = mode === 'admin' ? '返回 Worker' : '返回任务记录';

  const load = async (initial = false) => {
    if (initial) setLoading(true);
    setError('');
    try {
      const nextJob = await fetchDocumentJob(jobId, mode === 'user' ? 'user' : 'enterprise');
      setJob(nextJob);
      try {
        const nextDocument = await (mode === 'user' ? fetchUserDocument(nextJob.document_id) : fetchKnowledgeBaseDocumentDetail(nextJob.document_id));
        setDocument(nextDocument);
        setDocumentError('');
      } catch (reason) {
        setDocument(null);
        setDocumentError(reason instanceof Error ? reason.message : '关联文档不可用');
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '任务详情加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(true); }, [jobId, mode]);
  useEffect(() => {
    if (!job || !isActiveJob(job.status)) return;
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [job?.status, jobId, mode]);

  if (loading) return <div className="ru-job-page"><div className="ru-job-state"><RefreshCw className="ru-spin" /><strong>正在读取任务记录</strong></div></div>;
  if (error || !job) return <div className="ru-job-page"><button className="ru-job-back" type="button" onClick={() => navigate(listPath)}><ArrowLeft size={16} />{backLabel}</button><div className="ru-job-state is-error"><CircleSlash2 /><strong>无法打开任务</strong><span>{error || '任务不存在'}</span><button type="button" onClick={() => void load(true)}>重试</button></div></div>;

  return <div className="ru-job-page ru-job-detail-page"><header className="ru-job-title"><button type="button" aria-label={backLabel} title={backLabel} onClick={() => navigate(listPath)}><ArrowLeft size={17} /></button><div><span>{jobOperationLabel[job.operation] ?? job.operation}</span><h1>任务执行详情</h1><p>{job.id}</p></div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button></header>

    <section className={`ru-job-hero is-${job.status}`}><span>{job.status === 'succeeded' ? <CheckCircle2 size={28} /> : job.status === 'failed' ? <CircleSlash2 size={28} /> : <RotateCw className="ru-spin" size={28} />}</span><div><small>{job.file_name ?? '关联文档已删除'}</small><h2>{jobStatusLabel[job.status] ?? job.status}</h2><p>{jobModeLabel[job.mode] ?? job.mode}</p></div><strong>{isActiveJob(job.status) ? '每 3 秒自动刷新' : '任务已进入终态'}</strong></section>

    <div className="ru-job-detail-grid"><section className="ru-job-panel"><header><Database size={16} /><strong>执行事实</strong></header><dl><div><dt>任务类型</dt><dd>{jobOperationLabel[job.operation] ?? job.operation}</dd></div><div><dt>执行后端</dt><dd>{jobModeLabel[job.mode] ?? job.mode}</dd></div><div><dt>尝试次数</dt><dd>{job.attempts}</dd></div><div><dt>创建时间</dt><dd>{new Date(job.created_at).toLocaleString('zh-CN')}</dd></div><div><dt>更新时间</dt><dd>{new Date(job.updated_at).toLocaleString('zh-CN')}</dd></div></dl></section>
      <section className="ru-job-panel"><header><UserRound size={16} /><strong>请求上下文</strong></header><dl><div><dt>请求人</dt><dd>{job.requested_by ?? '未记录'}</dd></div><div><dt>请求 ID</dt><dd>{job.request_id ?? '未记录'}</dd></div><div><dt>文档 ID</dt><dd>{job.document_id}</dd></div></dl></section>
      <section className="ru-job-panel ru-job-document"><header><FileText size={16} /><strong>关联文档</strong></header>{document ? <><div><FileText size={24} /><span><strong>{document.item.title || document.item.file_name}</strong><small>{document.item.status} · v{document.item.version} · {document.item.chunk_count} 个切块</small></span></div><button type="button" onClick={() => navigate(`${documentBase}/${job.document_id}`)}>打开文档详情</button></> : <p>{job.operation === 'delete' ? '清理任务完成后文档元数据会被删除。' : `关联文档不可用：${documentError}`}</p>}</section>
      <section className="ru-job-panel ru-job-error"><header><Clock3 size={16} /><strong>最近执行结果</strong></header>{job.error ? <pre>{job.error}</pre> : <p>{isActiveJob(job.status) ? '当前没有失败信息，页面正在等待 Worker 更新。' : '任务未记录错误。'}</p>}</section></div>
  </div>;
}
