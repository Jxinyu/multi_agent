import { ArrowLeft, Clock3, Copy, Database, Eye, FileText, Layers3 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchSearchEvidence } from '../../api/user';
import type { SearchEvidence } from '../../types';

export function SearchEvidenceDetailPage() {
  const { evidenceId } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState<SearchEvidence | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    setItem(null);
    if (!evidenceId) {
      setError('证据标识缺失');
      return;
    }
    setError('');
    void fetchSearchEvidence(evidenceId)
      .then(setItem)
      .catch((reason) => setError(reason instanceof Error ? reason.message : '证据加载失败'));
  }, [evidenceId]);

  const copy = async () => {
    if (!item) return;
    try {
      await navigator.clipboard.writeText(item.content);
      setNotice('证据正文已复制');
    } catch {
      setNotice('浏览器未允许复制，请手动选择正文');
    }
  };

  if (error) {
    return <div className="ru-record-detail-page"><button className="ru-back-command" type="button" onClick={() => navigate('/app/search')}><ArrowLeft size={15} />返回搜索</button><div className="ru-task-detail-state is-error"><FileText size={28} /><strong>无法读取证据</strong><p>{error}</p><span>检索证据仅在当前用户会话内保留一段时间，请重新执行搜索。</span></div></div>;
  }
  if (!item) {
    return <div className="ru-record-detail-page"><div className="ru-task-detail-state"><Clock3 className="is-spinning" size={28} /><strong>正在读取证据</strong></div></div>;
  }

  return (
    <div className="ru-record-detail-page">
      <header className="ru-record-detail-title">
        <button type="button" onClick={() => navigate('/app/search')} aria-label="返回搜索"><ArrowLeft size={17} /></button>
        <div><span>检索证据</span><h1>{item.source}</h1><p>{item.id}</p></div>
        <button className="ru-outline-command" type="button" onClick={() => void copy()}><Copy size={15} />复制正文</button>
      </header>
      {notice ? <div className="ru-answer-notice" role="status">{notice}</div> : null}
      <div className="ru-evidence-detail-layout">
        <aside className="ru-record-metadata">
          <section><header><Layers3 size={15} /><strong>检索定位</strong></header><dl><div><dt>证据类型</dt><dd>{item.kind}</dd></div><div><dt>检索后端</dt><dd>{item.backend || '未标注'}</dd></div><div><dt>匹配分值</dt><dd>{item.score?.toFixed(4) ?? 'N/A'}</dd></div><div><dt>文档版本</dt><dd>{item.version == null ? '未标注' : `v${item.version}`}</dd></div><div><dt>切片序号</dt><dd>{item.chunk_index == null ? '未标注' : item.chunk_index}</dd></div></dl></section>
          <section><header><Database size={15} /><strong>来源文档</strong></header><p>{item.document_id ? '该证据包含可验证的文档标识，可继续核对解析结果、权限和原文件。' : '当前检索后端未返回文档标识，不能跳转到文档详情。'}</p>{item.document_id ? <div className="ru-record-source-actions"><button className="ru-outline-command" type="button" onClick={() => navigate(`/app/documents/${item.document_id}`)}><FileText size={15} />文档详情</button><button className="ru-primary-command" type="button" onClick={() => navigate(`/app/documents/${item.document_id}/preview`)}><Eye size={15} />原文件</button></div> : null}</section>
        </aside>
        <article className="ru-evidence-reading"><header><FileText size={16} /><strong>命中正文</strong><span>当前账号授权范围</span></header><div>{item.content}</div></article>
      </div>
    </div>
  );
}
