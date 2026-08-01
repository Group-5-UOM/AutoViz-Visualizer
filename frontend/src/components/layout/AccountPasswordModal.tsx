import { useState, type FormEvent } from 'react';
import { ApiError } from '../../lib/api';
import { setAccountPassword } from '../../lib/auth';
import './AccountPasswordModal.css';

interface AccountPasswordModalProps {
  open: boolean;
  hasPassword: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function AccountPasswordModal({
  open,
  hasPassword,
  onClose,
  onSaved,
}: AccountPasswordModalProps) {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  if (!open) return null;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    setSaving(true);
    try {
      await setAccountPassword(password, confirm);
      setPassword('');
      setConfirm('');
      onSaved();
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Could not save password.',
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="pwd-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="pwd-modal"
        role="dialog"
        aria-labelledby="pwd-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="pwd-modal-title">{hasPassword ? 'Change password' : 'Set a password'}</h2>
        <p className="pwd-modal-copy">
          {hasPassword
            ? 'Update the password you use with email sign-in.'
            : 'Add an AutoViz password so you can also sign in with email — Google/GitHub will keep working.'}
        </p>
        <form onSubmit={handleSubmit}>
          <label className="pwd-field">
            <span>New password</span>
            <input
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </label>
          <label className="pwd-field">
            <span>Confirm password</span>
            <input
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              minLength={8}
              required
            />
          </label>
          {error && (
            <p className="pwd-error" role="alert">
              {error}
            </p>
          )}
          <div className="pwd-actions">
            <button type="button" className="pwd-btn pwd-btn--ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="pwd-btn pwd-btn--primary" disabled={saving}>
              {saving ? 'Saving…' : 'Save password'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
