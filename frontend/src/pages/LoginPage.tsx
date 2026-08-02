import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Eye, EyeOff, Lock, Mail, User } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { ApiError } from '../lib/api';
import {
  completeOAuthRegister,
  loginUser,
  registerUser,
  requestPasswordReset,
  startGithubOAuth,
  startGoogleOAuth,
} from '../lib/auth';
import './LoginPage.css';

interface LoginPageProps {
  onLogin: (user: { email: string; username: string }) => void;
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615Z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18Z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.997 8.997 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332Z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58Z"
      />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="#24292F"
        d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.385-1.335-1.755-1.335-1.755-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"
      />
    </svg>
  );
}

const OAUTH_PROVIDERS = [
  { id: 'google', label: 'Google', icon: <GoogleIcon /> },
  { id: 'github', label: 'GitHub', icon: <GitHubIcon /> },
  { id: 'email', label: 'Email', icon: <Mail size={18} /> },
] as const;

export function LoginPage({ onLogin }: LoginPageProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [oauthPending, setOauthPending] = useState<string | null>(null);
  const [forgotMode, setForgotMode] = useState(false);
  const [forgotInfo, setForgotInfo] = useState('');
  const emailInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const pending = searchParams.get('pending');
    const nextEmail = searchParams.get('email');
    const nextMode = searchParams.get('mode');
    if (pending && nextEmail) {
      setOauthPending(pending);
      setEmail(nextEmail);
      setMode('register');
      setError('');
      setSearchParams({}, { replace: true });
    } else if (nextMode === 'register') {
      setMode('register');
    }
  }, [searchParams, setSearchParams]);

  const clearOauthPending = () => {
    setOauthPending(null);
  };

  const handleOAuthClick = (providerId: (typeof OAUTH_PROVIDERS)[number]['id']) => {
    if (providerId === 'email') {
      setError('');
      emailInputRef.current?.focus();
      return;
    }
    if (providerId === 'github') {
      setError('');
      startGithubOAuth();
      return;
    }
    setError('');
    startGoogleOAuth();
  };

  const handleForgot = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setForgotInfo('');
    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setError('Enter your email to reset or set a password.');
      return;
    }
    setSubmitting(true);
    try {
      const res = await requestPasswordReset(trimmedEmail);
      if (res.reset_url) {
        setForgotInfo(`${res.detail} Open: ${res.reset_url}`);
      } else {
        setForgotInfo(res.detail);
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not start password reset.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    if (forgotMode) {
      await handleForgot(e);
      return;
    }
    e.preventDefault();
    setError('');

    const trimmedEmail = email.trim();
    const trimmedUsername = username.trim();

    if (oauthPending) {
      if (!trimmedUsername) {
        setError('Choose a username to finish creating your account.');
        return;
      }
      setSubmitting(true);
      try {
        const session = await completeOAuthRegister(oauthPending, trimmedUsername);
        onLogin({
          email: session.email || trimmedEmail,
          username: session.username || trimmedUsername,
        });
      } catch (err) {
        const message =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : 'Could not create account.';
        setError(message);
      } finally {
        setSubmitting(false);
      }
      return;
    }

    if (!trimmedEmail || !password.trim()) {
      setError('Enter your email and password to continue.');
      return;
    }
    if (mode === 'register' && !trimmedUsername) {
      setError('Enter a username to create your account.');
      return;
    }

    setSubmitting(true);
    try {
      if (mode === 'register') {
        await registerUser(trimmedEmail, password, trimmedUsername);
      }
      const session = await loginUser(trimmedEmail, password);
      onLogin({
        email: trimmedEmail,
        username: session.username || trimmedUsername || trimmedEmail.split('@')[0],
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not sign in.';
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-atmosphere" aria-hidden>
        <div className="login-glow login-glow--a" />
        <div className="login-glow login-glow--b" />
        <div className="login-grid" />
      </div>

      <main className="login-shell">
        <section className="login-brand">
          <div className="login-brand-mark" aria-hidden />
          <h1 className="login-brand-name">AutoViz AI</h1>
          <p className="login-brand-tagline">
            Ask questions in plain language. Build dashboards without writing SQL.
          </p>
        </section>

        <section className="login-panel" aria-label={mode === 'login' ? 'Sign in' : 'Create account'}>
          <header className="login-panel-header">
            <h2>
              {forgotMode
                ? 'Forgot password'
                : oauthPending
                  ? 'Finish registration'
                  : mode === 'login'
                    ? 'Sign in'
                    : 'Create account'}
            </h2>
            <p>
              {forgotMode
                ? 'Enter your email. We’ll send a link to set or reset your AutoViz password.'
                : oauthPending
                  ? 'Your email was verified with Google or GitHub. Choose a username to continue.'
                  : mode === 'login'
                    ? 'Welcome back. Continue to your visualization workspace.'
                    : 'Register once, then upload a CSV and start exploring.'}
            </p>
          </header>

          {!oauthPending && !forgotMode && (
            <>
              <div className="oauth-row" role="group" aria-label="Sign in with a provider">
                {OAUTH_PROVIDERS.map((provider) => (
                  <button
                    key={provider.id}
                    type="button"
                    className={`oauth-icon-btn oauth-icon-btn--${provider.id}`}
                    onClick={() => handleOAuthClick(provider.id)}
                    title={`Continue with ${provider.label}`}
                    aria-label={`Continue with ${provider.label}`}
                  >
                    {provider.icon}
                  </button>
                ))}
              </div>

              <div className="login-divider" role="separator">
                <span>or</span>
              </div>
            </>
          )}

          <form className="login-form" onSubmit={handleSubmit} noValidate>
            {(mode === 'register' || oauthPending) && !forgotMode && (
              <label className="login-field">
                <span className="login-label">Username</span>
                <span className="login-input-wrap">
                  <User size={16} className="login-input-icon" aria-hidden />
                  <input
                    type="text"
                    name="username"
                    autoComplete="username"
                    placeholder="Choose a username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoFocus={Boolean(oauthPending)}
                  />
                </span>
              </label>
            )}

            <label className="login-field">
              <span className="login-label">Email</span>
              <span className="login-input-wrap">
                <Mail size={16} className="login-input-icon" aria-hidden />
                <input
                  ref={emailInputRef}
                  type="email"
                  name="email"
                  autoComplete="email"
                  placeholder="you@university.edu"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  readOnly={Boolean(oauthPending)}
                />
              </span>
            </label>

            {!oauthPending && !forgotMode && (
              <label className="login-field">
                <span className="login-label">Password</span>
                <span className="login-input-wrap">
                  <Lock size={16} className="login-input-icon" aria-hidden />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    name="password"
                    autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                    placeholder="Enter your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    className="login-eye-btn"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </span>
              </label>
            )}

            {mode === 'login' && !oauthPending && !forgotMode && (
              <div className="login-row">
                <label className="login-remember">
                  <input type="checkbox" name="remember" />
                  <span>Remember me</span>
                </label>
                <button
                  type="button"
                  className="login-link-btn"
                  onClick={() => {
                    setForgotMode(true);
                    setError('');
                    setForgotInfo('');
                  }}
                >
                  Forgot password?
                </button>
              </div>
            )}

            <button type="submit" className="login-submit" disabled={submitting}>
              {submitting
                ? forgotMode
                  ? 'Sending…'
                  : oauthPending || mode === 'register'
                    ? 'Creating account…'
                    : 'Signing in…'
                : forgotMode
                  ? 'Send reset link'
                  : oauthPending || mode === 'register'
                    ? 'Create account'
                    : 'Sign in'}
            </button>
          </form>

          {error && <p className="login-error" role="alert">{error}</p>}
          {forgotInfo && (
            <p className="login-error" role="status" style={{ color: 'var(--text-primary)' }}>
              {forgotInfo}
            </p>
          )}

          <p className="login-footer">
            {forgotMode ? (
              <>
                Remembered it?{' '}
                <button
                  type="button"
                  className="login-link-btn"
                  onClick={() => {
                    setForgotMode(false);
                    setForgotInfo('');
                    setError('');
                  }}
                >
                  Back to sign in
                </button>
              </>
            ) : oauthPending ? (
              <>
                Wrong account?{' '}
                <button
                  type="button"
                  className="login-link-btn"
                  onClick={() => {
                    clearOauthPending();
                    setMode('login');
                    setEmail('');
                    setUsername('');
                    setError('');
                  }}
                >
                  Start over
                </button>
              </>
            ) : mode === 'login' ? (
              <>
                Don&apos;t have an account?{' '}
                <button
                  type="button"
                  className="login-link-btn"
                  onClick={() => {
                    setMode('register');
                    setError('');
                    setForgotMode(false);
                  }}
                >
                  Create one
                </button>
              </>
            ) : (
              <>
                Already registered?{' '}
                <button
                  type="button"
                  className="login-link-btn"
                  onClick={() => {
                    setMode('login');
                    setError('');
                  }}
                >
                  Sign in
                </button>
              </>
            )}
          </p>
        </section>
      </main>
    </div>
  );
}
