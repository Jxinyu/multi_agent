import { ArrowRight, Database, FileText, RefreshCw, Search, Upload } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { uploadKnowledgeBaseDocuments } from '../../api/admin';
import { fetchEnterpriseDocuments } from '../../api/enterprise';
import type { KnowledgeBaseItem } from '../../types';

export function EnterpriseKnowledgePage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<KnowledgeBaseItem[]>([]);
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const load = async () => { try { const result = await fetchEnterpriseDocuments(); setItems(result); setSelectedId((id) => id ?? result[0]?.id ?? null); } catch (reason) { setError(reason instanceof Error ? reason.message : '加载失败'); } };
  useEffect(() => { void load(); }, []);
  const visible = useMemo(() => items.filter((item) => `${item.title}${item.file_name}`.toLowerCase().includes(query.toLowerCase())), [items, query]);
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const upload = async (files: FileList | null) => { if (!files?.length) return; const form = new FormData(); Array.from(files).forEach((file) => form.append('files', file)); form.append('mode', 'hybrid'); try { await uploadKnowledgeBaseDocuments(form); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : '上传失败'); } };
  const complete = items.filter((item) => item.status === 'completed' || item.status === 'ready').length;
  const selectDocument = (documentId: string) => {
    setSelectedId(documentId);
    if (window.matchMedia('(max-width: 760px)').matches) navigate(`/enterprise/knowledge/${documentId}`);
  };

  return <div className="ru-enterprise-page"><header className="ru-console-title"><div><h1>知识与解析</h1><p>管理租户文档、解析路由与双后端入库状态。</p></div><button type="button" onClick={() => inputRef.current?.click()}><Upload size={16} />导入文档</button><input ref={inputRef} hidden multiple type="file" onChange={(event) => void upload(event.target.files)} /></header><section className="ru-knowledge-summary"><div><Database size={18} /><span>文档总数<strong>{items.length}</strong></span></div><div><FileText size={18} /><span>健康文档<strong>{complete}</strong></span></div><div><RefreshCw size={18} /><span>处理中<strong>{items.filter((item) => item.status === 'processing').length}</strong></span></div></section>{error ? <div className="ru-inline-error">{error}</div> : null}<div className="ru-knowledge-layout"><section className="ru-console-panel ru-knowledge-table"><header><div><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索文档名称" /></div><button type="button" onClick={() => void load()}><RefreshCw size={14} />刷新</button></header><div className="ru-knowledge-head"><span>文档</span><span>版本</span><span>解析路由</span><span>切块</span><span>权限</span><span>状态</span></div>{visible.length ? visible.map((item) => <button key={item.id} className={selectedId === item.id ? 'is-selected' : ''} type="button" onClick={() => selectDocument(item.id)}><span><FileText size={15} /><strong>{item.title || item.file_name}</strong></span><span>v{item.version}</span><span>{item.mode}</span><span>{item.chunk_count}</span><span>{item.acl.join('、')}</span><span className={`ru-doc-status is-${item.status}`}>{item.status}</span></button>) : <div className="ru-data-empty"><FileText size={28} /><strong>暂无文档</strong><span>导入文档后可跟踪解析和入库状态。</span></div>}</section><aside className="ru-console-panel ru-knowledge-detail">{selected ? <><header><FileText size={18} /><strong>{selected.file_name}</strong></header><h3>智能解析路由</h3><div className="ru-parser-route"><span>上传</span><i /><span>{selected.mode}</span><i /><span>Milvus</span><i /><span>Neo4j</span></div><dl><div><dt>所有者</dt><dd>{selected.owner_id}</dd></div><div><dt>切块数量</dt><dd>{selected.chunk_count}</dd></div><div><dt>处理进度</dt><dd>{selected.ingest_progress ?? 0}/{selected.ingest_total ?? 0}</dd></div><div><dt>校验摘要</dt><dd>{selected.checksum.slice(0, 12)}</dd></div></dl><button className="ru-outline-command" type="button" onClick={() => navigate(`/enterprise/knowledge/${selected.id}`)}>打开完整详情 <ArrowRight size={14} /></button></> : <div className="ru-data-empty"><FileText size={28} /><strong>选择文档查看解析详情</strong></div>}</aside></div></div>;
}
