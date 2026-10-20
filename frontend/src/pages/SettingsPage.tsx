import { useEffect, useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, Link2, Trash2, User as UserIcon } from 'lucide-react';
import { ApiError, clearSession, getAccessToken, setSession } from '../lib/api';
import {
  deleteAccount,
  fetchMe,
  requestEmailChange,
  setAccountPassword,
  updateUsername,
} from '../lib/auth';
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
  onAccountDeleted?: () => void;
  onUserUpdated?: (user: { email: string; username: string }) => void;
}

export function SettingsPage({
  userEmail,
  username,
  onAccountDeleted,
  onUserUpdated,
}: SettingsPageProps) {
  const navigate = useNavigate();
  const { state: navState } = useLocation();
  const backTo =
    typeof (navState as { from?: unknown } | null)?.from === 'string'
      ? (navState as { from: string }).from
      : '/dashboard';
  const [section, setSection] = useState<SectionId>(() =>
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
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [emailPassword, setEmailPassword] = useState('');
  const [profileError, setProfileError] = useState('');
  const [profileOk, setProfileOk] = useState('');
  const [emailError, setEmailError] = useState('');
  const [emailOk, setEmailOk] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);
  const [savingEmail, setSavingEmail] = useState(false);
  const [devVerifyUrl, setDevVerifyUrl] = useState<string | null>(null);
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
    window.history.replaceState(null, '', `/settings#${section}`);
  }, [section]);

  const syncUser = (nextEmail: string, nextUsername: string) => {
    setEmail(nextEmail);
    setDisplayUsername(nextUsername);
    onUserUpdated?.({ email: nextEmail, username: nextUsername });
  };

  const usernameDirty = usernameDraft.trim() !== displayUsername;
  const passwordDirty = newPassword.length > 0 || confirmPassword.length > 0;
  const canSaveProfile = usernameDirty || passwordDirty;

  const handleSaveProfile = async (e: FormEvent) => {
    e.preventDefault();
    setProfileError('');
    setProfileOk('');
    setDevVerifyUrl(null);

    const nextUsername = usernameDraft.trim();
    if (usernameDirty && nextUsername.length < 2) {
      setProfileError('Username must be at least 2 characters.');
      return;
    }

    if (passwordDirty) {
      if (newPassword.length < 8) {
        setProfileError('New password must be at least 8 characters.');
        return;
      }
      if (newPassword !== confirmPassword) {
        setProfileError('New passwords do not match.');
        return;
      }
    }

    if (!canSaveProfile) {
      setProfileError('Change your username or enter a new password first.');
      return;
    }

    // Username change and password change both need the current AutoViz password
    // once one exists. First-time set (OAuth-only) only needs the new password.
    if (hasPassword && !currentPassword) {
      setProfileError('Enter your current password to save.');
      return;
    }
    if (!hasPassword && usernameDirty && !passwordDirty) {
      setProfileError('Set a password below first, then you can change your username.');
      return;
    }

    setSavingProfile(true);
    const notes: string[] = [];
    const nextPassword = newPassword;
    const hadPassword = hasPassword;
    try {
      // OAuth-only: set password first so username PATCH can re-auth with it.
      // Password accounts: username first, then password (old password still valid).
      if (!hadPassword && passwordDirty) {
        await setAccountPassword(nextPassword, confirmPassword);
        setHasPassword(true);
        notes.push('Password set.');
        setNewPassword('');
        setConfirmPassword('');
      }

      if (usernameDirty) {
        const reauth = hadPassword ? currentPassword : nextPassword;
        const me = await updateUsername(nextUsername, reauth);
        const token = getAccessToken();
        if (token) setSession(me.email, token, me.username);
        syncUser(me.email, me.username);
        setUsernameDraft(me.username);
        notes.push('Username saved.');
      }

      if (hadPassword && passwordDirty) {
        const pw = await setAccountPassword(nextPassword, confirmPassword, currentPassword);
        if (pw.access_token && pw.email) {
          setSession(pw.email, pw.access_token, pw.username || displayUsername);
          syncUser(pw.email, pw.username || displayUsername);
        }
        notes.push('Password updated.');
        setNewPassword('');
        setConfirmPassword('');
      }

      setCurrentPassword('');
      setProfileOk(notes.join(' ') || 'Saved.');
    } catch (err) {
      setProfileError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not save your changes.',
      );
    } finally {
      setSavingProfile(false);
    }
  };

  const handleSaveEmail = async (e: FormEvent) => {
    e.preventDefault();
    setEmailError('');
    setEmailOk('');
    setDevVerifyUrl(null);
    if (!hasPassword) {
      setEmailError('Set an AutoViz password in the form above first.');
      return;
    }
    const next = emailDraft.trim().toLowerCase();
    if (!next.includes('@')) {
      setEmailError('Enter a valid email address.');
      return;
    }
    if (next === email.trim().toLowerCase()) {
      setEmailError('That is already your email address.');
      return;
    }
    if (!emailPassword) {
      setEmailError('Enter your current password to change email.');
      return;
    }
    setSavingEmail(true);
    try {
      const result = await requestEmailChange(next, emailPassword);
      setPendingEmail(result.pending_email);
      setEmailPassword('');
      setEmailOk(result.detail);
      if (result.verify_url) setDevVerifyUrl(result.verify_url);
    } catch (err) {
      setEmailError(
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

              <form className="set-stack-form" onSubmit={handleSaveProfile}>
                <h3 className="set-subhead">Profile</h3>
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
                {hasPassword ? (
                  <label className="set-field">
                    <span>Current password</span>
                    <input
                      type="password"
                      autoComplete="current-password"
                      value={currentPassword}
                      onChange={(e) => setCurrentPassword(e.target.value)}
                      placeholder="Required to save changes"
                    />
                  </label>
                ) : (
                  <p className="set-hint">
                    You signed in with {providers.join(' or ') || 'an external provider'}. Set a
                    password below so you can also use email sign-in and update your profile.
                  </p>
                )}
                <label className="set-field">
                  <span>{hasPassword ? 'New password' : 'Password'}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder={hasPassword ? 'Leave blank to keep current password' : 'At least 8 characters'}
                    minLength={passwordDirty ? 8 : undefined}
                  />
                </label>
                <label className="set-field">
                  <span>{hasPassword ? 'Confirm new password' : 'Confirm password'}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder={hasPassword ? 'Leave blank to keep current password' : 'Repeat password'}
                  />
                </label>
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
                <button
                  type="submit"
                  className="set-btn set-btn--primary"
                  disabled={savingProfile || !canSaveProfile}
                >
                  {savingProfile ? 'Saving…' : 'Save'}
                </button>
              </form>

              <form className="set-stack-form" onSubmit={handleSaveEmail}>
                <h3 className="set-subhead">Email</h3>
                {pendingEmail && (
                  <p className="set-pending" role="status">
                    Pending: <strong>{pendingEmail}</strong> — check that inbox. Current address
                    stays <strong>{email}</strong> until you confirm.
                  </p>
                )}
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
                <label className="set-field">
                  <span>Current password</span>
                  <input
                    type="password"
                    autoComplete="current-password"
                    value={emailPassword}
                    onChange={(e) => setEmailPassword(e.target.value)}
                    placeholder="Required to change email"
                    disabled={!hasPassword}
                  />
                </label>
                {emailError && (
                  <p className="set-error" role="alert">
                    {emailError}
                  </p>
                )}
                {emailOk && (
                  <p className="set-ok" role="status">
                    {emailOk}
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
                  type="submit"
                  className="set-btn set-btn--primary"
                  disabled={
                    savingEmail ||
                    !hasPassword ||
                    emailDraft.trim().toLowerCase() === email.trim().toLowerCase()
                  }
                >
                  {savingEmail ? 'Sending…' : 'Save email'}
                </button>
              </form>

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
                    Set a password in the Profile section first, so deleting the account can be
                    confirmed.
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
    </div>
  );
}
