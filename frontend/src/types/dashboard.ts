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
}
