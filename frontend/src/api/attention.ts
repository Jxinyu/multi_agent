import type { ShellMode } from '../app/navigation';
import { fetchDependencyHealth, fetchEnterpriseOverview } from './enterprise';
import { fetchAuditEvents, fetchRuntimeStatus } from './platform';
import { fetchUserDocuments, fetchUserTasks } from './user';

export type AttentionSeverity = 'critical' | 'warning' | 'info';

export interface AttentionItem {
  id: string;
  severity: AttentionSeverity;
  title: string;
  detail: string;
  occurredAt?: string;
  actionLabel: string;
  actionPath: string;
}

async function fetchUserAttention(): Promise<AttentionItem[]> {
  const [tasks, documents] = await Promise.all([fetchUserTasks(), fetchUserDocuments()]);
  const taskItems = tasks
    .filter((task) => ['waiting', 'failed', 'cancelled', 'running'].includes(task.status))
    .map((task): AttentionItem => ({
      id: `task:${task.id}`,
      severity: task.status === 'failed' || task.status === 'cancelled' ? 'critical' : task.status === 'waiting' ? 'warning' : 'info',
      title: task.status === 'waiting' ? '会话等待补充信息' : task.status === 'running' ? '多智能体任务正在运行' : '会话任务未正常完成',
      detail: `任务 ${task.id} 当前状态：${task.status}`,
      occurredAt: task.updated_at,
      actionLabel: task.status === 'waiting' ? '立即处理' : '查看任务',
      actionPath: '/app/tasks'
    }));
  const documentItems = documents
    .filter((document) => ['failed', 'delete_failed', 'processing'].includes(document.status))
    .map((document): AttentionItem => ({
      id: `document:${document.id}`,
      severity: document.status === 'processing' ? 'info' : 'critical',
      title: document.status === 'processing' ? '文档正在解析入库' : '文档处理失败',
      detail: `${document.file_name}：${document.error || document.status}`,
      occurredAt: document.upload_time,
      actionLabel: '查看文档',
      actionPath: '/app/documents'
    }));
  return [...taskItems, ...documentItems];
}

async function fetchEnterpriseAttention(): Promise<AttentionItem[]> {
  const [overview, health] = await Promise.all([fetchEnterpriseOverview(), fetchDependencyHealth()]);
  const items: AttentionItem[] = [];
  if (overview.failed_count) items.push({ id: 'enterprise:failed', severity: 'critical', title: '存在失败或中断会话', detail: `最近审计窗口内共 ${overview.failed_count} 个失败或中断会话。`, actionLabel: '查看总览', actionPath: '/enterprise' });
  if (overview.waiting_count) items.push({ id: 'enterprise:waiting', severity: 'warning', title: '会话等待人工补充', detail: `当前有 ${overview.waiting_count} 个会话等待用户提供信息。`, actionLabel: '查看总览', actionPath: '/enterprise' });
  const unhealthyDocuments = overview.document_count - overview.healthy_document_count;
  if (unhealthyDocuments > 0) items.push({ id: 'enterprise:documents', severity: 'warning', title: '知识文档未处于健康状态', detail: `${unhealthyDocuments} 个文档尚未完成或处理失败。`, actionLabel: '检查知识库', actionPath: '/enterprise/knowledge' });
  Object.entries(health).filter(([, ok]) => !ok).forEach(([name]) => items.push({ id: `enterprise:health:${name}`, severity: 'critical', title: '企业依赖探针异常', detail: `${name} 当前未通过就绪检查。`, actionLabel: '查看运行状态', actionPath: '/enterprise' }));
  return items;
}

async function fetchAdminAttention(): Promise<AttentionItem[]> {
  const [runtime, failedEvents, deniedEvents] = await Promise.all([
    fetchRuntimeStatus(),
    fetchAuditEvents({ outcome: 'failure' }),
    fetchAuditEvents({ outcome: 'denied' })
  ]);
  const serviceItems = runtime.services.filter((service) => !service.ok).map((service): AttentionItem => ({
    id: `admin:service:${service.name}`,
    severity: 'critical',
    title: '平台服务探针异常',
    detail: `${service.name}：${service.detail}`,
    actionLabel: '查看系统运行',
    actionPath: '/admin/operations'
  }));
  const auditItems = [...failedEvents.items.slice(0, 8), ...deniedEvents.items.slice(0, 8)].map((event): AttentionItem => ({
    id: `admin:audit:${event.id}`,
    severity: event.outcome === 'denied' ? 'warning' : 'critical',
    title: event.outcome === 'denied' ? '访问请求被拒绝' : '平台操作执行失败',
    detail: `${event.actor_id} 执行 ${event.action}，资源类型 ${event.resource_type}。`,
    occurredAt: event.occurred_at,
    actionLabel: '调查审计事件',
    actionPath: '/admin/security'
  }));
  return [...serviceItems, ...auditItems];
}

export async function fetchAttentionItems(mode: ShellMode): Promise<AttentionItem[]> {
  if (mode === 'user') return fetchUserAttention();
  if (mode === 'enterprise') return fetchEnterpriseAttention();
  return fetchAdminAttention();
}
