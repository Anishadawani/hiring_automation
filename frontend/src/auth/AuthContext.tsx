import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, call, LOGOUT_EVENT, tokenStore } from "../api/client";
import type { User } from "../api/types";

type Status = "loading" | "anonymous" | "authenticated";

type AuthValue = {
  status: Status;
  user: User | null;
  login: (email: string, password: string) => Promise<User>;
  register: (input: { email: string; password: string; full_name: string; role: "candidate" | "recruiter"; invite_code?: string }) => Promise<User>;
  logout: () => void;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>(tokenStore.get() ? "loading" : "anonymous");
  const [user, setUser] = useState<User | null>(null);

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
    setStatus("anonymous");
  }, []);

  // Restore the session after a page refresh.
  useEffect(() => {
    if (!tokenStore.get()) return;
    let cancelled = false;
    call(api.GET("/api/auth/me"))
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setStatus("authenticated");
      })
      .catch(() => {
        if (!cancelled) logout();
      });
    return () => {
      cancelled = true;
    };
  }, [logout]);

  // The API client fires this when the server says the session is no longer valid.
  useEffect(() => {
    window.addEventListener(LOGOUT_EVENT, logout);
    return () => window.removeEventListener(LOGOUT_EVENT, logout);
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const result = await call(api.POST("/api/auth/login", { body: { email, password } }));
    tokenStore.set(result.access_token);
    setUser(result.user);
    setStatus("authenticated");
    return result.user;
  }, []);

  const register = useCallback<AuthValue["register"]>(
    async (input) => {
      await call(api.POST("/api/auth/register", { body: input }));
      return login(input.email, input.password);
    },
    [login],
  );

  const value = useMemo(() => ({ status, user, login, register, logout }), [status, user, login, register, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>.");
  return value;
}

export function homeFor(role: User["role"]): string {
  return role === "recruiter" ? "/recruiter" : "/jobs";
}
