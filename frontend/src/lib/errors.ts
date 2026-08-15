/**
 * The error taxonomy shared by every call into the backend.
 *
 * Split out of `api.ts` so it can be exercised without a browser: `api.ts`
 * reads `import.meta.env` at module scope, which is a Vite construct and throws
 * under Node. Nothing here touches the DOM or the network, and `api.ts`
 * re-exports all of it, so call sites keep importing from one place.
 */

/**
 * Which of the FR-19 error states a failure belongs to.
 *
 * `validation` — the request was understood and rejected. Sending it again
 * unchanged fails again, so the UI must not offer a retry; it must say what to
 * change.
 * `recoverable` — the request never got a verdict: a timeout, a dropped
 * connection, a backend that fell over. The same action may well succeed, so a
 * retry is the right thing to put in front of the user.
 * `fatal` — neither retrying nor rewording helps here (an expired session is
 * the case that matters, and is handled by signing the user out).
 */
export type ErrorKind = 'validation' | 'recoverable' | 'fatal';

/**
 * Backend taxonomy codes, split by what the user can do about them.
 *
 * These names come from `autoviz.errors` and reach the browser in the response
 * body as `error_code`. Codes absent from both sets fall back to the HTTP
 * status, which is why an unrecognised code is not a problem.
 */
const VALIDATION_CODES = new Set([
  'INVALID_PLAN',
  'TYPE_MISMATCH',
  'INVALID_SPEC',
  'NO_CHART_FIT',
  'UNKNOWN_DATASET',
  'RESOURCE_LIMIT',
  'FILE_ERROR',
  'FORBIDDEN_PATH',
]);

const RECOVERABLE_CODES = new Set(['EXECUTION_ERROR', 'TIMEOUT', 'CANCELLED']);

/** Status used when the request never reached the server at all. */
export const NETWORK_ERROR_STATUS = 0;

export class ApiError extends Error {
  status: number;

  /**
   * The backend's typed `error_code`, when it sent one.
   *
   * Carried rather than folded into the message because it is the only thing
   * that separates "your question cannot be answered from this data" from "the
   * query timed out" — the two need different UI, and the prose does not
   * reliably distinguish them.
   */
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }

  get kind(): ErrorKind {
    if (this.code && VALIDATION_CODES.has(this.code)) return 'validation';
    if (this.code && RECOVERABLE_CODES.has(this.code)) return 'recoverable';
    if (this.status === NETWORK_ERROR_STATUS) return 'recoverable';
    if (this.status === 401) return 'fatal';
    if (this.status === 408 || this.status === 429 || this.status >= 500) return 'recoverable';
    if (this.status >= 400) return 'validation';
    return 'recoverable';
  }
}

/** The FR-19 class of any thrown value, including ones that are not `ApiError`. */
export function classifyError(err: unknown): ErrorKind {
  if (err instanceof ApiError) return err.kind;
  // An unrecognised throw is treated as recoverable: offering a retry that does
  // nothing is a smaller failure than refusing one that would have worked.
  return 'recoverable';
}

/** True when re-running the same action is worth offering. */
export function isRetryable(err: unknown): boolean {
  return classifyError(err) === 'recoverable';
}

/** The message to show for a thrown value, whatever kind of thing it is. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong talking to the server.';
}
