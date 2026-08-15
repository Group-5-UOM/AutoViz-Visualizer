import { ApiError, NETWORK_ERROR_STATUS } from './errors';

// The error taxonomy lives in ./errors so it can be tested under Node — this
// module cannot be imported there, because `import.meta.env` below is a Vite
// construct. Re-exported so call sites still import everything from `lib/api`.
export {
  ApiError,
  NETWORK_ERROR_STATUS,
  classifyError,
  isRetryable,
  errorMessage,
} from './errors';
export type { ErrorKind } from './errors';

const TOKEN_KEY = 'autoviz-access-token';
const EMAIL_KEY = 'autoviz-user-email';
const USERNAME_KEY = 'autoviz-username';

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL as string | undefined
)?.replace(/\/+$/, '') || '/api';

export function getAccessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function getStoredEmail(): string | null {
  return sessionStorage.getItem(EMAIL_KEY);
}

export function getStoredUsername(): string | null {
  return sessionStorage.getItem(USERNAME_KEY);
}

export function setSession(email: string, token: string, username?: string) {
  sessionStorage.setItem(EMAIL_KEY, email);
  sessionStorage.setItem(TOKEN_KEY, token);
  sessionStorage.setItem(USERNAME_KEY, username || email.split('@')[0] || email);
}

export function clearSession() {
  sessionStorage.removeItem(EMAIL_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USERNAME_KEY);
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
    // A rejected analysis plan comes back as {valid: false, errors: [...]}.
    // Without this the most explanatory failure the backend produces — the one
    // that names the column or the aggregation it would not accept — reached
    // the user as "Request failed (422)".
    if (Array.isArray(obj.errors) && obj.errors.length > 0) {
      return obj.errors.map((item) => String(item)).join('; ');
    }
  }
  return `Request failed (${status})`;
}

/** The backend's typed error code, if the body carries one. */
function errorCode(data: unknown): string | undefined {
  if (data && typeof data === 'object') {
    const code = (data as Record<string, unknown>).error_code;
    if (typeof code === 'string') return code;
  }
  return undefined;
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

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: payload,
    });
  } catch {
    // fetch rejects for a dropped connection, DNS failure or CORS refusal — all
    // of which are recoverable and none of which are distinguishable from here.
    // Normalised into ApiError so callers have one error type to classify
    // rather than a bare TypeError reading "Failed to fetch".
    throw new ApiError(
      'Could not reach the server. Check your connection and try again.',
      NETWORK_ERROR_STATUS,
    );
  }

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
    throw new ApiError(formatDetail(data, res.status), res.status, errorCode(data));
  }

  return data as T;
}
