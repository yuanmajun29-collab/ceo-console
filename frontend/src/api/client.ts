export interface ApiOptions {
  signal?: AbortSignal;
}

const BASE = "";

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts: ApiOptions = {}
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: { "Content-Type": "application/json" },
    signal: opts.signal,
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }
  const resp = await fetch(`${BASE}${path}`, init);
  const text = await resp.text();
  if (!resp.ok) {
    let detail: unknown = text;
    try {
      detail = JSON.parse(text);
    } catch {}
    throw new ApiError(resp.status, detail);
  }
  return (text ? JSON.parse(text) : {}) as T;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

export const api = {
  get: <T>(path: string, opts?: ApiOptions) => request<T>("GET", path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: ApiOptions) =>
    request<T>("POST", path, body, opts),
  patch: <T>(path: string, body?: unknown, opts?: ApiOptions) =>
    request<T>("PATCH", path, body, opts),
  del: <T>(path: string, body?: unknown, opts?: ApiOptions) =>
    request<T>("DELETE", path, body, opts),
};
