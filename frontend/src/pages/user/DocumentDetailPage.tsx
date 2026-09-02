import { ArrowLeft, CheckCircle2, Database, Eye, FileText, RefreshCw, ShieldCheck, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchKnowledgeBaseDocumentDetail, ingestKnowledgeBaseDocument } from '../../api/admin';
import { fetchDocumentJobs, type DocumentJob } from '../../api/jobs';
import { fetchUserDocument } from '../../api/user';
import type { DocumentDetail } from '../../types';
import { jobOperationLabel, jobStatusLabel } from '../shared/jobStatus';

interface DocumentDetailPageProps {
  mode: 'user' | 'enterprise';
}

export function DocumentDetailPage({ mode }: DocumentDetailPageProps) {
  const { documentId } = useParams();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [jobs, setJobs] = useState<DocumentJob[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const backPath = mode === 'enterprise' ? '/enterprise/knowledge' : '/app/documents';
  const previewPath = mode === 'enterprise' ? `/enterprise/knowledge/${documentId}/preview` : `/app/documents/${documentId}/preview`;
  const jobsPath = mode === 'enterprise' ? '/enterprise/knowledge/jobs' : '/app/documents/jobs';

  const load = async () => {
    if (!documentId) {
      setError('文档标识缺失');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const [nextDetail, history] = await Promise.all([
        mode === 'enterprise' ? fetchKnowledgeBaseDocumentDetail(documentId) : fetchUserDocument(documentId),
        fetchDocumentJobs({ mode, documentId, limit: 5 })
      ]);
      setDetail(nextDetail);
      setJobs(history.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '文档详情加载失败');
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    setDetail(null);
    void load();
  }, [documentId, mode]);

  const ingest = async () => {
    if (!documentId || busy) return;
    setBusy(true);
    setError('');
    try {
      const submission = await ingestKnowledgeBaseDocument(documentId, 'graphrag');
      navigate(`${jobsPath}/${submission.jobId}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '入库任务提交失败');
      setBusy(false);
    }
  };

  if (error && !detail) {
    return <div className="ru-record-detail-page"><button className="ru-back-command" type="button" onClick={() => navigate(backPath)}><ArrowLeft size={15} />返回文档列表</button><div className="ru-task-detail-state is-error"><XCircle size={28} /><strong>无法读取文档</strong><p>{error}</p></div></div>;
  }
  if (!detail) {
    return <div className="ru-record-detail-page"><div className="ru-task-detail-state"><RefreshCw className="is-spinning" size={28} /><strong>正在读取文档</strong></div></div>;
  }

  const item = detail.item;
  const backendEntries = Object.entries(item.backend_status);
  return (
    <div className="ru-record-detail-page">
      <header className="ru-record-detail-title">
        <button type="button" onClick={() => navigate(backPath)} aria-label="返回文档列表"><ArrowLeft size={17} /></button>
        <div><span>{mode === 'enterprise' ? '企业知识库' : '我的文档'}</span><h1>{item.title || item.file_name}</h1><p>{item.file_name} · {item.id}</p></div>
        <button className="ru-outline-command" type="button" onClick={() => void load()} disabled={busy}><RefreshCw className={busy ? 'is-spinning' : ''} size={15} />刷新</button>
      </header>
      {error ? <div className="ru-inline-error">{error}</div> : null}
      <div className="ru-document-detail-layout">
        <aside className="ru-record-metadata">
          <section><header><FileText size={15} /><strong>文档信息</strong><span className={`ru-doc-status is-${item.status}`}>{item.status}</span></header><dl><div><dt>版本</dt><dd>v{item.version}</dd></div><div><dt>所有者</dt><dd>{item.owner_id}</dd></div><div><dt>上传时间</dt><dd>{new Date(item.upload_time).toLocaleString('zh-CN')}</dd></div><div><dt>校验摘要</dt><dd title={item.checksum}>{item.checksum.slice(0, 16)}</dd></div></dl></section>
          <section><header><ShieldCheck size={15} /><strong>权限范围</strong></header><p>{item.acl.length ? item.acl.join('、') : 'private'}</p></section>
          <section><header><Eye size={15} /><strong>原文件核验</strong></header><p>通过服务端权限校验预览或下载上传时保存的原文件，不暴露服务器存储路径。</p><button className="ru-primary-command" type="button" onClick={() => navigate(previewPath)}><Eye size={15} />预览原文件</button></section>
          <section><header><Database size={15} /><strong>解析与入库</strong></header><dl><div><dt>解析模式</dt><dd>{item.mode}</dd></div><div><dt>切块数量</dt><dd>{item.chunk_count}</dd></div><div><dt>处理进度</dt><dd>{item.ingest_progress ?? 0}/{item.ingest_total ?? 0}</dd></div><div><dt>批次</dt><dd>{item.batch_id || '无进行中批次'}</dd></div></dl>{item.ingest_message ? <p>{item.ingest_message}</p> : null}{item.error ? <p className="ru-detail-error"><XCircle size={15} />{item.error}</p> : null}<button className="ru-primary-command" type="button" onClick={() => void ingest()} disabled={busy || item.status === 'processing' || item.status === 'queued'}><Database size={15} />{item.status === 'processing' || item.status === 'queued' ? '任务进行中' : '重新混合入库'}</button></section>
          <section><header><RefreshCw size={15} /><strong>最近任务</strong></header>{jobs.length ? <div className="ru-document-job-list">{jobs.map((job) => <button type="button" key={job.id} onClick={() => navigate(`${jobsPath}/${job.id}`)}><span><strong>{jobOperationLabel[job.operation] ?? job.operation}</strong><small>{new Date(job.updated_at).toLocaleString('zh-CN')}</small></span><em className={`is-${job.status}`}>{jobStatusLabel[job.status] ?? job.status}</em></button>)}</div> : <p>该文档尚无异步任务记录。</p>}<button className="ru-outline-command" type="button" onClick={() => navigate(`${jobsPath}?document_id=${item.id}`)}>查看全部任务</button></section>
          <section><header><CheckCircle2 size={15} /><strong>后端状态</strong></header>{backendEntries.length ? <div className="ru-backend-status-list">{backendEntries.map(([backend, value]) => <div key={backend}><span>{backend}</span><strong>{value}</strong></div>)}</div> : <p>当前尚未记录向量库或图谱后端状态。</p>}</section>
        </aside>
        <article className="ru-document-reading"><header><FileText size={16} /><strong>解析预览</strong>{detail.preview_truncated ? <span>已截取前 {detail.preview?.length ?? 0} 字符</span> : <span>受控解析文件</span>}</header>{detail.preview ? <pre>{detail.preview}</pre> : <div className="ru-data-empty"><FileText size={28} /><strong>暂无解析预览</strong><span>文档完成解析后，此处将展示用于检索的规范化文本。</span></div>}</article>
      </div>
    </div>
  );
}
