import { apiRequest, clearSession, setSession } from './api';

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

/**
 * `username` is collected by the sign-up form and sent along, but the backend
 * has no username column yet — it accepts and ignores the field, and the
 * response carries only the id and email.
 */
export async function registerUser(email: string, password: string, username: string) {
  return apiRequest<{ id: string; email: string }>('/auth/register', {
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
  setSession(email, data.access_token);
  return data;
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
