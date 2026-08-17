import { apiRequest, clearSession, setSession, API_BASE_URL } from './api';

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  email?: string;
  username?: string;
  has_password?: boolean;
  oauth_providers?: string[];
}

export async function registerUser(email: string, password: string, username: string) {
  return apiRequest<{ id: string; email: string; username: string }>('/auth/register', {
    method: 'POST',
    body: { email, password, username },
    auth: false,
  });
}

export async function loginUser(email: string, password: string) {
  const data = await apiRequest<LoginResponse>('/auth/login', {
    method: 'POST',
    body: { email, password },
    auth: false,
  });
  setSession(email, data.access_token, data.username || email.split('@')[0]);
  return data;
}

export function startGithubOAuth() {
  window.location.assign(`${API_BASE_URL}/auth/oauth/github/start`);
}

export function startGoogleOAuth() {
  window.location.assign(`${API_BASE_URL}/auth/oauth/google/start`);
}

export function applyOAuthSession(email: string, token: string, username?: string) {
  setSession(email, token, username || email.split('@')[0]);
}

export async function completeOAuthRegister(pendingToken: string, username: string) {
  const data = await apiRequest<LoginResponse>('/auth/oauth/register', {
    method: 'POST',
    body: { pending_token: pendingToken, username },
    auth: false,
  });
  const email = data.email;
  if (!email) {
    throw new Error('OAuth registration did not return an email');
  }
  setSession(email, data.access_token, data.username || username);
  return data;
}

export async function setAccountPassword(password: string, confirmPassword: string) {
  return apiRequest<{ password_set: boolean }>('/auth/password', {
    method: 'POST',
    body: { password, confirm_password: confirmPassword },
  });
}

export async function requestPasswordReset(email: string) {
  return apiRequest<{
    ok: boolean;
    detail: string;
    reset_token?: string;
    reset_url?: string;
  }>('/auth/forgot-password', {
    method: 'POST',
    body: { email },
    auth: false,
  });
}

export async function resetPassword(token: string, password: string, confirmPassword: string) {
  return apiRequest<{ password_set: boolean }>('/auth/reset-password', {
    method: 'POST',
    body: { token, password, confirm_password: confirmPassword },
    auth: false,
  });
}

export async function fetchMe() {
  return apiRequest<{
    id: string;
    email: string;
    username: string;
    has_password: boolean;
    email_verified: boolean;
    oauth_providers: string[];
  }>('/auth/me');
}

export async function logoutUser() {
  try {
    await apiRequest<{ logged_out: boolean }>('/auth/logout', {
      method: 'POST',
    });
  } catch {
    // Clear local session even if the server call fails.
  } finally {
    clearSession();
  }
}

// --- MCP connection keys -----------------------------------------------------
//
// The link a user pastes into Claude, Gemini CLI or any other MCP host to give
// it access to *their* AutoViz data. The key is a capability — possession of
// the URL is the authorisation — so the server returns it exactly once, at
// creation, and never again.

export interface McpKey {
  id: string;
  label: string;
  profile: 'host' | 'default' | 'advanced';
  created_at: string | null;
  last_used_at: string | null;
  expires_at: string | null;
  revoked: boolean;
}

/** The create response, and the only one that ever carries the key itself. */
export interface McpKeyCreated extends McpKey {
  key: string;
  url: string;
}

export async function listMcpKeys() {
  return apiRequest<McpKey[]>('/auth/mcp-keys');
}

export async function createMcpKey(
  label: string,
  profile: McpKey['profile'] = 'host',
  expiresInDays: number | null = 90,
) {
  return apiRequest<McpKeyCreated>('/auth/mcp-keys', {
    method: 'POST',
    body: { label, profile, expires_in_days: expiresInDays },
  });
}

export async function revokeMcpKey(keyId: string) {
  return apiRequest<void>(`/auth/mcp-keys/${encodeURIComponent(keyId)}`, {
    method: 'DELETE',
  });
}
