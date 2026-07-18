import { useEffect, useSyncExternalStore } from 'react';

import {
  getAuthSnapshot,
  initializeAuth,
  requestDevelopmentToken,
  subscribeAuth
} from '../api/auth';

export function useAuth() {
  const auth = useSyncExternalStore(subscribeAuth, getAuthSnapshot, getAuthSnapshot);

  useEffect(() => {
    void initializeAuth();
  }, []);

  return {
    ...auth,
    retryDevelopmentAuth: requestDevelopmentToken
  };
}
