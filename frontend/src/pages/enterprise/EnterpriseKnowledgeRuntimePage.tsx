import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Database,
  FileSearch,
  Network,
  RefreshCw,
  ScanSearch,
  ServerOff,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { fetchKnowledgeIndexRuntime, type KnowledgeIndexRuntime } from '../../api/enterprise';

type Check = KnowledgeIndexRuntime['document_checks'][number];
type Filter = 'all' | Check['state'];

const stateText: Record<Check['state'], string> = {
  consistent: '一致',
  mismatch: '不一致',
  pending: '待处理',
  unknown: '未核验',
};

function actual(value: number | null, expected: boolean): string {
  if (!expected) return value ? `${value}（残留）` : '不适用';
  return value === null ? '未核验' : String(value);
}

function BackendState({ available, scanComplete }: { available: boolean; scanComplete: boolean }) {
  if (!available) return <span className="is-unhealthy"><ServerOff size={14} />不可用</span>;
  if (!scanComplete) return <span className="is-warning"><AlertTriangle size={14} />扫描受限</span>;
  return <span className="is-healthy"><CheckCircle2 size={14} />已核验</span>;
}

export function EnterpriseKnowledgeRuntimePage() {
  const navigate = useNavigate();
  const [data, setData] = useState<KnowledgeIndexRuntime | null>(null);
  const [filter, setFilter] = useState<Filter>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      setData(await fetchKnowledgeIndexRuntime());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '知识索引运行状态加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);
  const visible = useMemo(
    () => data?.document_checks.filter((item) => filter === 'all' || item.state === filter) ?? [],
    [data, filter],
  );
  const mismatches = data?.state_counts.mismatch ?? 0;
  const cannotVerify = data && (!data.milvus.available || !data.neo4j.available
    || !data.milvus.scan_complete || !data.neo4j.scan_complete);

  return (
    <div className="ru-enterprise-page ru-index-runtime-page">
      <header className="ru-console-title ru-detail-title">
        <button type="button" title="返回知识与解析" aria-label="返回知识与解析" onClick={() => navigate('/enterprise/knowledge')}>
          <ArrowLeft size={17} />
        </button>
        <div>
          <h1>知识索引运行详情</h1>
          <p>核对当前租户的文档元数据、Milvus 切片与 Neo4j 图谱写入结果。</p>
        </div>
        <button type="button" disabled={loading} onClick={() => void load()}>
          <RefreshCw className={loading ? 'is-spinning' : ''} size={16} />刷新
        </button>
      </header>

      {error ? <div className="ru-detail-error"><AlertTriangle size={20} /><strong>状态读取失败</strong><span>{error}</span><button type="button" onClick={() => void load()}>重新读取</button></div> : null}
      {loading && !data ? <div className="ru-detail-loading"><RefreshCw className="is-spinning" size={18} />正在查询两个索引后端</div> : null}
      {data ? (
        <>
          <section className="ru-index-kpis" aria-label="索引运行摘要">
            <div><Database /><span>租户文档<strong>{data.document_count}</strong><small>{data.ready_document_count} 份已就绪</small></span></div>
            <div><ScanSearch /><span>一致性异常<strong className={mismatches ? 'is-danger' : ''}>{mismatches}</strong><small>{data.orphan_document_count} 份索引残留</small></span></div>
            <div><FileSearch /><span>Milvus 切片<strong>{data.milvus.indexed_chunks ?? '—'}</strong><small>元数据期望 {data.expected_vector_chunks}</small></span></div>
            <div><Network /><span>Neo4j 切片<strong>{data.neo4j.indexed_chunks ?? '—'}</strong><small>元数据期望 {data.expected_graph_chunks}</small></span></div>
          </section>

          {mismatches ? <div className="ru-index-alert is-danger"><AlertTriangle size={17} /><span><strong>发现 {mismatches} 份文档索引不一致</strong>其中 {data.orphan_document_count} 份仅存在于索引；请先核对任务终态和对应后端，再决定是否重新入库或清理残留。</span></div> : null}
          {cannotVerify ? <div className="ru-index-alert is-warning"><ServerOff size={17} /><span><strong>本次核验不完整</strong>不可用后端或扫描上限内无法完成核对的文档会标记为“未核验”，不会判定为成功。</span></div> : null}

          <div className="ru-index-backends">
            <section className="ru-console-panel ru-index-backend">
              <header><strong><FileSearch size={16} />Milvus 向量索引</strong><BackendState available={data.milvus.available} scanComplete={data.milvus.scan_complete} /></header>
              <dl>
                <div><dt>业务集合</dt><dd>{data.milvus.collection_name}</dd></div>
                <div><dt>租户切片</dt><dd>{data.milvus.indexed_chunks ?? '未读取'}</dd></div>
                <div><dt>租户文档</dt><dd>{data.milvus.indexed_documents ?? '未完成扫描'}</dd></div>
                <div><dt>向量维度</dt><dd>{data.milvus.embedding_dimensions ?? '未读取'}</dd></div>
                <div><dt>稀疏检索</dt><dd>{data.milvus.sparse_search_enabled === null ? '未读取' : data.milvus.sparse_search_enabled ? '已启用' : '未启用'}</dd></div>
              </dl>
              {data.milvus.error ? <p>{data.milvus.error}</p> : null}
            </section>

            <section className="ru-console-panel ru-index-backend">
              <header><strong><Network size={16} />Neo4j 图谱索引</strong><BackendState available={data.neo4j.available} scanComplete={data.neo4j.scan_complete} /></header>
              <dl>
                <div><dt>租户切片</dt><dd>{data.neo4j.indexed_chunks ?? '未读取'}</dd></div>
                <div><dt>租户文档</dt><dd>{data.neo4j.indexed_documents ?? '未读取'}</dd></div>
                <div><dt>实体节点</dt><dd>{data.neo4j.entity_count ?? '未读取'}</dd></div>
                <div><dt>租户关系</dt><dd>{data.neo4j.relationship_count ?? '未读取'}</dd></div>
                <div><dt>文档扫描</dt><dd>{data.neo4j.scan_complete ? '完整' : '未完成'}</dd></div>
              </dl>
              {data.neo4j.error ? <p>{data.neo4j.error}</p> : null}
            </section>
          </div>

          <section className="ru-console-panel ru-index-checks">
            <header>
              <div><strong>文档级一致性</strong><span>{data.document_checks.length} 条可见记录</span></div>
              <div className="ru-index-filters" aria-label="一致性筛选">
                {(['all', 'mismatch', 'unknown', 'pending', 'consistent'] as Filter[]).map((item) => (
                  <button className={filter === item ? 'is-active' : ''} key={item} type="button" onClick={() => setFilter(item)}>
                    {item === 'all' ? '全部' : stateText[item]}
                  </button>
                ))}
              </div>
            </header>
            <div className="ru-index-check-head"><span>文档</span><span>状态</span><span>期望切片</span><span>Milvus</span><span>Neo4j</span><span>核验说明</span><span /></div>
            {visible.map((item) => (
              <button
                className={`ru-index-check-row is-${item.state}`}
                disabled={item.status === 'orphaned'}
                key={item.document_id}
                title={item.status === 'orphaned' ? '业务文档记录不存在，无法打开详情' : `打开 ${item.file_name} 详情`}
                type="button"
                onClick={() => navigate(`/enterprise/knowledge/${item.document_id}`)}
              >
                <span><strong>{item.file_name}</strong><small>{item.mode} · {item.status}</small></span>
                <em>{stateText[item.state]}</em>
                <span>{item.expected_chunks}</span>
                <span>{actual(item.vector_chunks, item.vector_expected)}</span>
                <span>{actual(item.graph_chunks, item.graph_expected)}</span>
                <span>{item.issue ?? '元数据与实际索引一致'}</span>
                {item.status === 'orphaned' ? <span /> : <ArrowRight size={14} />}
              </button>
            ))}
            {!visible.length ? <div className="ru-data-empty"><CheckCircle2 size={28} /><strong>当前筛选下没有记录</strong><span>切换筛选条件查看其他核验结果。</span></div> : null}
          </section>

          {!data.document_checks_complete ? <div className="ru-index-alert is-warning"><AlertTriangle size={17} /><span><strong>文档级核验范围受限</strong>文档超过 100 份或后端扫描未完成时，本页只返回可确认的优先记录；摘要计数仍覆盖当前租户业务文档。</span></div> : null}
          <p className="ru-index-observation"><strong>数据口径</strong>{data.observation_note} 核验时间：{new Date(data.checked_at).toLocaleString('zh-CN')}</p>
        </>
      ) : null}
    </div>
  );
}
