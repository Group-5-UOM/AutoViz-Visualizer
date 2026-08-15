import { useCallback, useEffect, useRef, useState } from 'react';
import { classifyError, errorMessage, type ErrorKind } from '../lib/api';

/**
 * What a notice is telling the user, in the vocabulary FR-19 uses.
 *
 * `working` is the loading state for an action with no widget of its own to put
 * a spinner in — exporting, mainly, where the thing being worked on is the whole
 * canvas.
 */
export type NoticeKind = 'working' | 'success' | 'validation' | 'error';

/**
 * The one thing a notice offers the user to do about it.
 *
 * Deliberately open rather than a fixed "retry": the same banner shape carries
 * "Try again" after a failed export and "Undo" after a deleted chart, and those
 * are the same interaction — a single reversal of the thing just reported.
 */
export interface NoticeAction {
  label: string;
  onClick: () => void;
}

export interface Notice {
  id: number;
  kind: NoticeKind;
  message: string;
  /**
   * A retry is present only on recoverable failures. A validation error never
   * carries one: re-sending a rejected request produces the same rejection, and
   * a button that promises otherwise is worse than no button.
   */
  action?: NoticeAction;
}

/** How long a self-clearing notice stays up. Failures never self-clear. */
const SUCCESS_MS = 4000;

/**
 * The application's one channel for things the user needs told about.
 *
 * It exists because the alternative had become `window.alert` in one place,
 * `console.error` in four others, and a red Save button whose reason was
 * computed and then dropped. Those are the same state — a failed action — and
 * they now render the same way.
 *
 * A notice can be replaced in place by giving it a `key`, so a retry updates the
 * banner the user is looking at instead of stacking a second one underneath it.
 */
export function useNotices() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const nextId = useRef(1);
  const keys = useRef(new Map<string, number>());
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    setNotices((prev) => prev.filter((n) => n.id !== id));
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
    for (const [key, value] of keys.current) {
      if (value === id) keys.current.delete(key);
    }
  }, []);

  /** Clear a keyed notice if it is up — the "it worked after all" path. */
  const dismissKey = useCallback(
    (key: string) => {
      const id = keys.current.get(key);
      if (id !== undefined) dismiss(id);
    },
    [dismiss],
  );

  const notify = useCallback(
    (notice: Omit<Notice, 'id'> & { key?: string }): number => {
      const { key, ...rest } = notice;
      const existing = key ? keys.current.get(key) : undefined;
      const id = existing ?? nextId.current++;
      if (key) keys.current.set(key, id);

      const previousTimer = timers.current.get(id);
      if (previousTimer !== undefined) {
        window.clearTimeout(previousTimer);
        timers.current.delete(id);
      }

      setNotices((prev) => {
        const next: Notice = { ...rest, id };
        const at = prev.findIndex((n) => n.id === id);
        if (at === -1) return [...prev, next];
        const copy = [...prev];
        copy[at] = next;
        return copy;
      });

      // Success is confirmation, not information: it goes away on its own.
      // Anything the user has to act on stays until they dismiss it.
      if (rest.kind === 'success') {
        timers.current.set(
          id,
          window.setTimeout(() => dismiss(id), SUCCESS_MS),
        );
      }
      return id;
    },
    [dismiss],
  );

  /**
   * Report a caught failure, choosing the state and the retry affordance from
   * the error itself rather than from the call site.
   */
  const notifyError = useCallback(
    (err: unknown, context: string, options: { key?: string; onRetry?: () => void } = {}) => {
      const kind: ErrorKind = classifyError(err);
      notify({
        key: options.key,
        kind: kind === 'validation' ? 'validation' : 'error',
        message: `${context} ${errorMessage(err)}`,
        action:
          kind === 'recoverable' && options.onRetry
            ? { label: 'Try again', onClick: options.onRetry }
            : undefined,
      });
    },
    [notify],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending.values()) window.clearTimeout(timer);
      pending.clear();
    };
  }, []);

  return { notices, notify, notifyError, dismiss, dismissKey };
}
