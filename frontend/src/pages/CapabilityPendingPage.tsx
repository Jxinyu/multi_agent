import { AlertTriangle, Cable, LockKeyhole } from 'lucide-react';

interface CapabilityPendingPageProps {
  scope: 'user' | 'enterprise' | 'admin';
  capability: string;
}

export function CapabilityPendingPage({ scope, capability }: CapabilityPendingPageProps) {
  const scopeLabel = scope === 'user' ? '用户端' : scope === 'enterprise' ? '企业端' : '平台管理端';

  return (
    <section className="ru-pending-page">
      <header><span>{scopeLabel}</span><h1>{capability}</h1></header>
      <div className="ru-pending-status" role="status">
        <AlertTriangle size={22} />
        <div><strong>主流程尚未接通</strong><p>该路由已经纳入三端权限边界，但对应服务端接口仍在实施中，当前不会返回模拟成功数据。</p></div>
      </div>
      <div className="ru-pending-checks">
        <div><Cable size={18} /><strong>接口契约</strong><span>待接入并验证</span></div>
        <div><LockKeyhole size={18} /><strong>权限范围</strong><span>按租户和角色校验</span></div>
      </div>
    </section>
  );
}
