/**
 * Pure state transitions for the canvas.
 *
 * Separate from `useDashboard` so they can be tested: the hook pulls in the
 * whole app's import graph, and a reducer that decides what gets persisted
 * deserves a test that does not need React to run.
 */
import type { DashboardState } from '../types/dashboard';

/**
 * The canvas with one widget gone.
 *
 * The invariant, and the reason this is its own function: **a canvas edit must
 * never change which board is being edited.** This reducer was written as a
 * fresh object literal — `{ widgets, selectedWidgetId }` — which silently
 * dropped `dashboardId`, `dashboardName` and `nameIsAuto`.
 *
 * Nothing caught it. All three fields are optional on `DashboardState`, so the
 * literal still type-checks; and the damage only surfaced one autosave later,
 * when `syncDashboard` found no id, called `createDashboard`, and wrote the
 * canvas to a brand new board. The board the user was editing never received
 * the deletion, so the chart was still in it when it was next opened — which
 * reads as the deleted chart coming back.
 */
export function withWidgetRemoved(state: DashboardState, id: string): DashboardState {
  return {
    ...state,
    widgets: state.widgets.filter((w) => w.id !== id),
    selectedWidgetId: state.selectedWidgetId === id ? null : state.selectedWidgetId,
  };
}
