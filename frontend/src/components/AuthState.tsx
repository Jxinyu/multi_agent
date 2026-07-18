import { LoaderCircle, LogIn, ShieldAlert } from 'lucide-react';

import type { AuthSnapshot } from '../api/auth';

interface AuthStateProps {
  auth: AuthSnapshot;
  onRetry: () => Promise<void>;
}

export function AuthState({ auth, onRetry }: AuthStateProps) {
  const initializing = auth.status === 'initializing';

  return (
    <main className="auth-shell">
      <section className="auth-panel" aria-live="polite">
        <div className="auth-icon" aria-hidden="true">
          {initializing ? <LoaderCircle className="auth-spinner" size={22} /> : <ShieldAlert size={22} />}
        </div>
        <h1>{initializing ? '正在验证身份' : '未认证'}</h1>
        <p>{initializing ? '正在检查可用的登录会话。' : (auth.error ?? '登录会话不可用或已过期。')}</p>
        {!initializing ? (
          <button type="button" className="icon-button primary" onClick={() => void onRetry()}>
            <LogIn size={16} />
            获取开发令牌
          </button>
        ) : null}
      </section>
    </main>
  );
}
