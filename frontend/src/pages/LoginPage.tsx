import { useState, type FormEvent } from 'react';
import { Eye, EyeOff, Lock, Mail } from 'lucide-react';
import './LoginPage.css';

interface LoginPageProps {
  onLogin: (email: string) => void;
}

export function LoginPage({ onLogin }: LoginPageProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    if (!email.trim() || !password.trim()) {
      setError('Enter your email and password to continue.');
      return;
    }

    setSubmitting(true);
    await new Promise((r) => setTimeout(r, 450));
    setSubmitting(false);
    onLogin(email.trim());
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

        <section className="login-panel" aria-label="Sign in">
          <header className="login-panel-header">
            <h2>Sign in</h2>
            <p>Welcome back. Continue to your visualization workspace.</p>
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
                  autoComplete="current-password"
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

            <div className="login-row">
              <label className="login-remember">
                <input type="checkbox" name="remember" />
                <span>Remember me</span>
              </label>
              <button type="button" className="login-link-btn">
                Forgot password?
              </button>
            </div>

            {error && <p className="login-error" role="alert">{error}</p>}

            <button type="submit" className="login-submit" disabled={submitting}>
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <p className="login-footer">
            Don&apos;t have an account?{' '}
            <button type="button" className="login-link-btn">
              Create one
            </button>
          </p>
        </section>
      </main>
    </div>
  );
}
