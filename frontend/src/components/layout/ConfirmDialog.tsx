import { useRef } from 'react';
import { AlertTriangle } from 'lucide-react';
import { useEscapeToClose } from '../../hooks/useEscapeToClose';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import './ConfirmDialog.css';

interface ConfirmDialogProps {
  title: string;
  /**
   * What will happen, in specifics. A confirmation that cannot name the thing
   * it is about to destroy is not asking a question the user can answer.
   */
  body: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** Colours the confirm button as destructive and leads with a warning icon. */
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * The confirmation used before anything irreversible.
 *
 * Replaces `window.confirm`, which had three problems beyond being unstyled:
 * its string is fixed before the facts are known, so it cannot say *how much*
 * will be deleted; it blocks the event loop, so nothing can be computed while
 * it is up; and it is not focus-managed in a way this app controls.
 *
 * Cancel is the default focus. For a destructive action the safe choice should
 * be the one a hurried Enter lands on.
 */
export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel = 'Cancel',
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  useEscapeToClose(onCancel);
  useFocusTrap(dialogRef);

  return (
    <div
      className="confirm-overlay"
      ref={overlayRef}
      onClick={(e) => {
        if (e.target === overlayRef.current) onCancel();
      }}
    >
      <div
        className="confirm-dialog"
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-body"
      >
        <div className="confirm-head">
          {destructive && <AlertTriangle size={18} className="confirm-icon" aria-hidden />}
          <h2 id="confirm-title">{title}</h2>
        </div>

        <div className="confirm-body" id="confirm-body">
          {body}
        </div>

        <div className="confirm-actions">
          {/* First in the DOM, so it is where the focus trap lands. */}
          <button type="button" className="confirm-btn" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`confirm-btn ${destructive ? 'is-destructive' : 'is-primary'}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
