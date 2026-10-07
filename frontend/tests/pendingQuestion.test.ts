/**
 * Whether a message answers the question on screen or starts a new request.
 *
 * The defect: with a cleaning question pending, a request made from the Setup
 * panel was sent as the *answer* to it — bound to "do nothing", the paused run
 * finished, and the chart that came back answered a question the user had
 * already cancelled.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { answersPendingQuestion, type PendingPause } from '../src/lib/pendingQuestion.ts';

const cleaning: PendingPause = {
  kind: 'cleaning_choice',
  options: ['Treat them as missing', 'Treat them as real values'],
};
const clarification: PendingPause = {
  kind: 'clarification',
  options: ['Average price', 'Number of records (count)'],
};

test('clicking an option answers the question', () => {
  assert.equal(answersPendingQuestion({ text: 'Treat them as missing' }, cleaning), true);
  // Typed rather than clicked, with different case and spacing, is the same reply.
  assert.equal(answersPendingQuestion({ text: '  treat them  as MISSING ' }, cleaning), true);
});

test('a new question while a cleaning choice is pending is a new request', () => {
  assert.equal(
    answersPendingQuestion({ text: 'Number of reviews vs price under $500' }, cleaning),
    false,
  );
});

test('a Setup-panel pick or an attached chart is never an answer', () => {
  assert.equal(
    answersPendingQuestion({ text: 'Treat them as missing', chartType: 'scatter' }, cleaning),
    false,
  );
  assert.equal(
    answersPendingQuestion({ text: 'Average price', agentChartId: 'c1' }, clarification),
    false,
  );
});

test('a clarification still takes a free-text answer', () => {
  assert.equal(answersPendingQuestion({ text: 'by how many reviews they get' }, clarification), true);
});

test('with nothing known about the pause, the old behaviour stands', () => {
  assert.equal(answersPendingQuestion({ text: 'yes' }, null), true);
  assert.equal(answersPendingQuestion({ text: 'yes' }, { kind: 'confirmation', options: [] }), true);
});
