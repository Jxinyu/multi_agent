export const jobStatusLabel: Record<string, string> = {
  queued: '等待执行',
  processing: '执行中',
  succeeded: '已成功',
  failed: '已失败'
};

export const jobOperationLabel: Record<string, string> = {
  ingest: '文档入库',
  delete: '文档清理'
};

export const jobModeLabel: Record<string, string> = {
  milvus: 'Milvus 向量入库',
  graph: 'Neo4j 图谱入库',
  mg: 'Milvus + Neo4j 双路入库'
};

export const isActiveJob = (status: string) => status === 'queued' || status === 'processing';
