import { Building2, Check, ExternalLink, KeyRound, RefreshCw, ShieldCheck } from 'lucide-react';
import { useState } from 'react';

interface LoginPageProps {
  error?: string;
  onRetry: () => Promise<void>;
}

export function LoginPage({ error, onRetry }: LoginPageProps) {
  const [busy, setBusy] = useState(false);

  const retry = async () => {
    setBusy(true);
    try {
      await onRetry();
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="ru-login-page">
      <aside className="ru-login-rail">
        <div className="ru-brand">RAG UPPER</div>
        <section><small>01 产品</small><strong><Building2 size={19} />多智能体知识系统</strong></section>
        <section><small>02 安全状态</small><strong className="is-healthy"><ShieldCheck size={19} />系统运行正常</strong><span>所有服务可用</span></section>
        <section><small>03 部署区域</small><strong>华东（上海）</strong><span>cn-shanghai-01</span></section>
        <footer>© 2026 RAG UPPER</footer>
      </aside>

      <section className="ru-login-form-area">
        <div className="ru-login-form">
          <span className="ru-section-index">04 安全登录</span>
          <h1>登录企业知识空间</h1>
          <p>使用企业身份访问获授权的知识与智能体服务。</p>

          <div className="ru-segmented" aria-label="登录方式">
            <button className="is-active" type="button">企业 SSO</button>
            <button type="button" disabled>账号登录</button>
          </div>

          <label>企业邮箱 / 账号<input value="zhangsan@demo.com" readOnly /></label>
          <label>密码<input type="password" value="development" readOnly /></label>
          <label className="ru-checkbox"><input type="checkbox" defaultChecked /><span><Check size={13} /></span>信任此设备（30 天内免验证）</label>

          <button className="ru-primary-button" type="button" onClick={retry} disabled={busy}>
            {busy ? <RefreshCw className="ru-spin" size={17} /> : <KeyRound size={17} />}
            {busy ? '正在认证' : '进入开发工作空间'}
          </button>

          <div className="ru-login-security"><ShieldCheck size={18} /><span>开发环境使用短期 JWT。生产环境由部署方接入企业 OIDC/SSO。</span><ExternalLink size={14} /></div>
          {error ? <div className="ru-inline-error">登录失败：{error}</div> : null}
        </div>
      </section>

      <aside className="ru-login-tenants">
        <span className="ru-section-index">05 选择知识空间</span>
        <h2>选择要访问的企业知识空间</h2>
        <div className="ru-tenant-option is-selected"><Building2 /><div><strong>数字化运营平台</strong><span>管理员 · 华东（上海）</span><small>最近访问：今天 09:18</small></div><Check /></div>
        <div className="ru-tenant-option"><Building2 /><div><strong>智能研发知识库</strong><span>知识管理员 · 华南（深圳）</span><small>最近访问：昨天 14:32</small></div></div>
        <div className="ru-tenant-option"><Building2 /><div><strong>客户服务知识中心</strong><span>成员 · 华北（北京）</span><small>最近访问：05-18 16:47</small></div></div>
      </aside>
    </main>
  );
}
