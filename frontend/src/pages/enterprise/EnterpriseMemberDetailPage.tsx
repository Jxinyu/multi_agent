import { Activity, ArrowLeft, CalendarClock, CircleSlash2, KeyRound, RefreshCw, ShieldCheck, UserCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { fetchObservedMemberDetail, type ObservedMemberDetail } from '../../api/enterprise';

const time = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '当前窗口无记录';

export function EnterpriseMemberDetailPage() {
  const navigate = useNavigate();
  const { actorId = '' } = useParams();
  const [detail, setDetail] = useState<ObservedMemberDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try { setDetail(await fetchObservedMemberDetail(actorId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '身份详情加载失败'); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [actorId]);

  if (loading) return <div className="ru-enterprise-page"><div className="ru-detail-loading"><RefreshCw className="ru-spin" /><strong>正在汇总租户身份活动</strong></div></div>;
  if (error || !detail) return <div className="ru-enterprise-page"><div className="ru-detail-error"><CircleSlash2 /><strong>无法打开身份详情</strong><span>{error || '身份不存在'}</span><button type="button" onClick={() => void load()}>重试</button></div></div>;

  return <div className="ru-enterprise-page ru-member-detail-page">
    <header className="ru-console-title ru-detail-title"><button type="button" onClick={() => navigate('/enterprise/members')}><ArrowLeft size={16} />返回成员</button><div><h1>已观测身份详情</h1><p>{detail.actor_id}</p></div><button type="button" onClick={() => void load()}><RefreshCw size={16} />刷新</button></header>

    <section className="ru-member-detail-hero">
      <span className="ru-member-avatar">{detail.actor_id.slice(0, 1).toUpperCase()}</span>
      <div><small>{detail.is_current_user ? '当前登录身份' : '审计中已观测身份'}</small><h2>{detail.actor_id}</h2><p>{detail.identity_source} · {detail.actor_type}</p></div>
      <span className={detail.directory_managed ? 'is-healthy' : 'is-muted'}>{detail.directory_managed ? <ShieldCheck size={16} /> : <CircleSlash2 size={16} />}{detail.directory_managed ? '目录已托管' : '未接入 SCIM 目录'}</span>
    </section>

    <section className="ru-member-activity-kpis">
      <div><Activity /><span>审计窗口事件<strong>{detail.event_count}</strong></span></div>
      <div><CalendarClock /><span>首次观测<strong>{time(detail.first_seen_at)}</strong></span></div>
      <div><CalendarClock /><span>最近活动<strong>{time(detail.last_seen_at)}</strong></span></div>
      <div><ShieldCheck /><span>窗口范围<strong>{detail.window_complete ? '当前记录完整' : '超过 200 条'}</strong></span></div>
    </section>

    <div className="ru-member-detail-grid">
      <section className="ru-console-panel ru-member-claims"><header><strong><KeyRound size={16} />身份声明</strong><span>{detail.is_current_user ? '当前令牌' : '不可推测'}</span></header><dl><div><dt>角色</dt><dd>{detail.role ?? '未由目录或令牌确认'}</dd></div><div><dt>组</dt><dd>{detail.groups.length ? detail.groups.join('、') : '未确认'}</dd></div></dl><h3>有效权限</h3>{detail.permissions.length ? <div className="ru-permission-list">{detail.permissions.map((permission) => <span key={permission}>{permission}</span>)}</div> : <p>非当前身份无法从审计事件推断角色和权限；需要接入企业 IdP/SCIM 后读取。</p>}</section>
      <section className="ru-console-panel ru-member-outcomes"><header><strong><ShieldCheck size={16} />结果分布</strong><span>{detail.outcomes.length} 类</span></header>{detail.outcomes.length ? detail.outcomes.map((item) => <div key={item.id}><span className={`is-${item.id}`}>{item.id}</span><strong>{item.count}</strong></div>) : <p>当前窗口没有审计结果。</p>}</section>
      <section className="ru-console-panel ru-member-actions"><header><strong><UserCheck size={16} />常用操作</strong><span>最多 8 项</span></header>{detail.actions.length ? detail.actions.map((item) => <div key={item.id}><code>{item.id}</code><strong>{item.count}</strong></div>) : <p>当前窗口没有操作记录。</p>}</section>
      <section className="ru-console-panel ru-member-recent-events"><header><strong><Activity size={16} />最近活动</strong><span>{detail.recent_events.length} 条</span></header>{detail.recent_events.length ? detail.recent_events.map((event) => <div key={event.id}><time>{new Date(event.occurred_at).toLocaleString('zh-CN')}</time><strong>{event.action}</strong><span className={`is-${event.outcome}`}>{event.outcome}</span><small>{event.resource_type}</small></div>) : <p>当前登录身份尚无审计活动。</p>}</section>
    </div>
  </div>;
}
