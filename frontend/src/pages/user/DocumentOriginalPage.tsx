import { AlertCircle, ArrowLeft, Download, Eye, File, FileText, Image, RefreshCw, ShieldCheck } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchKnowledgeBaseDocumentDetail } from '../../api/admin';
import { downloadDocumentOriginal, fetchDocumentOriginal, originalPreviewKind, type DocumentAccessMode, type OriginalPreviewKind } from '../../api/documents';
import { fetchUserDocument } from '../../api/user';
import type { DocumentDetail } from '../../types';

export function DocumentOriginalPage({ mode }: { mode: DocumentAccessMode }) {
  const { documentId = '' } = useParams();
  const navigate = useNavigate();
  const objectUrl = useRef<string | null>(null);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [kind, setKind] = useState<OriginalPreviewKind>('unsupported');
  const [previewUrl, setPreviewUrl] = useState('');
  const [text, setText] = useState('');
  const [textTruncated, setTextTruncated] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const detailPath = mode === 'enterprise' ? `/enterprise/knowledge/${documentId}` : `/app/documents/${documentId}`;

  const revokeObjectUrl = () => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = null;
  };
  const load = async () => {
    setBusy(true);
    setError('');
    revokeObjectUrl();
    setPreviewUrl('');
    setText('');
    setTextTruncated(false);
    try {
      const nextDetail = await (mode === 'enterprise' ? fetchKnowledgeBaseDocumentDetail(documentId) : fetchUserDocument(documentId));
      const nextKind = originalPreviewKind(nextDetail.item.file_name);
      setDetail(nextDetail);
      setKind(nextKind);
      if (nextKind !== 'unsupported') {
        const blob = await fetchDocumentOriginal(documentId, mode);
        if (nextKind === 'text') {
          const content = await blob.text();
          setText(content.slice(0, 500_000));
          setTextTruncated(content.length > 500_000);
        }
        else {
          objectUrl.current = URL.createObjectURL(blob);
          setPreviewUrl(objectUrl.current);
        }
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '原文件加载失败');
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => { void load(); return revokeObjectUrl; }, [documentId, mode]);

  const download = async () => {
    if (!detail) return;
    try { await downloadDocumentOriginal(documentId, detail.item.file_name, mode); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '原文件下载失败'); }
  };

  if (busy && !detail) return <div className="ru-record-detail-page"><div className="ru-task-detail-state"><RefreshCw className="is-spinning" /><strong>正在验证并加载原文件</strong></div></div>;
  if (error && !detail) return <div className="ru-record-detail-page"><button className="ru-back-command" type="button" onClick={() => navigate(detailPath)}><ArrowLeft size={15} />返回文档详情</button><div className="ru-task-detail-state is-error"><AlertCircle /><strong>无法打开原文件</strong><p>{error}</p></div></div>;
  if (!detail) return null;
  const item = detail.item;

  return <div className="ru-record-detail-page">
    <header className="ru-record-detail-title"><button type="button" onClick={() => navigate(detailPath)} aria-label="返回文档详情"><ArrowLeft size={17} /></button><div><span>原文件核验</span><h1>{item.title || item.file_name}</h1><p>{item.file_name} · v{item.version}</p></div><button className="ru-outline-command" type="button" onClick={() => void download()}><Download size={15} />下载原文件</button></header>
    {error ? <div className="ru-inline-error">{error}</div> : null}
    <div className="ru-original-layout"><aside className="ru-record-metadata"><section><header><File size={15} /><strong>文件信息</strong></header><dl><div><dt>文件名</dt><dd>{item.file_name}</dd></div><div><dt>预览类型</dt><dd>{kind === 'pdf' ? 'PDF' : kind === 'image' ? '图片' : kind === 'text' ? '文本' : '仅下载'}</dd></div><div><dt>所有者</dt><dd>{item.owner_id}</dd></div><div><dt>版本</dt><dd>v{item.version}</dd></div><div><dt>校验摘要</dt><dd title={item.checksum}>{item.checksum.slice(0, 16)}</dd></div></dl></section><section><header><ShieldCheck size={15} /><strong>访问控制</strong></header><p>文件内容通过当前访问令牌重新请求，服务端执行租户与文档权限校验，页面不包含服务器存储路径。</p></section></aside><article className="ru-original-preview"><header>{kind === 'image' ? <Image size={16} /> : <FileText size={16} />}<strong>原文件预览</strong><span>{busy ? '正在刷新' : textTruncated ? '已截取前 500,000 字符' : '受权内容'}</span></header>{kind === 'text' ? <pre>{text}</pre> : null}{kind === 'image' && previewUrl ? <div className="ru-original-image"><img src={previewUrl} alt={item.file_name} /></div> : null}{kind === 'pdf' && previewUrl ? <iframe src={previewUrl} title={`${item.file_name} PDF 预览`} /> : null}{kind === 'unsupported' ? <div className="ru-data-empty"><Eye size={30} /><strong>浏览器不支持此格式的安全预览</strong><span>可使用右上角下载原文件，并在受信任的本地应用中打开。</span><button className="ru-primary-command" type="button" onClick={() => void download()}><Download size={15} />下载原文件</button></div> : null}</article></div>
  </div>;
}
