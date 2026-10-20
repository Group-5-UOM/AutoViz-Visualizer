import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ApiError } from '../lib/api';
import { confirmEmailChange } from '../lib/auth';
import './LoginPage.css';

interface VerifyEmailPageProps {
  onVerified?: (user: { email: string; username: string }) => void;
}

export function VerifyEmailPage({ onVerified }: VerifyEmailPageProps) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get('token') || '';
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [email, setEmail] = useState('');
  const onVerifiedRef = useRef(onVerified);
  onVerifiedRef.current = onVerified;

  useEffect(() => {
    if (!token) {
      setError('Missing confirmation token. Use the link from the email again.');
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const data = await confirmEmailChange(token);
        if (cancelled) return;
        const nextEmail = data.email || '';
        const nextUsername = data.username || nextEmail.split('@')[0] || '';
        setEmail(nextEmail);
        setDone(true);
        onVerifiedRef.current?.({ email: nextEmail, username: nextUsername });
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : 'Could not confirm the new email.',
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="login-page">
      <main className="login-shell">
        <section className="login-panel">
          <header className="login-panel-header">
            <h2>Confirm email</h2>
            <p>Finishing the email change for your AutoViz account.</p>
          </header>

          {done ? (
            <>
              <p className="login-error" role="status" style={{ color: 'var(--text-primary)' }}>
                Your email is now {email || 'updated'}. You are signed in with the new address.
              </p>
              <button
                type="button"
                className="login-submit"
                onClick={() => navigate('/settings', { replace: true })}
              >
                Go to Settings
              </button>
            </>
          ) : error ? (
            <>
              <p className="login-error" role="alert">
                {error}
              </p>
              <button
                type="button"
                className="login-submit"
                onClick={() => navigate('/settings', { replace: true })}
              >
                Back to Settings
              </button>
            </>
          ) : (
            <p className="login-error" role="status" style={{ color: 'var(--text-primary)' }}>
              Confirming…
            </p>
          )}
        </section>
      </main>
    </div>
  );
}
