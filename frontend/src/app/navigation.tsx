import {
  Activity,
  Bot,
  Building2,
  ClipboardCheck,
  Database,
  FileSearch,
  Files,
  Gauge,
  KeyRound,
  LayoutDashboard,
  Search,
  Settings,
  ShieldCheck,
  Users
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export type ShellMode = 'user' | 'enterprise' | 'admin';

export interface NavigationItem {
  label: string;
  to: string;
  icon: LucideIcon;
  end?: boolean;
}

export const navigationByMode: Record<ShellMode, NavigationItem[]> = {
  user: [
    { label: 'AI 工作台', to: '/app', icon: Bot, end: true },
    { label: '企业搜索', to: '/app/search', icon: Search },
    { label: '任务与追问', to: '/app/tasks', icon: ClipboardCheck },
    { label: '我的文档', to: '/app/documents', icon: Files }
  ],
  enterprise: [
    { label: '总览', to: '/enterprise', icon: LayoutDashboard, end: true },
    { label: '知识与解析', to: '/enterprise/knowledge', icon: Database },
    { label: '智能体与 MCP', to: '/enterprise/agents', icon: Bot },
    { label: '成员与权限', to: '/enterprise/members', icon: Users },
    { label: '评测与成本', to: '/enterprise/evaluation', icon: Gauge }
  ],
  admin: [
    { label: '租户与配额', to: '/admin/tenants', icon: Building2 },
    { label: '审计与安全', to: '/admin/security', icon: ShieldCheck },
    { label: '系统运行', to: '/admin/operations', icon: Activity },
    { label: '模型与容量', to: '/admin/models', icon: FileSearch },
    { label: '平台配置', to: '/admin/settings', icon: Settings }
  ]
};

export const modeMeta: Record<ShellMode, { label: string; switchLabel: string; switchTo: string; switchIcon: LucideIcon }> = {
  user: { label: '员工工作区', switchLabel: '进入企业控制台', switchTo: '/enterprise', switchIcon: KeyRound },
  enterprise: { label: '企业控制台', switchLabel: '返回用户端', switchTo: '/app', switchIcon: Bot },
  admin: { label: '平台管理', switchLabel: '进入企业控制台', switchTo: '/enterprise', switchIcon: Building2 }
};
