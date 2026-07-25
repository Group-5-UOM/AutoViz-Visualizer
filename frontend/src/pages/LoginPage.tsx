import { useState, type FormEvent } from 'react';
import { Eye, EyeOff, Lock, Mail } from 'lucide-react';
import { ApiError } from '../lib/api';
import { loginUser, registerUser } from '../lib/auth';
import './LoginPage.css';

interface LoginPageProps {
  onLogin: (email: string) => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    const trimmedEmail = email.trim();
    if (!trimmedEmail || !password.trim()) {
      setError('Enter your email and password to continue.');
      return;
    }

    setSubmitting(true);
    try {
      if (mode === 'register') {
        await registerUser(trimmedEmail, password);
      }
      await loginUser(trimmedEmail, password);
      onLogin(trimmedEmail);
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
            <h2>{mode === 'login' ? 'Sign in' : 'Create account'}</h2>
            <p>
              {mode === 'login'
                ? 'Welcome back. Continue to your visualization workspace.'
                : 'Register once, then upload a CSV and start exploring.'}
            </p>
          </header>

          <form className="login-form" onSubmit={handleSubmit} noValidate>
            <label className="login-field">
              <span className="login-label">Email</span>
              <span className="login-input-wrap">
                <Mail size={16} className="login-input-icon" aria-hidden />
                <input
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

            {error && <p className="login-error" role="alert">{error}</p>}

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

          <p className="login-footer">
            {mode === 'login' ? (
              <>
                Don&apos;t have an account?{' '}
                <button
                  type="button"
                  className="login-link-btn"
                  onClick={() => {
                    setMode('register');
                    setError('');
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
