import createClient, { type Middleware } from "openapi-fetch";
import { toApiError } from "./errors";
import type { paths } from "./schema";

const TOKEN_KEY = "hiresense.token";
export const LOGOUT_EVENT = "hiresense:logout";

// sessionStorage: the token disappears when the tab closes. (No browser storage is safe from XSS,
// which is why the app also avoids dangerouslySetInnerHTML and only links to http(s) URLs.)
export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (token: string) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const token = tokenStore.get();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401 && tokenStore.get()) {
      tokenStore.clear();
      window.dispatchEvent(new Event(LOGOUT_EVENT));
    }
    return response;
  },
};

// The browser talks to the page's own origin: Vite (dev) or nginx (production) forwards /api to FastAPI.
export const api = createClient<paths>({
  baseUrl: window.location.origin,
  fetch: (request) => globalThis.fetch(request),
});
api.use(authMiddleware);

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Unwrap an openapi-fetch result: return the data, or throw an ApiError with a readable message. */
export async function call<T>(promise: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await promise;
  if (error !== undefined || !response.ok) throw toApiError(error, response.status);
  return data as T;
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await globalThis.fetch(`${window.location.origin}${path}`, { ...init, headers });
  if (response.status === 401 && token) {
    tokenStore.clear();
    window.dispatchEvent(new Event(LOGOUT_EVENT));
  }
  return response;
}

async function failIfNotOk(response: Response): Promise<void> {
  if (response.ok) return;
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = undefined;
  }
  throw toApiError(body, response.status);
}

/** Resume upload is multipart, which is simplest to send with plain fetch. */
export async function uploadResume(file: File): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  await failIfNotOk(await raw("/api/candidate/resume", { method: "POST", body: form }));
}

/** Download a candidate's resume (needs the sign-in header, so a plain link would not work). */
export async function downloadResume(applicationId: number, filename: string): Promise<void> {
  const response = await raw(`/api/recruiter/applications/${applicationId}/resume`);
  await failIfNotOk(response);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
