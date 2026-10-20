import { useEffect, useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, KeyRound, Link2, Trash2, User as UserIcon } from 'lucide-react';
import { ApiError, clearSession, getAccessToken, setSession } from '../lib/api';
import {
  deleteAccount,
  fetchMe,
  requestEmailChange,
  updateUsername,
} from '../lib/auth';
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
  /**
   * Drops App's signed-in user. Clearing sessionStorage alone is not enough:
   * App still holds the user in state, so /login bounced straight back to a
   * dashboard whose every request failed.
   */
  onAccountDeleted?: () => void;
  /** Keep App's header / session storage in sync after profile edits. */
  onUserUpdated?: (user: { email: string; username: string }) => void;
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
export function SettingsPage({
  userEmail,
  username,
  onAccountDeleted,
  onUserUpdated,
}: SettingsPageProps) {
  const navigate = useNavigate();
  // The board the user came from. Read once from router state at mount — the
  // section effect below rewrites the history entry with replaceState, which
  // the router does not see, so this survives it.
  const { state: navState } = useLocation();
  const backTo =
    typeof (navState as { from?: unknown } | null)?.from === 'string'
      ? (navState as { from: string }).from
      : '/dashboard';
  const [section, setSection] = useState<SectionId>(() =>
    // Deep-link support: /settings#connections lands on the right section, which
    // is what a "generate a link" instruction in a document wants to point at.
    window.location.hash.replace('#', '') === 'connections' ? 'connections' : 'account',
  );
  const [hasPassword, setHasPassword] = useState(true);
  const [providers, setProviders] = useState<string[]>([]);
  const [email, setEmail] = useState(userEmail || '');
  const [displayUsername, setDisplayUsername] = useState(username || '');
  const [usernameDraft, setUsernameDraft] = useState(username || '');
  const [emailDraft, setEmailDraft] = useState(userEmail || '');
  const [pendingEmail, setPendingEmail] = useState<string | null>(null);
  const [currentPassword, setCurrentPassword] = useState('');
  const [profileError, setProfileError] = useState('');
  const [profileOk, setProfileOk] = useState('');
  const [savingUsername, setSavingUsername] = useState(false);
  const [savingEmail, setSavingEmail] = useState(false);
  const [devVerifyUrl, setDevVerifyUrl] = useState<string | null>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [deletePassword, setDeletePassword] = useState('');
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const me = await fetchMe();
        setHasPassword(me.has_password !== false);
        setProviders(me.oauth_providers ?? []);
        setEmail(me.email);
        setEmailDraft(me.email);
        setDisplayUsername(me.username);
        setUsernameDraft(me.username);
        setPendingEmail(me.pending_email ?? null);
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

  const syncUser = (nextEmail: string, nextUsername: string) => {
    setEmail(nextEmail);
    setDisplayUsername(nextUsername);
    onUserUpdated?.({ email: nextEmail, username: nextUsername });
  };

  const handleSaveUsername = async (e: FormEvent) => {
    e.preventDefault();
    setProfileError('');
    setProfileOk('');
    setDevVerifyUrl(null);
    if (!hasPassword) {
      setProfileError('Set an AutoViz password first so this change can be confirmed.');
      return;
    }
    const next = usernameDraft.trim();
    if (next.length < 2) {
      setProfileError('Username must be at least 2 characters.');
      return;
    }
    if (!currentPassword) {
      setProfileError('Enter your current password to save.');
      return;
    }
    setSavingUsername(true);
    try {
      const me = await updateUsername(next, currentPassword);
      const token = getAccessToken();
      if (token) setSession(me.email, token, me.username);
      syncUser(me.email, me.username);
      setUsernameDraft(me.username);
      setCurrentPassword('');
      setProfileOk('Username saved.');
    } catch (err) {
      setProfileError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not save username.',
      );
    } finally {
      setSavingUsername(false);
    }
  };

  const handleSaveEmail = async (e: FormEvent) => {
    e.preventDefault();
    setProfileError('');
    setProfileOk('');
    setDevVerifyUrl(null);
    if (!hasPassword) {
      setProfileError('Set an AutoViz password first so this change can be confirmed.');
      return;
    }
    const next = emailDraft.trim().toLowerCase();
    if (!next.includes('@')) {
      setProfileError('Enter a valid email address.');
      return;
    }
    if (next === email.trim().toLowerCase()) {
      setProfileError('That is already your email address.');
      return;
    }
    if (!currentPassword) {
      setProfileError('Enter your current password to save.');
      return;
    }
    setSavingEmail(true);
    try {
      const result = await requestEmailChange(next, currentPassword);
      setPendingEmail(result.pending_email);
      setCurrentPassword('');
      setProfileOk(result.detail);
      if (result.verify_url) setDevVerifyUrl(result.verify_url);
    } catch (err) {
      setProfileError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not start the email change.',
      );
    } finally {
      setSavingEmail(false);
    }
  };

  const handleDelete = async (e: FormEvent) => {
    e.preventDefault();
    setDeleteError('');
    if (deleteConfirm.trim().toUpperCase() !== 'DELETE') {
      setDeleteError('Type DELETE to confirm.');
      return;
    }
    if (!deletePassword) {
      setDeleteError('Enter your password to confirm.');
      return;
    }
    setDeleting(true);
    try {
      await deleteAccount(deletePassword);
      clearSession();
      onAccountDeleted?.();
      navigate('/login', { replace: true });
    } catch (err) {
      setDeleteError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not delete the account.',
      );
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="set-page">
      <header className="set-topbar">
        <button
          type="button"
          className="set-back"
          onClick={() => navigate(backTo)}
          aria-label="Back to dashboard"
        >
          <ArrowLeft size={16} aria-hidden="true" />
          Back
        </button>
        <h1>Settings</h1>
        <span className="set-who">{displayUsername || email}</span>
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
                  <dt>Sign-in methods</dt>
                  <dd>
                    {[hasPassword ? 'Password' : null, ...providers]
                      .filter(Boolean)
                      .join(', ') || 'None yet'}
                  </dd>
                </div>
              </dl>

              {pendingEmail && (
                <p className="set-pending" role="status">
                  Pending email: <strong>{pendingEmail}</strong> — check that inbox for a
                  confirmation link. Your current address stays{' '}
                  <strong>{email}</strong> until you confirm.
                </p>
              )}

              <form className="set-profile-form" onSubmit={handleSaveUsername}>
                <label className="set-field">
                  <span>Username</span>
                  <input
                    value={usernameDraft}
                    onChange={(e) => setUsernameDraft(e.target.value)}
                    autoComplete="username"
                    minLength={2}
                    maxLength={64}
                    required
                  />
                </label>
                <button
                  type="submit"
                  className="set-btn set-btn--primary"
                  disabled={savingUsername || usernameDraft.trim() === displayUsername}
                >
                  {savingUsername ? 'Saving…' : 'Save username'}
                </button>
              </form>

              <form className="set-profile-form" onSubmit={handleSaveEmail}>
                <label className="set-field">
                  <span>Email</span>
                  <input
                    type="email"
                    value={emailDraft}
                    onChange={(e) => setEmailDraft(e.target.value)}
                    autoComplete="email"
                    required
                  />
                </label>
                <button
                  type="submit"
                  className="set-btn set-btn--primary"
                  disabled={
                    savingEmail || emailDraft.trim().toLowerCase() === email.trim().toLowerCase()
                  }
                >
                  {savingEmail ? 'Sending…' : 'Save email'}
                </button>
              </form>

              <label className="set-field set-field--password">
                <span>Current password</span>
                <input
                  type="password"
                  autoComplete="current-password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="Required to save username or email"
                  disabled={!hasPassword}
                />
              </label>
              {!hasPassword && (
                <p className="set-hint">
                  You signed in with {providers.join(' or ') || 'an external provider'}.{' '}
                  <button
                    type="button"
                    className="set-link"
                    onClick={() => setPasswordOpen(true)}
                  >
                    Set an AutoViz password
                  </button>{' '}
                  before changing username or email.
                </p>
              )}

              {profileError && (
                <p className="set-error" role="alert">
                  {profileError}
                </p>
              )}
              {profileOk && (
                <p className="set-ok" role="status">
                  {profileOk}
                </p>
              )}
              {devVerifyUrl && (
                <p className="set-hint" role="status">
                  Dev verify link:{' '}
                  <a href={devVerifyUrl} className="set-link">
                    {devVerifyUrl}
                  </a>
                </p>
              )}

              <button
                type="button"
                className="set-btn"
                onClick={() => setPasswordOpen(true)}
              >
                <KeyRound size={15} aria-hidden="true" />
                {hasPassword ? 'Change password' : 'Set a password'}
              </button>

              <div className="set-danger">
                <h3>Delete account</h3>
                <p>
                  Permanently removes your account, datasets, dashboards, and chat history.
                  This cannot be undone.
                </p>
                {!deleteOpen ? (
                  <button
                    type="button"
                    className="set-btn set-btn--danger"
                    onClick={() => setDeleteOpen(true)}
                    disabled={!hasPassword}
                    title={
                      hasPassword
                        ? undefined
                        : 'Set an AutoViz password first so this action can be re-authenticated.'
                    }
                  >
                    <Trash2 size={15} aria-hidden="true" />
                    Delete account…
                  </button>
                ) : null}
                {!deleteOpen && !hasPassword && (
                  <p className="set-hint">
                    You signed in with {providers.join(' or ') || 'an external provider'}.{' '}
                    <button
                      type="button"
                      className="set-link"
                      onClick={() => setPasswordOpen(true)}
                    >
                      Set an AutoViz password
                    </button>{' '}
                    first, so deleting the account can be confirmed.
                  </p>
                )}
                {deleteOpen && (
                  <form className="set-danger-form" onSubmit={handleDelete}>
                    <label className="set-field">
                      <span>Type DELETE to confirm</span>
                      <input
                        value={deleteConfirm}
                        onChange={(e) => setDeleteConfirm(e.target.value)}
                        autoComplete="off"
                        required
                      />
                    </label>
                    <label className="set-field">
                      <span>Password</span>
                      <input
                        type="password"
                        autoComplete="current-password"
                        value={deletePassword}
                        onChange={(e) => setDeletePassword(e.target.value)}
                        required
                      />
                    </label>
                    {deleteError && (
                      <p className="set-error" role="alert">
                        {deleteError}
                      </p>
                    )}
                    <div className="set-danger-actions">
                      <button
                        type="button"
                        className="set-btn"
                        onClick={() => {
                          setDeleteOpen(false);
                          setDeleteConfirm('');
                          setDeletePassword('');
                          setDeleteError('');
                        }}
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        className="set-btn set-btn--danger"
                        disabled={deleting}
                      >
                        {deleting ? 'Deleting…' : 'Delete forever'}
                      </button>
                    </div>
                  </form>
                )}
              </div>
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
