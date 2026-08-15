import { useEffect, type RefObject } from 'react';

/**
 * What counts as reachable by Tab. `[tabindex="-1"]` is deliberately excluded —
 * it means "focusable by script, not by keyboard", which is the opposite of
 * what this needs.
 */
const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function focusableWithin(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    // A control inside a collapsed panel is in the DOM and cannot be reached;
    // offsetParent is null for anything `display: none` has removed from layout.
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
}

/**
 * Keep keyboard focus inside an open dialog, and give it back afterwards.
 *
 * Every modal in this app already declared `aria-modal="true"`, which is an
 * assertion to assistive technology that the rest of the page is inert. None of
 * them implemented it: Tab walked straight out into the board behind, and
 * closing a dialog dropped focus back to `<body>`, stranding a keyboard user at
 * the top of the document. The markup was actively misinforming a screen reader
 * rather than merely omitting a feature.
 *
 * Focus moves to the first control on open, or to the container itself when
 * there is none — never left where it was, because that is outside the thing
 * claiming to be modal.
 */
export function useFocusTrap(
  ref: RefObject<HTMLElement | null>,
  active = true,
  /**
   * Where focus should land, when the first control in DOM order is the wrong
   * answer — a naming dialog wants the text field, not the close button that
   * happens to precede it in the header.
   */
  initialFocus?: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    if (!active) return;
    const container = ref.current;
    if (!container) return;

    // Captured before focus moves, so it can be handed back on close. The
    // element may be gone by then — a dialog opened from a button inside a list
    // that the dialog's own action removes — hence the `isConnected` check.
    const previous = document.activeElement as HTMLElement | null;

    const initial = initialFocus?.current ?? focusableWithin(container)[0];
    if (initial) {
      initial.focus();
    } else {
      // Nothing to focus: make the container itself the target so the dialog is
      // where the screen reader starts reading, rather than the page behind it.
      container.tabIndex = -1;
      container.focus();
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const items = focusableWithin(container);
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;

      // Wrap at both ends. The `!contains` case covers focus that has already
      // escaped — a click on the page behind, or a control removed while
      // focused — and pulls it back rather than letting Tab continue outside.
      if (!container.contains(active)) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      if (previous?.isConnected) previous.focus();
    };
  }, [ref, active, initialFocus]);
}
