import { useRef, useState, type FormEvent } from 'react';
import { Eye, EyeOff, Lock, Mail, User } from 'lucide-react';
import { ApiError } from '../lib/api';
import { loginUser, registerUser } from '../lib/auth';
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

function FacebookIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden>
      <path
        fill="#1877F2"
        d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047v-2.66c0-3.025 1.792-4.697 4.533-4.697 1.312 0 2.686.236 2.686.236v2.971h-1.513c-1.491 0-1.956.931-1.956 1.886v2.264h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073Z"
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
  { id: 'facebook', label: 'Facebook', icon: <FacebookIcon /> },
  { id: 'github', label: 'GitHub', icon: <GitHubIcon /> },
  { id: 'email', label: 'Email', icon: <Mail size={18} /> },
] as const;

export function LoginPage({ onLogin }: LoginPageProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [showRegisterHint, setShowRegisterHint] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const emailInputRef = useRef<HTMLInputElement>(null);

  const switchMode = (next: 'login' | 'register') => {
    setMode(next);
    setError('');
    setShowRegisterHint(false);
  };

  const handleOAuthClick = (providerId: (typeof OAUTH_PROVIDERS)[number]['id']) => {
    if (providerId === 'email') {
      setError('');
      emailInputRef.current?.focus();
      return;
    }
    setError(`${providerId[0].toUpperCase()}${providerId.slice(1)} sign-in is coming soon.`);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setShowRegisterHint(false);

    const trimmedEmail = email.trim();
    const trimmedUsername = username.trim();
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
        username: session.username || trimmedEmail.split('@')[0],
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not sign in.';
      setError(message);
      // 401 covers both an unknown email and a wrong password, so point at
      // registration without confirming whether the account exists.
      if (mode === 'login' && err instanceof ApiError && err.status === 401) {
        setShowRegisterHint(true);
      }
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
            <h2>{mode === 'login' ? 'Sign in' : 'Create account'}</h2>
            <p>
              {mode === 'login'
                ? 'Welcome back. Continue to your visualization workspace.'
                : 'Register once, then upload a CSV and start exploring.'}
            </p>
          </header>

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

          <form className="login-form" onSubmit={handleSubmit} noValidate>
            {mode === 'register' && (
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
                />
              </span>
            </label>

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

            {mode === 'login' && (
              <div className="login-row">
                <label className="login-remember">
                  <input type="checkbox" name="remember" />
                  <span>Remember me</span>
                </label>
                <button type="button" className="login-link-btn">
                  Forgot password?
                </button>
              </div>
            )}

            <button type="submit" className="login-submit" disabled={submitting}>
              {submitting
                ? mode === 'login'
                  ? 'Signing in…'
                  : 'Creating account…'
                : mode === 'login'
                  ? 'Sign in'
                  : 'Create account'}
            </button>
          </form>

          {error && (
            <p className="login-error" role="alert">
              {error}
              {showRegisterHint && (
                <>
                  {' '}
                  If you have not signed up yet,{' '}
                  <button
                    type="button"
                    className="login-link-btn"
                    onClick={() => switchMode('register')}
                  >
                    create an account
                  </button>
                  .
                </>
              )}
            </p>
          )}

          <p className="login-footer">
            {mode === 'login' ? (
              <>
                Don&apos;t have an account?{' '}
                <button
                  type="button"
                  className="login-link-btn"
                  onClick={() => switchMode('register')}
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
                  onClick={() => switchMode('login')}
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
