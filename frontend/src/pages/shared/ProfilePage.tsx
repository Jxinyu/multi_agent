import { Bell, HelpCircle, KeyRound, LogOut, ShieldCheck, UserRound } from 'lucide-react';
import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';

import { clearAccessToken } from '../../api/auth';
import type { ShellMode } from '../../app/navigation';
import { useAuth } from '../../hooks/useAuth';
import type { CurrentUser } from '../../types';

const basePath = (mode: ShellMode) => mode === 'user' ? '/app' : `/${mode}`;

export function ProfilePage({ mode, currentUser }: { mode: ShellMode; currentUser: CurrentUser | null }) {
  const navigate = useNavigate();
  const auth = useAuth();
  const grouped = useMemo(() => currentUser?.permissions.reduce<Record<string, string[]>>((result, permission) => { const area = permission.split(':')[0] || 'other'; (result[area] ??= []).push(permission); return result; }, {}) ?? {}, [currentUser]);
  const signOut = () => { clearAccessToken(); navigate('/login', { replace: true }); };

  return <div className="ru-utility-page"><header className="ru-utility-title"><div><span>身份与权限</span><h1>个人资料</h1><p>当前会话身份来自访问令牌；权限声明决定可访问的数据与操作。</p></div><button className="is-danger" type="button" onClick={signOut}><LogOut size={16} />退出会话</button></header><div className="ru-profile-layout"><section className="ru-profile-identity"><header><span>{currentUser?.username?.slice(0, 1).toUpperCase() ?? 'U'}</span><div><h2>{currentUser?.username ?? '正在加载身份'}</h2><p>{currentUser?.role ?? '未知角色'}</p></div></header><dl><div><dt>用户 ID</dt><dd>{currentUser?.user_id ?? '—'}</dd></div><div><dt>租户 ID</dt><dd>{currentUser?.tenant_id ?? '—'}</dd></div><div><dt>认证来源</dt><dd>{auth.source === 'oidc' ? 'OIDC 访问令牌' : auth.source === 'development' ? '开发环境令牌' : '未知'}</dd></div><div><dt>会话状态</dt><dd>{auth.status === 'authenticated' ? '已认证' : '未认证'}</dd></div></dl></section><section className="ru-profile-permissions"><header><KeyRound size={17} /><strong>有效权限声明</strong><span>{currentUser?.permissions.length ?? 0} 项</span></header>{Object.entries(grouped).map(([area, permissions]) => <div key={area}><strong>{area.toUpperCase()}</strong><span>{permissions.map((permission) => <code key={permission}>{permission}</code>)}</span></div>)}{!currentUser?.permissions.length ? <div className="ru-utility-empty"><ShieldCheck /><strong>没有权限声明</strong></div> : null}</section><aside className="ru-profile-actions"><button type="button" onClick={() => navigate(`${basePath(mode)}/notifications`)}><Bell /><span><strong>通知中心</strong><small>查看当前任务和风险。</small></span></button><button type="button" onClick={() => navigate(`${basePath(mode)}/help`)}><HelpCircle /><span><strong>帮助与状态</strong><small>查看快捷入口和依赖状态。</small></span></button><div><UserRound /><span><strong>资料修改由身份提供方管理</strong><small>用户名、角色和组织信息不能在应用内伪造修改。</small></span></div></aside></div></div>;
}
