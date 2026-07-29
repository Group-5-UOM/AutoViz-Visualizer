export type SidebarItemId =
  | 'add'
  | 'setup'
  | 'filter'
  | 'ai-chat'
  | 'dashboards'
  | 'data'
  | 'settings';

export type ChartType = 'bar' | 'line' | 'pie' | 'scatter' | 'area';

/**
 * One offered answer. `label` is both the button text and the reply sent back,
 * so it must not be reworded on the way out. `detail` carries what the choice
 * costs in real numbers, and `technique` the underlying method — shown quietly,
 * because a user who does not know what imputation is still has to decide.
 */
export interface ChatOption {
  label: string;
  detail?: string;
  technique?: string;
  recommended?: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  chartId?: string;
  /** Grounded answers offered with a question; picking one replies with its label. */
  options?: ChatOption[];
  timestamp: number;
}

export interface ChartWidget {
  id: string;
  title: string;
  explanation: string;
  vegaLiteSpec: Record<string, unknown>;
  x: number;
  y: number;
  width: number;
  height: number;
  backendChartId?: string;
}

export interface DashboardState {
  widgets: ChartWidget[];
  selectedWidgetId: string | null;
  dashboardId?: string;
  dashboardName?: string;
  /**
   * The name was invented by autosave rather than chosen. Set while a board is
   * still called something like "Titanic", cleared once the user names it —
   * which is how Save knows to ask for a name exactly once.
   */
  nameIsAuto?: boolean;
}

/**
 * Where the canvas stands relative to the server.
 *
 * `error` is sticky: autosave stops retrying on a timer so a dead backend is
 * not hammered every couple of seconds, and the Save button re-arms it.
 */
export type SaveStatus = 'idle' | 'dirty' | 'saving' | 'saved' | 'error';
