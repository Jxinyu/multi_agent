import { KeyRound, ShieldCheck, UserCheck, Users } from 'lucide-react';
import { useEffect, useState } from 'react';

import { fetchEnterpriseCurrentUser, fetchEnterpriseOverview, type EnterpriseOverview } from '../../api/enterprise';
import type { CurrentUser } from '../../types';

export function EnterpriseMembersPage() {
  const [overview, setOverview] = useState<EnterpriseOverview | null>(null);
  const [user, setUser] = useState<CurrentUser | null>(null);
  useEffect(() => { void Promise.all([fetchEnterpriseOverview(), fetchEnterpriseCurrentUser()]).then(([data, current]) => { setOverview(data); setUser(current); }); }, []);
  return <div className="ru-enterprise-page"><header className="ru-console-title"><div><h1>成员与数据权限</h1><p>身份来源于 JWT 与租户审计；未配置 SCIM 时不生成虚拟成员。</p></div><button type="button" disabled title="需要配置 OIDC SCIM 目录连接"><Users size={16} />邀请成员</button></header><div className="ru-members-layout"><section className="ru-console-panel ru-member-table"><header><strong>已观测身份</strong><span>{overview?.observed_actors.length ?? 0} 个</span></header><div className="ru-member-head"><span>身份 ID</span><span>来源</span><span>最近活动</span><span>状态</span></div>{overview?.observed_actors.map((actor) => { const latest = overview.recent_events.find((event) => event.actor_id === actor); return <div key={actor}><span><UserCheck size={16} /><strong>{actor}</strong></span><span>{actor === user?.user_id ? '当前 JWT' : '审计事件'}</span><time>{latest ? new Date(latest.occurred_at).toLocaleString('zh-CN') : '超出窗口'}</time><span className="is-healthy">已观测</span></div>; })}</section><aside className="ru-console-panel ru-permission-detail"><header><ShieldCheck size={17} /><strong>当前身份有效权限</strong></header><div className="ru-current-identity"><span>{user?.username?.slice(0, 1).toUpperCase() ?? 'U'}</span><div><strong>{user?.username ?? '加载中'}</strong><small>{user?.user_id}</small></div></div><dl><div><dt>租户</dt><dd>{user?.tenant_id}</dd></div><div><dt>角色</dt><dd>{user?.role}</dd></div></dl><h3><KeyRound size={15} />权限声明</h3><div className="ru-permission-list">{user?.permissions.map((permission) => <span key={permission}>{permission}</span>)}</div><p>权限以访问令牌声明为准；成员创建、停用与组同步应由企业 IdP/SCIM 负责。</p></aside></div></div>;
}
