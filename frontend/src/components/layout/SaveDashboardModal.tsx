import { useEffect, useRef, useState } from 'react';
import { Save, X } from 'lucide-react';
// The overlay, panel, header and footer shells were originally shared with the dashboards
// picker but are now defined locally since DashboardsModal is gone.
import './SaveDashboardModal.css';

interface SaveDashboardModalProps {
  /** Prefilled name — the auto-generated one on first save, else the current. */
  initialName: string;
  onCancel: () => void;
  onConfirm: (name: string) => void;
}

export function SaveDashboardModal({ initialName, onCancel, onConfirm }: SaveDashboardModalProps) {
  const [name, setName] = useState(initialName);
  const overlayRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const trimmed = name.trim();

  // Select rather than just focus: the field arrives prefilled with a guess,
  // and typing over it should be the fastest thing to do.
  useEffect(() => {
    inputRef.current?.select();
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onCancel]);

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onCancel();
  };

  const submit = () => {
    if (trimmed) onConfirm(trimmed);
  };

  return (
    <div className="dashboard-modal-overlay" ref={overlayRef} onClick={handleOverlayClick}>
      <div
        className="dashboard-modal save-dashboard-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="save-dashboard-title"
      >
        <div className="dashboard-modal-header">
          <h2 id="save-dashboard-title">
            <Save size={18} />
            Name this dashboard
          </h2>
          <button className="modal-close-btn" onClick={onCancel} aria-label="Close">
            <X size={20} />
          </button>
        </div>

        <div className="dashboard-modal-body">
          <label className="save-dashboard-label" htmlFor="save-dashboard-name">
            Dashboard name
          </label>
          <input
            id="save-dashboard-name"
            ref={inputRef}
            className="save-dashboard-input"
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
          />
          <p className="save-dashboard-hint">
            Changes to this dashboard are saved automatically from here on.
          </p>
        </div>

        <div className="dashboard-modal-footer save-dashboard-footer">
          <button type="button" className="btn-cancel" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn-load" onClick={submit} disabled={!trimmed}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
