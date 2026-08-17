import { useCallback, useEffect, useRef, useState } from 'react';
import { Copy, Check, Plus, Trash2, Link2, AlertTriangle } from 'lucide-react';
import { ApiError } from '../../lib/api';
import {
  createMcpKey,
  listMcpKeys,
  revokeMcpKey,
  type McpKey,
  type McpKeyCreated,
} from '../../lib/auth';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { MCP_SNIPPETS, snippetById } from '../../lib/mcpSetup';
import { ConfirmDialog } from './ConfirmDialog';
import './ConnectionsModal.css';

interface ConnectionsModalProps {
  open: boolean;
  onClose: () => void;
}

function formatDate(value: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString();
}

/** "Never used" is the answer that matters most; don't dress it up as a date. */
function formatLastUsed(value: string | null): string {
  if (!value) return 'Never used';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return 'Never used';
  return `Last used ${d.toLocaleDateString()}`;
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard is permission-gated and fails on insecure origins. The text is
      // on screen and selectable either way, so this is a silent degradation
      // rather than an error worth interrupting the user for.
      return;
    }
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button type="button" className="conn-copy-btn" onClick={copy} aria-label={label}>
      {copied ? <Check size={14} /> : <Copy size={14} />}
      <span>{copied ? 'Copied' : 'Copy'}</span>
    </button>
  );
}

export function ConnectionsModal({ open, onClose }: ConnectionsModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const [keys, setKeys] = useState<McpKey[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [label, setLabel] = useState('');
  const [creating, setCreating] = useState(false);
  // The one and only time the key exists in the client. Cleared on close.
  const [minted, setMinted] = useState<McpKeyCreated | null>(null);
  const [snippet, setSnippet] = useState(MCP_SNIPPETS[0].id);
  const [pendingRevoke, setPendingRevoke] = useState<McpKey | null>(null);

  useEscapeToClose(onClose, open && !pendingRevoke);
  useFocusTrap(dialogRef, open && !pendingRevoke);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setKeys(await listMcpKeys());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load your connections.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  if (!open) return null;

  const handleClose = () => {
    // The key is unrecoverable once this closes, which is the point — but it
    // means closing must not be something the user does by accident while it is
    // still on screen. The panel says so before they get here.
    setMinted(null);
    setLabel('');
    setError('');
    onClose();
  };

  const handleCreate = async () => {
    setCreating(true);
    setError('');
    try {
      const created = await createMcpKey(label.trim() || 'Untitled connection');
      setMinted(created);
      setLabel('');
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create a connection link.');
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (key: McpKey) => {
    setPendingRevoke(null);
    setError('');
    try {
      await revokeMcpKey(key.id);
      if (minted?.id === key.id) setMinted(null);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not revoke that connection.');
    }
  };

  const active = keys.filter((k) => !k.revoked);
  const revoked = keys.filter((k) => k.revoked);
  const chosen = snippetById(snippet);

  return (
    <>
      <div className="conn-backdrop" role="presentation" onClick={handleClose}>
        <div
          className="conn-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="conn-title"
          ref={dialogRef}
          onClick={(e) => e.stopPropagation()}
        >
          <header className="conn-head">
            <h2 id="conn-title">
              <Link2 size={18} aria-hidden="true" /> Connections
            </h2>
            <p className="conn-copy">
              Generate a link and paste it into Claude, Gemini or any MCP host. That host can then
              analyse <strong>your</strong> datasets using its own model — AutoViz still does every
              calculation.
            </p>
          </header>

          {error && (
            <p className="conn-error" role="alert">
              {error}
            </p>
          )}

          {minted ? (
            <section className="conn-minted" aria-labelledby="conn-minted-title">
              <h3 id="conn-minted-title">
                <AlertTriangle size={15} aria-hidden="true" /> Copy this now — it is shown once
              </h3>
              <p className="conn-minted-warn">
                Anyone with this link can read and analyse your datasets. It is not stored anywhere
                you can read it back, so if you lose it, revoke it and make another. Do not commit
                it to a repository.
              </p>

              <div className="conn-tabs" role="tablist" aria-label="Setup instructions">
                {MCP_SNIPPETS.map((s) => (
                  <button
                    key={s.id}
                    role="tab"
                    type="button"
                    aria-selected={s.id === snippet}
                    className={`conn-tab${s.id === snippet ? ' conn-tab--on' : ''}`}
                    onClick={() => setSnippet(s.id)}
                  >
                    {s.label}
                  </button>
                ))}
              </div>

              <p className="conn-hint">{chosen.hint}</p>
              <div className="conn-snippet">
                <pre>
                  <code>{chosen.build(minted.url)}</code>
                </pre>
                <CopyButton text={chosen.build(minted.url)} label="Copy setup snippet" />
              </div>

              <button type="button" className="conn-btn" onClick={() => setMinted(null)}>
                Done — hide it
              </button>
            </section>
          ) : (
            <section className="conn-create">
              <label className="conn-field">
                <span>Name this connection</span>
                <input
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="Claude on my laptop"
                  maxLength={120}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !creating) void handleCreate();
                  }}
                />
              </label>
              <button
                type="button"
                className="conn-btn conn-btn--primary"
                onClick={handleCreate}
                disabled={creating}
              >
                <Plus size={15} aria-hidden="true" />
                {creating ? 'Generating…' : 'Generate link'}
              </button>
            </section>
          )}

          <section className="conn-list" aria-label="Your connections">
            {loading && <p className="conn-empty">Loading…</p>}
            {!loading && active.length === 0 && !minted && (
              <p className="conn-empty">No connections yet.</p>
            )}
            {active.map((k) => (
              <div className="conn-row" key={k.id}>
                <div className="conn-row-main">
                  <span className="conn-row-label">{k.label || 'Untitled connection'}</span>
                  <span className="conn-row-meta">
                    {k.profile} · created {formatDate(k.created_at)} · {formatLastUsed(k.last_used_at)}
                    {k.expires_at ? ` · expires ${formatDate(k.expires_at)}` : ''}
                  </span>
                </div>
                <button
                  type="button"
                  className="conn-revoke"
                  onClick={() => setPendingRevoke(k)}
                  aria-label={`Revoke ${k.label || 'this connection'}`}
                >
                  <Trash2 size={15} aria-hidden="true" />
                  Revoke
                </button>
              </div>
            ))}
            {revoked.length > 0 && (
              <details className="conn-revoked">
                <summary>{revoked.length} revoked</summary>
                {revoked.map((k) => (
                  <div className="conn-row conn-row--dead" key={k.id}>
                    <span className="conn-row-label">{k.label || 'Untitled connection'}</span>
                    <span className="conn-row-meta">revoked</span>
                  </div>
                ))}
              </details>
            )}
          </section>

          <footer className="conn-foot">
            <button type="button" className="conn-btn" onClick={handleClose}>
              Close
            </button>
          </footer>
        </div>
      </div>

      {pendingRevoke && (
        <ConfirmDialog
          title="Revoke this connection?"
          body={
            <>
              <strong>{pendingRevoke.label || 'This connection'}</strong> will stop working
              immediately. Any host still configured with it will lose access to your datasets.
              This cannot be undone — generate a new link instead.
            </>
          }
          confirmLabel="Revoke"
          destructive
          onConfirm={() => void handleRevoke(pendingRevoke)}
          onCancel={() => setPendingRevoke(null)}
        />
      )}
    </>
  );
}
