import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { applyOAuthSession } from '../lib/auth';
import './LoginPage.css';

interface OAuthCallbackPageProps {
  onLogin: (user: { email: string; username: string }) => void;
}

/**
 * Handles backend OAuth redirects:
 * - Existing user: ?token=&email=&username= → dashboard
 * - New email: ?pending_token=&email= → register on /login
 * - Failure: ?error=
 */
export function OAuthCallbackPage({ onLogin }: OAuthCallbackPageProps) {
  const navigate = useNavigate();
  const [message, setMessage] = useState('Signing you in…');

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const queryError = query.get('error');
    if (queryError) {
      setMessage(queryError);
      return;
    }

    const pendingToken = query.get('pending_token');
    const email = query.get('email');
    if (pendingToken && email) {
      navigate(
        `/login?${new URLSearchParams({
          mode: 'register',
          email,
          pending: pendingToken,
        }).toString()}`,
        { replace: true },
      );
      return;
    }

    const token = query.get('token');
    const username = query.get('username') || email?.split('@')[0] || '';
    if (token && email) {
      applyOAuthSession(email, token, username);
      onLogin({ email, username });
      navigate('/dashboard', { replace: true });
      return;
    }

    setMessage('Missing OAuth credentials. Return to login and try again.');
  }, [navigate, onLogin]);

  return (
    <div className="login-page">
      <main className="login-shell">
        <section className="login-card" aria-live="polite">
          <h1 className="login-brand">AutoViz AI</h1>
          <p className="login-error" role="status">
            {message}
          </p>
          <p className="login-footer">
            <button
              type="button"
              className="login-link-btn"
              onClick={() => navigate('/login', { replace: true })}
            >
              Back to sign in
            </button>
          </p>
        </section>
      </main>
    </div>
  );
}
