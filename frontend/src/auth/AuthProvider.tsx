import { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { RoleName, User } from "../api/types";
import { authApi } from "../api/endpoints";
import {
  clearTokens,
  hasTokens,
  onTokensCleared,
  setTokens,
} from "../api/tokenStore";
import { AuthContext, type AuthState } from "./authContext";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const queryClient = useQueryClient();

  // Hydrate the session on first load: if we hold tokens, ask the server who
  // we are. A failure here (expired/rotated-away tokens) just means logged out.
  useEffect(() => {
    let active = true;
    async function hydrate() {
      if (!hasTokens()) {
        setLoading(false);
        return;
      }
      try {
        const me = await authApi.me();
        if (active) setUserState(me);
      } catch {
        clearTokens();
      } finally {
        if (active) setLoading(false);
      }
    }
    void hydrate();
    return () => {
      active = false;
    };
  }, []);

  // When the API layer clears tokens (a refresh failed mid-session), drop the
  // user so the router sends them to login.
  useEffect(
    () =>
      onTokensCleared(() => {
        setUserState(null);
        queryClient.clear();
      }),
    [queryClient],
  );

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    setTokens({ accessToken: res.access_token, refreshToken: res.refresh_token });
    setUserState(res.user);
  }, []);

  const logout = useCallback(
    async (allSessions = false) => {
      try {
        await authApi.logout(allSessions);
      } catch {
        // Even if the server call fails, drop local state.
      }
      clearTokens();
      setUserState(null);
      queryClient.clear();
    },
    [queryClient],
  );

  const setUser = useCallback((next: User) => setUserState(next), []);

  const value = useMemo<AuthState>(() => {
    const roleNames = new Set<RoleName>(user?.roles.map((r) => r.name) ?? []);
    const isAdmin = roleNames.has("admin");
    return {
      user,
      loading,
      login,
      logout,
      setUser,
      hasRole: (...roles: RoleName[]) =>
        isAdmin || roles.some((r) => roleNames.has(r)),
      isAdmin,
      isEngineer: isAdmin || roleNames.has("engineer"),
    };
  }, [user, loading, login, logout, setUser]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
