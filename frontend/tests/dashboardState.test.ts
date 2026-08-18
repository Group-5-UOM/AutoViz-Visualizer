/**
 * Deleting a chart must not change which board is being edited.
 *
 * The bug this pins: `deleteWidget` rebuilt the canvas as a fresh object
 * literal, `{ widgets, selectedWidgetId }`, which dropped `dashboardId`,
 * `dashboardName` and `nameIsAuto`. All three are optional on DashboardState,
 * so it type-checked; the compiler had nothing to say.
 *
 * The damage landed one autosave later. `syncDashboard` creates a board when it
 * finds no `dashboardId`, so the canvas was written to a NEW board and the board
 * the user was actually editing never received the deletion — leaving the
 * deleted chart in it, to reappear the next time it was opened.
 *
 * Two symptoms, one dropped field, and no error anywhere in between. That gap
 * between cause and effect is why this is tested on the reducer rather than
 * anywhere further downstream.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { withWidgetRemoved } from '../src/lib/dashboardState.ts';
import type { ChartWidget, DashboardState } from '../src/types/dashboard.ts';

const widget = (id: string): ChartWidget =>
  ({ id, x: 0, y: 0, width: 4, height: 3, title: id }) as ChartWidget;

/** A board that has been saved at least once, so it has a server identity. */
const saved = (): DashboardState => ({
  widgets: [widget('a'), widget('b')],
  selectedWidgetId: 'a',
  dashboardId: 'dash_123',
  dashboardName: 'Tips',
  nameIsAuto: true,
});

test('deleting a chart keeps the board identity that autosave routes on', () => {
  const after = withWidgetRemoved(saved(), 'a');

  // The one field the whole bug turned on: without it the next autosave calls
  // createDashboard and the edit lands on a board the user never opened.
  assert.equal(after.dashboardId, 'dash_123');
  assert.equal(after.dashboardName, 'Tips');
  assert.equal(after.nameIsAuto, true);
});

test('the widget is actually gone and the others are untouched', () => {
  const after = withWidgetRemoved(saved(), 'a');
  assert.deepEqual(
    after.widgets.map((w) => w.id),
    ['b'],
  );
});

test('deleting the selected chart clears the selection, deleting another leaves it', () => {
  assert.equal(withWidgetRemoved(saved(), 'a').selectedWidgetId, null);
  assert.equal(withWidgetRemoved(saved(), 'b').selectedWidgetId, 'a');
});

test('deleting the last chart still keeps the board identity', () => {
  // The emptied-canvas case matters most: autosave skips a board with no
  // widgets AND no id, so losing the id here would silently drop the delete
  // instead of persisting an empty board.
  const one: DashboardState = {
    widgets: [widget('only')],
    selectedWidgetId: 'only',
    dashboardId: 'dash_123',
    dashboardName: 'Tips',
  };
  const after = withWidgetRemoved(one, 'only');
  assert.deepEqual(after.widgets, []);
  assert.equal(after.dashboardId, 'dash_123');
});

test('deleting an id that is not on the canvas changes nothing', () => {
  const before = saved();
  const after = withWidgetRemoved(before, 'nope');
  assert.deepEqual(after, before);
});

test('an unsaved board stays unsaved rather than inventing an id', () => {
  const fresh: DashboardState = { widgets: [widget('a')], selectedWidgetId: null };
  const after = withWidgetRemoved(fresh, 'a');
  assert.equal(after.dashboardId, undefined);
});
