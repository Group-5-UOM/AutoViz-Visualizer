import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, KeyRound, Link2, User as UserIcon } from 'lucide-react';
import { ApiError } from '../lib/api';
import { fetchMe } from '../lib/auth';
import { AccountPasswordModal } from '../components/layout/AccountPasswordModal';
import { ConnectionsSection } from '../components/settings/ConnectionsSection';
import './SettingsPage.css';

type SectionId = 'account' | 'connections';

const SECTIONS: { id: SectionId; label: string; icon: typeof UserIcon }[] = [
  { id: 'account', label: 'Account', icon: UserIcon },
  { id: 'connections', label: 'Connections', icon: Link2 },
];

interface SettingsPageProps {
  userEmail?: string;
  username?: string;
}

/**
 * Account settings, as a page rather than a modal.
 *
 * Connections outgrew a dialog the moment it carried setup instructions for
 * three different hosts: a modal has to be dismissed to consult anything else,
 * which is the wrong shape for something you read *while* configuring another
 * application. A page also gives the URL a place to live, so "go to settings"
 * is a link rather than a sequence of clicks.
 */
export function SettingsPage({ userEmail, username }: SettingsPageProps) {
  const navigate = useNavigate();
  const [section, setSection] = useState<SectionId>(() =>
    // Deep-link support: /settings#connections lands on the right section, which
    // is what a "generate a link" instruction in a document wants to point at.
    window.location.hash.replace('#', '') === 'connections' ? 'connections' : 'account',
  );
  const [hasPassword, setHasPassword] = useState(true);
  const [providers, setProviders] = useState<string[]>([]);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    void (async () => {
      try {
        const me = await fetchMe();
        setHasPassword(me.has_password !== false);
        setProviders(me.oauth_providers ?? []);
      } catch (err) {
        setLoadError(
          err instanceof ApiError ? err.message : 'Could not load your account details.',
        );
      }
    })();
  }, []);

  useEffect(() => {
    // Keep the address bar honest so a refresh or a shared link returns here.
    window.history.replaceState(null, '', `/settings#${section}`);
  }, [section]);

  return (
    <div className="set-page">
      <header className="set-topbar">
        <button
          type="button"
          className="set-back"
          onClick={() => navigate('/dashboard')}
          aria-label="Back to dashboard"
        >
          <ArrowLeft size={16} aria-hidden="true" />
          Back
        </button>
        <h1>Settings</h1>
        <span className="set-who">{username || userEmail}</span>
      </header>

      <div className="set-body">
        <nav className="set-nav" aria-label="Settings sections">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              className={`set-nav-item${id === section ? ' set-nav-item--on' : ''}`}
              aria-current={id === section ? 'page' : undefined}
              onClick={() => setSection(id)}
            >
              <Icon size={16} aria-hidden="true" />
              {label}
            </button>
          ))}
        </nav>

        <main className="set-main">
          {loadError && (
            <p className="set-error" role="alert">
              {loadError}
            </p>
          )}

          {section === 'account' && (
            <section className="set-section" aria-labelledby="acct-heading">
              <header className="set-section-head">
                <h2 id="acct-heading">Account</h2>
                <p>How you sign in to AutoViz.</p>
              </header>

              <dl className="set-facts">
                <div>
                  <dt>Email</dt>
                  <dd>{userEmail || '—'}</dd>
                </div>
                <div>
                  <dt>Username</dt>
                  <dd>{username || '—'}</dd>
                </div>
                <div>
                  <dt>Sign-in methods</dt>
                  <dd>
                    {[hasPassword ? 'Password' : null, ...providers]
                      .filter(Boolean)
                      .join(', ') || 'None yet'}
                  </dd>
                </div>
              </dl>

              <button
                type="button"
                className="set-btn"
                onClick={() => setPasswordOpen(true)}
              >
                <KeyRound size={15} aria-hidden="true" />
                {hasPassword ? 'Change password' : 'Set a password'}
              </button>
            </section>
          )}

          {section === 'connections' && <ConnectionsSection />}
        </main>
      </div>

      <AccountPasswordModal
        open={passwordOpen}
        hasPassword={hasPassword}
        onClose={() => setPasswordOpen(false)}
        onSaved={() => setHasPassword(true)}
      />
    </div>
  );
}
