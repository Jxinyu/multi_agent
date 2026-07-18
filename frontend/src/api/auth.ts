export type AuthStatus = 'initializing' | 'authenticated' | 'unauthenticated';
export type AuthSource = 'development' | 'oidc';

export interface AuthSnapshot {
  status: AuthStatus;
  source?: AuthSource;
  error?: string;
}

interface DevelopmentTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

interface OidcAuthBridge {
  setAccessToken: (token: string) => void;
  clearAccessToken: () => void;
}

declare global {
  interface Window {
    ragUpperAuth?: OidcAuthBridge;
  }
}

const DEVELOPMENT_TOKEN_ENDPOINT = '/api/auth/development-token';

let accessToken: string | null = null;
let tokenRevision = 0;
let snapshot: AuthSnapshot = { status: 'initializing' };
let developmentTokenRequest: Promise<void> | null = null;
const listeners = new Set<() => void>();

function publish(next: AuthSnapshot) {
  snapshot = next;
  listeners.forEach((listener) => listener());
}

function setAccessToken(token: string, source: AuthSource) {
  if (typeof token !== 'string') {
    throw new Error('访问令牌必须是字符串');
  }
  const normalized = token.trim();
  if (!normalized) {
    throw new Error('访问令牌不能为空');
  }

  tokenRevision += 1;
  accessToken = normalized;
  publish({ status: 'authenticated', source });
}

function clearAccessTokenIfCurrent(token: string) {
  if (accessToken === token) {
    clearAccessToken();
  }
}

function requireAccessToken(): string {
  if (!accessToken) {
    throw new Error('未认证，请先登录');
  }
  return accessToken;
}

function assertSameOrigin(url: string) {
  const target = new URL(url, window.location.href);
  if (target.origin !== window.location.origin) {
    throw new Error('拒绝向跨域地址发送访问令牌');
  }
}

export function getAuthSnapshot(): AuthSnapshot {
  return snapshot;
}

export function subscribeAuth(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function setOidcAccessToken(token: string) {
  setAccessToken(token, 'oidc');
}

export function clearAccessToken() {
  tokenRevision += 1;
  accessToken = null;
  publish({ status: 'unauthenticated' });
}

export async function requestDevelopmentToken(): Promise<void> {
  if (accessToken) return;
  if (developmentTokenRequest) return developmentTokenRequest;

  const requestRevision = tokenRevision;
  publish({ status: 'initializing' });

  developmentTokenRequest = (async () => {
    try {
      const response = await fetch(DEVELOPMENT_TOKEN_ENDPOINT, {
        method: 'POST',
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) {
        throw new Error(`开发令牌请求失败（HTTP ${response.status}）`);
      }

      const data = (await response.json()) as DevelopmentTokenResponse;
      if (
        typeof data.access_token !== 'string'
        || typeof data.token_type !== 'string'
        || data.token_type.toLowerCase() !== 'bearer'
      ) {
        throw new Error('开发令牌响应格式无效');
      }

      if (tokenRevision === requestRevision && !accessToken) {
        setAccessToken(data.access_token, 'development');
      }
    } catch (error) {
      if (tokenRevision === requestRevision && !accessToken) {
        publish({
          status: 'unauthenticated',
          error: error instanceof Error ? error.message : '无法获取开发令牌'
        });
      }
    } finally {
      developmentTokenRequest = null;
    }
  })();

  return developmentTokenRequest;
}

export async function initializeAuth(): Promise<void> {
  if (accessToken) return;
  await requestDevelopmentToken();
}

export async function authFetch(input: string, init?: RequestInit): Promise<Response> {
  assertSameOrigin(input);
  const token = requireAccessToken();
  const headers = new Headers(init?.headers);
  headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch(input, { ...init, headers });
  if (response.status === 401) {
    clearAccessTokenIfCurrent(token);
  }
  return response;
}

export function openAuthenticatedXhr(method: string, url: string): XMLHttpRequest {
  assertSameOrigin(url);
  const token = requireAccessToken();
  const xhr = new XMLHttpRequest();
  xhr.open(method, url);
  xhr.setRequestHeader('Authorization', `Bearer ${token}`);
  xhr.addEventListener('load', () => {
    if (xhr.status === 401) {
      clearAccessTokenIfCurrent(token);
    }
  });
  return xhr;
}

if (typeof window !== 'undefined') {
  window.ragUpperAuth = {
    setAccessToken: setOidcAccessToken,
    clearAccessToken
  };
}
