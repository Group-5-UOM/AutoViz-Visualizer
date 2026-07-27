export type SidebarItemId =
  | 'add'
  | 'setup'
  | 'filter'
  | 'ai-chat'
  | 'dashboards'
  | 'data'
  | 'settings';

export type ChartType = 'bar' | 'line' | 'pie' | 'scatter' | 'area';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  chartId?: string;
  /** Grounded answers offered with a clarification question; picking one replies. */
  options?: string[];
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
