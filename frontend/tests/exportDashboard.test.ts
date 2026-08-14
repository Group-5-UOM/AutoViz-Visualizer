/**
 * File naming for exports.
 *
 * Dashboards are named by the user and datasets carry their original file name,
 * so both routinely contain characters that make a download fail outright on
 * Windows — and a name that came off an uploaded file arrives with `.csv` still
 * on the end, which would otherwise produce `titanic.csv.pdf`.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { exportFileName } from '../src/lib/exportDashboard.ts';

test('keeps an ordinary name and adds the right extension', () => {
  assert.equal(exportFileName('Quarterly revenue', 'pdf'), 'Quarterly revenue.pdf');
  assert.equal(exportFileName('Quarterly revenue', 'png'), 'Quarterly revenue.png');
});

test('drops the source file extension instead of stacking a second one', () => {
  assert.equal(exportFileName('titanic.csv', 'pdf'), 'titanic.pdf');
  assert.equal(exportFileName('sales.xlsx', 'png'), 'sales.png');
  // Not an extension — a decimal in the name must survive.
  assert.equal(exportFileName('revenue v1.2 breakdown', 'pdf'), 'revenue v1.2 breakdown.pdf');
});

test('strips characters that break a download', () => {
  // Every one of these is rejected by Windows; the slashes would also read as
  // a path and silently redirect the file.
  assert.equal(exportFileName('a/b\\c:d*e?f"g<h>i|j', 'png'), 'a-b-c-d-e-f-g-h-i-j.png');
  assert.equal(exportFileName('../../etc/passwd', 'pdf'), 'etc-passwd.pdf');
});

test('collapses separator runs and trims the edges, but keeps ordinary spaces', () => {
  assert.equal(exportFileName('  spaced   out  ', 'png'), 'spaced out.png');
  assert.equal(exportFileName('--leading and trailing--', 'pdf'), 'leading and trailing.pdf');
});

test('keeps non-Latin names rather than reducing them to hyphens', () => {
  // A blacklist of unsafe ASCII would have passed these through; a naive
  // whitelist of [A-Za-z0-9] would have destroyed them.
  assert.equal(exportFileName('café revenue', 'pdf'), 'café revenue.pdf');
  assert.equal(exportFileName('売上 2026', 'png'), '売上 2026.png');
});

test('replaces control characters, which no blacklist of punctuation would catch', () => {
  assert.equal(exportFileName('report\u0007\u001fdata', 'pdf'), 'report-data.pdf');
  assert.equal(exportFileName('line\nbreak', 'png'), 'line-break.png');
});

test('falls back to a usable name when nothing survives', () => {
  assert.equal(exportFileName('', 'pdf'), 'dashboard.pdf');
  assert.equal(exportFileName('///', 'png'), 'dashboard.png');
  assert.equal(exportFileName('   ', 'pdf'), 'dashboard.pdf');
});

test('caps the length so the write does not fail on a long name', () => {
  const name = exportFileName('x'.repeat(400), 'pdf');
  assert.ok(name.length <= 84, `name is ${name.length} characters`);
  assert.ok(name.endsWith('.pdf'));
});
