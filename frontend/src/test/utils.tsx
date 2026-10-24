import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";

type Request_ = { url: URL; method: string; body: unknown };
type Route = ((req: Request_) => unknown) | unknown;

export function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
}

/** Replace fetch with a fake server. Keys look like "GET /api/openings". */
export function mockApi(routes: Record<string, Route>) {
  const calls: { method: string; path: string; body: unknown; search: string }[] = [];
  const fake = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(input, init);
    const url = new URL(req.url);
    const method = req.method.toUpperCase();
    const text = await req.clone().text();
    let body: unknown = undefined;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    calls.push({ method, path: url.pathname, body, search: url.search });
    const route = routes[`${method} ${url.pathname}`];
    if (route === undefined) return json({ detail: `No mock for ${method} ${url.pathname}` }, 500);
    const result = typeof route === "function" ? (route as (r: Request_) => unknown)({ url, method, body }) : route;
    return result instanceof Response ? result : json(result);
  });
  vi.stubGlobal("fetch", fake);
  return { calls, fake, called: (key: string) => calls.filter((c) => `${c.method} ${c.path}` === key) };
}

export const candidateUser = { id: 1, email: "ada@example.com", full_name: "Ada Lovelace", role: "candidate", created_at: "2026-01-01T00:00:00Z" };
export const recruiterUser = { id: 2, email: "rec@example.com", full_name: "Rae Recruiter", role: "recruiter", created_at: "2026-01-01T00:00:00Z" };

/** Render with router, data cache and sign-in state. Pass `user` to start signed in. */
export function renderApp(ui: ReactElement, options: { route?: string; user?: typeof candidateUser | typeof recruiterUser } = {}) {
  if (options.user) sessionStorage.setItem("hiresense.token", "test-token");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[options.route ?? "/"]}>
        <AuthProvider>{ui}</AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export function asUser(user: typeof candidateUser | typeof recruiterUser): Record<string, Route> {
  return { "GET /api/auth/me": user };
}
