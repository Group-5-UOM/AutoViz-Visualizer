import { useCallback, useEffect, useRef, useState } from 'react';
import { Copy, Check, Plus, Trash2, AlertTriangle } from 'lucide-react';
import { ApiError } from '../../lib/api';
import {
  createMcpKey,
  listMcpKeys,
  revokeMcpKey,
  type McpKey,
  type McpKeyCreated,
} from '../../lib/auth';
import { MCP_SNIPPETS, snippetById } from '../../lib/mcpSetup';
import { ConfirmDialog } from '../layout/ConfirmDialog';
import './ConnectionsSection.css';

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
      // Clipboard is permission-gated and unavailable on insecure origins. The
      // text is on screen and selectable either way, so this degrades silently
      // rather than interrupting with an error the user cannot act on.
      return;
    }
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button type="button" className="conn-copy-btn" onClick={copy} aria-label={label}>
      {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
      <span>{copied ? 'Copied' : 'Copy'}</span>
    </button>
  );
}

/**
 * MCP connection links — generate, copy once, revoke.
 *
 * A page section rather than a modal: this is account configuration a user
 * returns to, and it carries setup instructions long enough that a dialog fights
 * them for room.
 */
export function ConnectionsSection() {
  const [keys, setKeys] = useState<McpKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [label, setLabel] = useState('');
  const [creating, setCreating] = useState(false);
  // The one and only time the key exists in the client.
  const [minted, setMinted] = useState<McpKeyCreated | null>(null);
  const [snippet, setSnippet] = useState(MCP_SNIPPETS[0].id);
  const [pendingRevoke, setPendingRevoke] = useState<McpKey | null>(null);

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
    void refresh();
  }, [refresh]);

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
    <section className="set-section" aria-labelledby="conn-heading">
      <header className="set-section-head">
        <h2 id="conn-heading">Connections</h2>
        <p>
          Generate a link and paste it into Claude, Gemini or any MCP host. That host can then
          analyse <strong>your</strong> datasets using its own model — AutoViz still runs every
          calculation and every number stays traceable to a query.
        </p>
      </header>

      {error && (
        <p className="set-error" role="alert">
          {error}
        </p>
      )}

      {minted && (
        <div className="conn-minted">
          <h3>
            <AlertTriangle size={15} aria-hidden="true" /> Copy this now — it is shown once
          </h3>
          <p className="conn-minted-warn">
            Anyone with this link can read and analyse your datasets. It is not stored anywhere you
            can read it back, so if you lose it, revoke it and make another. Don't commit it to a
            repository.
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

          {/* The Copy button sits in its own bar above the code, not floating on
              top of it. A long URL wraps to two lines, and an overlaid button
              covered the end of it — which is precisely the part you need. */}
          <div className="conn-snippet">
            <div className="conn-snippet-bar">
              <span className="conn-hint">{chosen.hint}</span>
              <CopyButton text={chosen.build(minted.url)} label="Copy setup snippet" />
            </div>
            <pre>
              <code>{chosen.build(minted.url)}</code>
            </pre>
          </div>

          <button type="button" className="set-btn" onClick={() => setMinted(null)}>
            Done — hide it
          </button>
        </div>
      )}

      <div className="conn-create">
        <label className="set-field">
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
          className="set-btn set-btn--primary"
          onClick={handleCreate}
          disabled={creating}
        >
          <Plus size={15} aria-hidden="true" />
          {creating ? 'Generating…' : 'Generate link'}
        </button>
      </div>

      <div className="conn-list">
        {loading && <p className="set-empty">Loading…</p>}
        {!loading && active.length === 0 && (
          <p className="set-empty">No connections yet.</p>
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
      </div>

      {pendingRevoke && (
        <ConfirmDialog
          title="Revoke this connection?"
          body={
            <>
              <strong>{pendingRevoke.label || 'This connection'}</strong> will stop working
              immediately. Any host still configured with it loses access to your datasets. This
              cannot be undone — generate a new link instead.
            </>
          }
          confirmLabel="Revoke"
          destructive
          onConfirm={() => void handleRevoke(pendingRevoke)}
          onCancel={() => setPendingRevoke(null)}
        />
      )}
    </section>
  );
}
