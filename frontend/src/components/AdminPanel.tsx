import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  CloudUpload,
  Database,
  FileText,
  Layers3,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Trash2,
  UploadCloud,
  Users,
  Zap
} from 'lucide-react';

import {
  bulkDeleteKnowledgeBaseDocuments,
  bulkIngestKnowledgeBaseDocuments,
  deleteKnowledgeBase,
  deleteKnowledgeBaseDocument,
  fetchCurrentUser,
  fetchKnowledgeBaseItems,
  ingestKnowledgeBaseDocument,
  uploadKnowledgeBaseDocumentsResumable
} from '../api/admin';
import type { CurrentUser, KnowledgeBaseItem } from '../types';

function formatDate(value: string): string {
  return new Date(value).toLocaleString('zh-CN');
}

const adminModules = [
  { id: 'overview', label: '总览', icon: BarChart3 },
  { id: 'knowledge', label: '知识库管理', icon: Database, active: true },
  { id: 'users', label: '用户与权限', icon: Users },
  { id: 'audit', label: '审计日志', icon: ShieldCheck },
  { id: 'settings', label: '系统设置', icon: Settings }
];

export function AdminPanel() {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [items, setItems] = useState<KnowledgeBaseItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [title, setTitle] = useState('');
  const [mode, setMode] = useState<'rag' | 'graphrag'>('rag');
  const [uploadStrategy, setUploadStrategy] = useState<'upload-only' | 'upload-and-ingest'>('upload-only');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [confirmAction, setConfirmAction] = useState<null | 'delete-all' | 'delete-selected' | 'upload'>(null);
  const [query, setQuery] = useState('');
  const [uploadProgress, setUploadProgress] = useState<{ fileName: string; percent: number } | null>(null);
  const timerRef = useRef<number | null>(null);

  const filteredItems = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return items.filter((item) => {
      if (!keyword) return true;
      return [item.title, item.file_name, item.tenant_id, item.owner_id, item.status, item.mode].some((value) =>
        String(value ?? '').toLowerCase().includes(keyword)
      );
    });
  }, [items, query]);

  const stats = useMemo(
    () => ({
      total: filteredItems.length,
      ready: filteredItems.filter((item) => item.status === 'completed').length,
      failed: filteredItems.filter((item) => item.status === 'error').length,
      processing: filteredItems.filter((item) => item.status === 'processing').length
    }),
    [filteredItems]
  );

  const refresh = async () => {
    setLoading(true);
    setError('');
    try {
      const [user, documents] = await Promise.all([fetchCurrentUser(), fetchKnowledgeBaseItems()]);
      setCurrentUser(user);
      setItems(documents);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, []);

  useEffect(() => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = window.setInterval(() => {
      void refresh();
    }, 5000);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, []);

  const submitUpload = async () => {
    if (!selectedFiles.length) return;
    setError('');
    setUploadProgress({ fileName: selectedFiles[0]?.name ?? '', percent: 0 });
    try {
      const uploadedItems = await uploadKnowledgeBaseDocumentsResumable(selectedFiles, {
        title,
        mode,
        onProgress: ({ fileName, percent }) => setUploadProgress({ fileName, percent })
      });
      if (uploadStrategy === 'upload-and-ingest' && uploadedItems.length > 0) {
        await bulkIngestKnowledgeBaseDocuments(uploadedItems.map((item) => item.id), mode);
      }
      setSelectedFiles([]);
      setTitle('');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : '上传失败');
    } finally {
      setUploadProgress(null);
    }
  };

  const handleIngest = async (item: KnowledgeBaseItem, ingestMode: 'rag' | 'graphrag') => {
    await ingestKnowledgeBaseDocument(item.id, ingestMode);
    await refresh();
  };

  const handleBulkIngest = async () => {
    if (!selectedIds.length) return;
    await bulkIngestKnowledgeBaseDocuments(selectedIds, mode);
    setSelectedIds([]);
    await refresh();
  };

  const handleBulkDelete = async () => {
    if (!selectedIds.length) return;
    await bulkDeleteKnowledgeBaseDocuments(selectedIds);
    setSelectedIds([]);
    await refresh();
  };

  const handleClearKnowledgeBase = async () => {
    await deleteKnowledgeBase();
    setSelectedIds([]);
    await refresh();
  };

  const handleDeleteDocument = async (id: string) => {
    await deleteKnowledgeBaseDocument(id);
    setSelectedIds((current) => current.filter((selectedId) => selectedId !== id));
    await refresh();
  };

  return (
    <div className="admin-page-shell">
      <aside className="admin-sidebar">
        <div className="admin-sidebar-title">Admin Console</div>
        <nav className="admin-nav">
          {adminModules.map((module) => {
            const Icon = module.icon;
            return (
              <button key={module.id} type="button" className={`admin-nav-item ${module.active ? 'active' : ''}`}>
                <Icon size={16} />
                <span>{module.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="admin-content">
        <section className="admin-hero">
          <div>
            <div className="admin-breadcrumb">后台管理 / 知识库管理</div>
            <h1>知识库管理</h1>
            <p>当前为模拟登录模式。上传文档时系统会自动使用当前用户 ID、租户 ID 和默认 ACL，不再要求人工填写租户信息。</p>
          </div>
          <div className="admin-hero-actions">
            <button type="button" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw size={14} />
              {loading ? '刷新中' : '刷新数据'}
            </button>
            <button type="button" className="danger" onClick={() => setConfirmAction('delete-all')}>
              <Trash2 size={14} />
              清空当前租户知识库
            </button>
          </div>
        </section>

        <section className="admin-context-card">
          <div>
            <span>当前用户</span>
            <strong>{currentUser?.username ?? '加载中'}</strong>
          </div>
          <div>
            <span>用户 ID</span>
            <strong>{currentUser?.user_id ?? '-'}</strong>
          </div>
          <div>
            <span>租户 ID</span>
            <strong>{currentUser?.tenant_id ?? '-'}</strong>
          </div>
          <div>
            <span>角色</span>
            <strong>{currentUser?.role ?? '-'}</strong>
          </div>
        </section>

        <section className="admin-metrics">
          <div className="metric-card"><span>文档总数</span><strong>{stats.total}</strong></div>
          <div className="metric-card success"><span>已入库</span><strong>{stats.ready}</strong></div>
          <div className="metric-card warning"><span>处理中</span><strong>{stats.processing}</strong></div>
          <div className="metric-card danger-metric"><span>失败</span><strong>{stats.failed}</strong></div>
        </section>

        <section className="admin-section-grid">
          <div className="admin-card upload-card upload-card-modern">
            <div className="upload-card-head">
              <div className="upload-icon-wrap"><CloudUpload size={20} /></div>
              <div>
                <div className="admin-card-title upload-title">文档上传</div>
                <p>选择文件后可仅保存文档，也可以上传后立即同步入知识库。</p>
              </div>
            </div>

            <div className="admin-form upload-form-modern">
              <label className={`upload-dropzone ${selectedFiles.length ? 'has-files' : ''}`}>
                <input type="file" multiple onChange={(e) => setSelectedFiles(Array.from(e.target.files ?? []))} />
                <UploadCloud size={24} />
                <strong>{selectedFiles.length ? `已选择 ${selectedFiles.length} 个文件` : '点击选择或拖拽文件'}</strong>
                <span>{selectedFiles.length ? selectedFiles.map((file) => file.name).join('、') : '支持 PDF、Word、Excel、Markdown、图片等业务资料'}</span>
              </label>

              <input className="admin-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="标题前缀（可选）" />

              <div className="upload-mode-field">
                <span>入库管线</span>
                <select value={mode} onChange={(e) => setMode(e.target.value as 'rag' | 'graphrag')}>
                  <option value="rag">RAG</option>
                  <option value="graphrag">graphRAG</option>
                </select>
              </div>

              <div className="upload-strategy-group" role="radiogroup" aria-label="上传处理方式">
                <button
                  type="button"
                  className={`upload-strategy-card ${uploadStrategy === 'upload-only' ? 'active' : ''}`}
                  onClick={() => setUploadStrategy('upload-only')}
                >
                  <FileText size={16} />
                  <strong>仅上传文档</strong>
                  <span>保存到后台列表，稍后手动执行入库。</span>
                </button>
                <button
                  type="button"
                  className={`upload-strategy-card ${uploadStrategy === 'upload-and-ingest' ? 'active' : ''}`}
                  onClick={() => setUploadStrategy('upload-and-ingest')}
                >
                  <Zap size={16} />
                  <strong>上传并同步入库</strong>
                  <span>上传完成后立即按当前管线写入知识库。</span>
                </button>
              </div>

              <div className="admin-form-note upload-owner-note">
                自动归属到租户 <strong>{currentUser?.tenant_id ?? '-'}</strong>，所有者 <strong>{currentUser?.user_id ?? '-'}</strong>。上传采用分片断点续传，网络中断后可重新上传同一文件继续处理。
              </div>
              {uploadProgress ? (
                <div className="upload-progress">
                  <div className="upload-progress-text">
                    <span>{uploadProgress.fileName}</span>
                    <strong>{uploadProgress.percent}%</strong>
                  </div>
                  <div className="upload-progress-bar"><span style={{ width: `${uploadProgress.percent}%` }} /></div>
                </div>
              ) : null}
              <button type="button" className="primary-admin-button upload-submit-button" onClick={() => setConfirmAction('upload')} disabled={!selectedFiles.length || Boolean(uploadProgress)}>
                {uploadStrategy === 'upload-and-ingest' ? '上传并入库' : '上传文件'}
              </button>
            </div>
          </div>

          <div className="admin-card table-card">
            <div className="table-card-header">
              <div className="admin-card-title"><Database size={16} />文档列表</div>
              <span className="selection-hint">已选择 {selectedIds.length} 项</span>
            </div>

            <div className="admin-filter-bar">
              <label className="admin-search">
                <Search size={15} />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索标题、文件名、状态或模式" />
              </label>
              <button type="button" onClick={() => void handleBulkIngest()} disabled={!selectedIds.length}>
                <Layers3 size={14} />批量入库
              </button>
              <button type="button" className="danger" onClick={() => setConfirmAction('delete-selected')} disabled={!selectedIds.length}>
                <Trash2 size={14} />批量删除
              </button>
            </div>

            {error ? <div className="admin-error"><AlertTriangle size={14} />{error}</div> : null}

            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th><input type="checkbox" checked={filteredItems.length > 0 && selectedIds.length === filteredItems.length} onChange={(e) => setSelectedIds(e.target.checked ? filteredItems.map((item) => item.id) : [])} /></th>
                    <th>文档</th>
                    <th>所有者</th>
                    <th>租户</th>
                    <th>模式</th>
                    <th>状态</th>
                    <th>Chunks</th>
                    <th>上传时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.length === 0 ? (
                    <tr><td colSpan={9} className="admin-empty-cell"><FileText size={18} />暂无文档</td></tr>
                  ) : (
                    filteredItems.map((item) => (
                      <tr key={item.id}>
                        <td><input type="checkbox" checked={selectedIds.includes(item.id)} onChange={(e) => setSelectedIds((current) => e.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} /></td>
                        <td>
                          <div className="doc-title">{item.title}</div>
                          <div className="doc-meta">{item.file_name}</div>
                          {item.ingest_message ? <div className="doc-note">{item.ingest_message}</div> : null}
                          {item.error ? <div className="admin-error-inline">{item.error}</div> : null}
                        </td>
                        <td>{item.owner_id}</td>
                        <td>{item.tenant_id}</td>
                        <td>{item.mode}</td>
                        <td><span className={`status-tag status-${item.status}`}>{item.status}</span></td>
                        <td>{item.chunk_count}</td>
                        <td>{formatDate(item.upload_time)}</td>
                        <td>
                          <div className="table-actions">
                            <button type="button" onClick={() => void handleIngest(item, 'rag')}>RAG</button>
                            <button type="button" onClick={() => void handleIngest(item, 'graphrag')}>graphRAG</button>
                            <button type="button" className="danger" onClick={() => void handleDeleteDocument(item.id)}>删除</button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </main>

      {confirmAction ? (
        <div className="confirm-modal">
          <div className="confirm-card">
            <h3>请确认操作</h3>
            <p>
              {confirmAction === 'delete-all' && '此操作会清空当前租户知识库，无法恢复。'}
              {confirmAction === 'delete-selected' && `此操作会删除当前租户下 ${selectedIds.length} 个文档。`}
              {confirmAction === 'upload' && `将上传 ${selectedFiles.length} 个文件到当前租户${uploadStrategy === 'upload-and-ingest' ? '，并立即同步入知识库。' : '。'}`}
            </p>
            <div className="confirm-actions">
              <button type="button" onClick={() => setConfirmAction(null)}>取消</button>
              <button type="button" className="danger" onClick={async () => { try { if (confirmAction === 'upload') await submitUpload(); if (confirmAction === 'delete-selected') await handleBulkDelete(); if (confirmAction === 'delete-all') await handleClearKnowledgeBase(); } finally { setConfirmAction(null); } }}>确认</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
