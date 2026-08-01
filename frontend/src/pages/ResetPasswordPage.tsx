import { useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ApiError } from '../lib/api';
import { resetPassword } from '../lib/auth';
import './LoginPage.css';

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token') || '';
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (!token) {
      setError('Missing reset token. Use the link from Forgot password again.');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(token, password, confirm);
      setDone(true);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not reset password.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <main className="login-shell">
        <section className="login-panel">
          <header className="login-panel-header">
            <h2>Set AutoViz password</h2>
            <p>Choose a password for email sign-in. Google/GitHub sign-in will still work.</p>
          </header>

          {done ? (
            <>
              <p className="login-error" role="status" style={{ color: 'var(--text-primary)' }}>
                Password saved. You can sign in with email and password now.
              </p>
              <button
                type="button"
                className="login-submit"
                onClick={() => navigate('/login', { replace: true })}
              >
                Go to sign in
              </button>
            </>
          ) : (
            <form className="login-form" onSubmit={handleSubmit}>
              <label className="login-field">
                <span className="login-label">New password</span>
                <span className="login-input-wrap">
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={8}
                  />
                </span>
              </label>
              <label className="login-field">
                <span className="login-label">Confirm password</span>
                <span className="login-input-wrap">
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    required
                    minLength={8}
                  />
                </span>
              </label>
              {error && (
                <p className="login-error" role="alert">
                  {error}
                </p>
              )}
              <button type="submit" className="login-submit" disabled={submitting}>
                {submitting ? 'Saving…' : 'Save password'}
              </button>
            </form>
          )}
        </section>
      </main>
    </div>
  );
}
