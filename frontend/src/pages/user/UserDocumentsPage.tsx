import { ArrowRight, Database, File, FileUp, RefreshCw, Search, Upload, XCircle } from 'lucide-react';
import { ChangeEvent, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { ingestKnowledgeBaseDocument, uploadKnowledgeBaseDocuments } from '../../api/admin';
import { fetchUserDocuments } from '../../api/user';
import type { KnowledgeBaseItem } from '../../types';

export function UserDocumentsPage() {
  const navigate = useNavigate();
  const fileInput = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<KnowledgeBaseItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState<string[]>([]);
  const [error, setError] = useState('');
  const selected = items.find((item) => item.id === selectedId) ?? items[0] ?? null;
  const visible = useMemo(() => items.filter((item) => `${item.file_name} ${item.title}`.toLowerCase().includes(query.toLowerCase())), [items, query]);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await fetchUserDocuments();
      setItems(result);
      setSelectedId((current) => current ?? result[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '文档加载失败');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (!files.length) return;
    setUploading(files.map((file) => file.name));
    setError('');
    try {
      const form = new FormData();
      files.forEach((file) => form.append('files', file));
      form.append('mode', 'hybrid');
      const created = await uploadKnowledgeBaseDocuments(form);
      setItems((current) => [...created, ...current]);
      setSelectedId(created[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '上传失败');
    } finally {
      setUploading([]);
    }
  };

  const ingest = async () => {
    if (!selected) return;
    setError('');
    try {
      const updated = await ingestKnowledgeBaseDocument(selected.id, 'graphrag');
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '入库任务提交失败');
    }
  };

  const selectDocument = (documentId: string) => {
    setSelectedId(documentId);
    if (window.matchMedia('(max-width: 780px)').matches) {
      navigate(`/app/documents/${documentId}`);
    }
  };

  return (
    <div className="ru-documents-page">
      <section className="ru-document-main">
        <header className="ru-page-title"><div><h1>我的文档</h1><p>上传、解析并管理当前账号有权访问的知识文档。</p></div><button className="ru-outline-command" type="button" onClick={() => fileInput.current?.click()}><Upload size={16} />上传文件</button><input ref={fileInput} hidden multiple type="file" onChange={(event) => void upload(event)} /></header>
        <div className="ru-document-tabs"><button className="is-active" type="button">我的文档</button><button type="button">与我分享</button><button type="button">回收站</button></div>
        {uploading.length ? <div className="ru-upload-queue"><header><strong>上传队列（{uploading.length}）</strong><span>正在写入安全存储</span></header>{uploading.map((name) => <div key={name}><FileUp size={19} /><strong>{name}</strong><span><i /></span><small>上传中</small></div>)}</div> : null}
        <div className="ru-document-toolbar"><button type="button" onClick={() => fileInput.current?.click()}><FileUp size={15} />新建上传</button><button type="button" onClick={() => void load()}><RefreshCw size={15} />刷新</button><div><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索文件名" /></div></div>
        {error ? <div className="ru-inline-error">{error}</div> : null}
        <div className="ru-document-table">
          <div className="ru-document-table-head"><span>文件名 / 标题</span><span>版本</span><span>所有者</span><span>解析路由</span><span>切块数</span><span>状态</span><span>操作</span></div>
          {loading ? <div className="ru-data-empty"><RefreshCw className="is-spinning" size={28} /><strong>正在读取文档</strong></div> : null}
          {!loading && visible.length === 0 ? <div className="ru-data-empty"><File size={30} /><strong>暂无可访问文档</strong><span>上传文件后可选择解析方式并提交入库。</span></div> : null}
          {visible.map((item) => (
            <button key={item.id} type="button" className={selected?.id === item.id ? 'is-selected' : ''} onClick={() => selectDocument(item.id)}>
              <span><File size={18} /><span><strong>{item.file_name}</strong><small>{item.title}</small></span></span><span>v{item.version}</span><span>{item.owner_id}</span><span>{item.mode}</span><span>{item.chunk_count || '—'}</span><span className={`ru-doc-status is-${item.status}`}>{item.status}</span><span><ArrowRight size={16} /></span>
            </button>
          ))}
        </div>
      </section>
      <aside className="ru-document-detail">
        {selected ? <><header><File size={19} /><strong>{selected.file_name}</strong></header><section><h3>文档配置</h3><dl><div><dt>知识模式</dt><dd>{selected.mode}</dd></div><div><dt>所有者</dt><dd>{selected.owner_id}</dd></div><div><dt>权限范围</dt><dd>{selected.acl.join('、') || 'private'}</dd></div><div><dt>版本</dt><dd>v{selected.version}</dd></div></dl><button className="ru-outline-command" type="button" onClick={() => navigate(`/app/documents/${selected.id}`)}>打开完整详情 <ArrowRight size={14} /></button></section><section><h3>解析结果</h3><dl><div><dt>切块数量</dt><dd>{selected.chunk_count}</dd></div><div><dt>当前状态</dt><dd>{selected.status}</dd></div><div><dt>处理进度</dt><dd>{selected.ingest_progress ?? 0}/{selected.ingest_total ?? 0}</dd></div></dl>{selected.error ? <p className="ru-detail-error"><XCircle size={15} />{selected.error}</p> : null}<button className="ru-primary-command" type="button" onClick={() => void ingest()} disabled={selected.status === 'processing'}><Database size={16} />{selected.status === 'processing' ? '正在入库' : '提交混合入库'}</button></section></> : <div className="ru-data-empty"><File size={30} /><strong>选择一个文档</strong><span>右侧将显示解析配置与后端状态。</span></div>}
      </aside>
    </div>
  );
}
