const TOKEN_KEY = 'autoviz-access-token';
const EMAIL_KEY = 'autoviz-user-email';

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL as string | undefined
)?.replace(/\/+$/, '') || 'http://127.0.0.1:8000';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function getAccessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function getStoredEmail(): string | null {
  return sessionStorage.getItem(EMAIL_KEY);
}

export function setSession(email: string, token: string) {
  sessionStorage.setItem(EMAIL_KEY, email);
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearSession() {
  sessionStorage.removeItem(EMAIL_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
}

/**
 * Fired when the server rejects a token we thought was good (expired, or
 * revoked by a logout elsewhere). App listens and drops back to the login
 * screen, so an expired session shows a sign-in page instead of every action
 * failing with "Invalid or expired token".
 */
export const SESSION_EXPIRED_EVENT = 'autoviz:session-expired';

function formatDetail(data: unknown, status: number): string {
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    if (typeof obj.detail === 'string') return obj.detail;
    if (typeof obj.error === 'string') return obj.error;
    if (Array.isArray(obj.detail)) {
      return obj.detail
        .map((item) => {
          if (item && typeof item === 'object' && 'msg' in item) {
            return String((item as { msg: unknown }).msg);
          }
          return JSON.stringify(item);
        })
        .join('; ');
    }
  }
  return `Request failed (${status})`;
}

export async function apiRequest<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    form?: FormData;
    auth?: boolean;
  } = {},
): Promise<T> {
  const { method = 'GET', body, form, auth = true } = options;
  const headers: Record<string, string> = {};

  if (auth) {
    const token = getAccessToken();
    if (!token) {
      throw new ApiError('Not signed in', 401);
    }
    headers.Authorization = `Bearer ${token}`;
  }

  let payload: BodyInit | undefined;
  if (form) {
    payload = form;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: payload,
  });

  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: text };
    }
  }

  if (!res.ok) {
    if (res.status === 401 && auth) {
      clearSession();
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT));
    }
    throw new ApiError(formatDetail(data, res.status), res.status);
  }

  return data as T;
}
