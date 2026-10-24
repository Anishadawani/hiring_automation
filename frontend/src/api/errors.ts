export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type ValidationItem = { loc?: unknown[]; msg?: string };

/** Turn whatever FastAPI sent back into one readable sentence. */
export function toApiError(detail: unknown, status: number): ApiError {
  const body = (detail && typeof detail === "object" ? (detail as { detail?: unknown }).detail : undefined) ?? detail;

  if (typeof body === "string") return new ApiError(body, status);

  if (Array.isArray(body)) {
    // 422 validation errors: [{loc: ["body", "title"], msg: "..."}]
    const parts = (body as ValidationItem[]).map((item) => {
      const field = Array.isArray(item.loc) ? item.loc.filter((p) => p !== "body").join(" › ") : "";
      const message = (item.msg ?? "Invalid value").replace(/^Value error, /, "");
      return field ? `${field}: ${message}` : message;
    });
    return new ApiError(parts.join(". ") || "Please check the form.", status);
  }

  if (body && typeof body === "object") {
    const { code, message } = body as { code?: string; message?: string };
    if (message) return new ApiError(message, status, code);
  }

  const fallback =
    status === 401 ? "Please sign in again."
    : status === 403 ? "You do not have access to this."
    : status === 404 ? "We could not find that."
    : status === 429 ? "Too many requests. Please wait a moment and try again."
    : status >= 500 ? "Something went wrong on our side. Please try again."
    : "Something went wrong.";
  return new ApiError(fallback, status);
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError) return "Could not reach the server. Check your connection and try again.";
  return error instanceof Error ? error.message : "Something went wrong.";
}
