import { AlertTriangle, CheckCircle2, Info, Loader2, X } from 'lucide-react';
import type { Notice } from '../../hooks/useNotices';
import './NoticeStack.css';

interface NoticeStackProps {
  notices: Notice[];
  onDismiss: (id: number) => void;
}

const ICONS = {
  working: Loader2,
  success: CheckCircle2,
  validation: Info,
  error: AlertTriangle,
} as const;

/**
 * The visible half of the notice channel.
 *
 * `role="status"` rather than `role="alert"`: these are announced politely so a
 * screen-reader user is told what happened without having the sentence they
 * were reading interrupted. Failures are not auto-dismissed, so there is no
 * risk of one being announced and then gone.
 */
export function NoticeStack({ notices, onDismiss }: NoticeStackProps) {
  if (notices.length === 0) return null;

  return (
    <div className="notice-stack" role="status" aria-live="polite">
      {notices.map((notice) => {
        const Icon = ICONS[notice.kind];
        return (
          <div key={notice.id} className={`notice notice--${notice.kind}`}>
            <Icon
              size={16}
              className={notice.kind === 'working' ? 'notice-icon is-spinning' : 'notice-icon'}
              aria-hidden
            />
            <span className="notice-message">{notice.message}</span>
            {notice.action && (
              <button type="button" className="notice-retry" onClick={notice.action.onClick}>
                {notice.action.label}
              </button>
            )}
            {notice.kind !== 'working' && (
              <button
                type="button"
                className="notice-dismiss"
                onClick={() => onDismiss(notice.id)}
                aria-label="Dismiss"
              >
                <X size={14} />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
