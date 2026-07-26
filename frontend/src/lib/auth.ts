import { apiRequest, clearSession, setSession } from './api';

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
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
