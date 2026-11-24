/** Error carrying the HTTP status and the server's safe, user-facing message. */
export class ApiError extends Error {
  status: number;
  code?: string;
  retryAfter?: number;
  authRequired: boolean;

  constructor(message: string, status: number, extra: { code?: string; retryAfter?: number; authRequired?: boolean } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = extra.code;
    this.retryAfter = extra.retryAfter;
    this.authRequired = Boolean(extra.authRequired);
  }
}

let unauthorizedHandler: (() => void) | null = null;

/** The auth context registers a callback so any 401 anywhere signs the user out of the UI. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function notifyUnauthorized(): void {
  unauthorizedHandler?.();
}

interface ErrorBody {
  success?: boolean;
  error?: string;
  code?: string;
  auth_required?: boolean;
}

export async function errorFromResponse(response: Response): Promise<ApiError> {
  let body: ErrorBody = {};
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    /* non-JSON error body */
  }
  const retry = Number(response.headers.get("Retry-After"));
  return new ApiError(body.error || "Something went wrong. Please try again.", response.status, {
    code: body.code,
    retryAfter: Number.isFinite(retry) && retry > 0 ? retry : undefined,
    authRequired: body.auth_required,
  });
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const response = await fetch(path, {
    credentials: "same-origin",
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });

  if (!response.ok) {
    const error = await errorFromResponse(response);
    if (response.status === 401 && error.authRequired) notifyUnauthorized();
    throw error;
  }

  const data = (await response.json()) as T & { success?: boolean; error?: string };
  if (data && data.success === false) {
    throw new ApiError(data.error || "Something went wrong. Please try again.", response.status);
  }
  return data;
}
