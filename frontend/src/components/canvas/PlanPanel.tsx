import { useEffect, useMemo, useState } from 'react';
import { Braces, RotateCcw, X } from 'lucide-react';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';
import type { ChartWidget } from '../../types/dashboard';
import './PlanPanel.css';

/**
 * View and edit the analysis_plan JSON that produced a chart.
 *
 * The agent already returns this on every chart; the canvas previously dropped
 * it. Editing here re-runs `POST /analysis/pipeline` — the same deterministic
 * path the agent worker uses — so the LLM is not involved in the re-run.
 */

interface PlanPanelProps {
  widget: ChartWidget;
  datasetId: string | null;
  busy: boolean;
  /** Apply an edited plan. Resolves to an error message, or null on success. */
  onApply: (plan: Record<string, unknown>) => Promise<string | null>;
  onClose: () => void;
}

function pretty(plan: Record<string, unknown> | null | undefined): string {
  return JSON.stringify(plan ?? {}, null, 2);
}

export function PlanPanel({ widget, datasetId, busy, onApply, onClose }: PlanPanelProps) {
  const initial = useMemo(() => pretty(widget.plan), [widget.id, widget.plan]);
  const [text, setText] = useState(initial);
  const [parseError, setParseError] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  useEscapeToClose(onClose);

  useEffect(() => {
    setText(pretty(widget.plan));
    setParseError(null);
    setApplyError(null);
  }, [widget.id, widget.plan]);

  const dirty = text.trim() !== initial.trim();
  const hasPlan = Boolean(widget.plan && Object.keys(widget.plan).length > 0);

  const handleReset = () => {
    setText(initial);
    setParseError(null);
    setApplyError(null);
  };

  const handleApply = async () => {
    setParseError(null);
    setApplyError(null);
    if (!datasetId) {
      setApplyError('Add a dataset to the board before running a plan.');
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (err) {
      setParseError(err instanceof Error ? err.message : 'Invalid JSON');
      return;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setParseError('The plan must be a JSON object.');
      return;
    }
    const plan = { ...(parsed as Record<string, unknown>), dataset_id: datasetId };
    setText(pretty(plan));
    const failure = await onApply(plan);
    if (failure) setApplyError(failure);
  };

  return (
    <aside className="plan-panel" aria-label="Analysis plan editor">
      <header className="plan-panel-header">
        <Braces size={14} aria-hidden />
        <p className="plan-panel-subject" title={widget.title}>
          Plan · {widget.title}
        </p>
        <button
          type="button"
          className="plan-panel-close"
          onClick={onClose}
          aria-label="Close plan editor"
        >
          <X size={16} />
        </button>
      </header>

      <div className="plan-panel-body">
        <p className="plan-panel-hint">
          This is the structured analysis plan the AI used for this chart. Edit
          the JSON, then run it to rebuild the chart without asking the AI again.
        </p>

        {!hasPlan && (
          <p className="plan-panel-empty">
            No plan is stored on this chart yet. Ask the AI for a chart first, or
            paste a plan below.
          </p>
        )}

        <label className="plan-field">
          <span className="plan-field-label">analysis_plan</span>
          <textarea
            className="plan-editor"
            spellCheck={false}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setParseError(null);
              setApplyError(null);
            }}
            disabled={busy}
            aria-invalid={Boolean(parseError)}
          />
        </label>

        {(parseError || applyError) && (
          <p className="plan-panel-error" role="alert">
            {parseError || applyError}
          </p>
        )}
      </div>

      <footer className="plan-panel-footer">
        <button
          type="button"
          className="plan-btn plan-btn-ghost"
          onClick={handleReset}
          disabled={busy || !dirty}
          title="Restore the plan currently on this chart"
        >
          <RotateCcw size={14} />
          Reset
        </button>
        <button
          type="button"
          className="plan-btn plan-btn-primary"
          onClick={() => void handleApply()}
          disabled={busy || !datasetId}
        >
          {busy ? 'Running…' : 'Run plan'}
        </button>
      </footer>
    </aside>
  );
}
