import { useEffect, useState } from 'react';

import { fetchCurrentUser } from '../api/admin';
import type { CurrentUser } from '../types';

interface CurrentUserState {
  user: CurrentUser | null;
  loading: boolean;
  error: string | null;
}

export function useCurrentUser(): CurrentUserState {
  const [state, setState] = useState<CurrentUserState>({ user: null, loading: true, error: null });

  useEffect(() => {
    let active = true;

    fetchCurrentUser()
      .then((user) => {
        if (active) setState({ user, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setState({
          user: null,
          loading: false,
          error: error instanceof Error ? error.message : '无法加载当前用户'
        });
      });

    return () => {
      active = false;
    };
  }, []);

  return state;
}
