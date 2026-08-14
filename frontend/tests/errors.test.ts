/**
 * The error taxonomy behind FR-19's validation-error / recoverable-error split.
 *
 * What is actually being pinned here is which failures get a "Try again"
 * button. Offering one on a rejected request sends the user round a loop that
 * cannot succeed; withholding one on a dropped connection makes them retype a
 * question the server never saw. Both are decided by the table below and
 * nowhere else, so the table is what is tested.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ApiError,
  NETWORK_ERROR_STATUS,
  classifyError,
  errorMessage,
  isRetryable,
} from '../src/lib/errors.ts';

test('typed backend codes decide the kind, whatever the HTTP status says', () => {
  // A plan the validator refused: the user must change the question.
  assert.equal(new ApiError('bad plan', 422, 'INVALID_PLAN').kind, 'validation');
  assert.equal(new ApiError('wrong type', 422, 'TYPE_MISMATCH').kind, 'validation');
  assert.equal(new ApiError('too big', 413, 'RESOURCE_LIMIT').kind, 'validation');
  assert.equal(new ApiError('no such dataset', 404, 'UNKNOWN_DATASET').kind, 'validation');
  assert.equal(new ApiError('no chart fits', 400, 'NO_CHART_FIT').kind, 'validation');

  // The query never produced a verdict: the same request may still work.
  assert.equal(new ApiError('query blew up', 500, 'EXECUTION_ERROR').kind, 'recoverable');
  assert.equal(new ApiError('too slow', 504, 'TIMEOUT').kind, 'recoverable');
});

test('EXECUTION_ERROR is recoverable even though its status is 500-shaped, and a 400 without a code is not', () => {
  // The point of carrying error_code at all: status alone gets these wrong in
  // both directions if the mapping ever changes on the backend.
  assert.equal(isRetryable(new ApiError('x', 500, 'EXECUTION_ERROR')), true);
  assert.equal(isRetryable(new ApiError('x', 400)), false);
});

test('status decides when the backend sent no code', () => {
  assert.equal(new ApiError('nope', 400).kind, 'validation');
  assert.equal(new ApiError('forbidden', 403).kind, 'validation');
  assert.equal(new ApiError('gone', 404).kind, 'validation');
  assert.equal(new ApiError('unprocessable', 422).kind, 'validation');

  assert.equal(new ApiError('slow', 408).kind, 'recoverable');
  assert.equal(new ApiError('slow down', 429).kind, 'recoverable');
  assert.equal(new ApiError('boom', 500).kind, 'recoverable');
  assert.equal(new ApiError('gateway', 502).kind, 'recoverable');
});

test('an expired session is fatal, not something to retry', () => {
  const expired = new ApiError('Invalid or expired token', 401);
  assert.equal(expired.kind, 'fatal');
  assert.equal(isRetryable(expired), false);
});

test('a request that never reached the server is recoverable', () => {
  const offline = new ApiError('Could not reach the server.', NETWORK_ERROR_STATUS);
  assert.equal(offline.kind, 'recoverable');
  assert.equal(isRetryable(offline), true);
});

test('an unrecognised code falls through to the status rather than being dropped', () => {
  // A code the frontend has never heard of must not silently become fatal.
  assert.equal(new ApiError('new code', 422, 'SOMETHING_NEW').kind, 'validation');
  assert.equal(new ApiError('new code', 503, 'SOMETHING_NEW').kind, 'recoverable');
});

test('non-ApiError throws are treated as recoverable', () => {
  // A retry that does nothing is a smaller failure than refusing one that would
  // have worked.
  assert.equal(classifyError(new TypeError('Failed to fetch')), 'recoverable');
  assert.equal(classifyError('a string'), 'recoverable');
  assert.equal(classifyError(undefined), 'recoverable');
});

test('errorMessage prefers the server sentence and always returns something', () => {
  assert.equal(errorMessage(new ApiError('Column "prive" not found', 422)), 'Column "prive" not found');
  assert.equal(errorMessage(new Error('boom')), 'boom');
  assert.equal(errorMessage({ weird: true }), 'Something went wrong talking to the server.');
  assert.equal(errorMessage(null), 'Something went wrong talking to the server.');
});
