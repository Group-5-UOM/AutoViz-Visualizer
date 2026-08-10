import { useEffect } from 'react';

/**
 * Close a panel with the Escape key.
 *
 * The side panels used to carry a header with a close button; that header was
 * removed because it only repeated the label already shown in the sidebar. The
 * sidebar button still toggles each panel shut, but that is a mouse target —
 * without this, a keyboard user has no way out. Call it before any early
 * `return null`, and pass `active` so a closed panel is not listening.
 */
export function useEscapeToClose(onClose: () => void, active = true) {
  useEffect(() => {
    if (!active) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [active, onClose]);
}
