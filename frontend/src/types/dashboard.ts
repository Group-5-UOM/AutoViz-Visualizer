export type SidebarItemId =
  | 'add'
  | 'setup'
  | 'filter'
  | 'ai-chat'
  | 'dashboards'
  | 'data'
  | 'settings';

export type ChartType =
  | 'bar'
  | 'line'
  | 'pie'
  | 'scatter'
  | 'area'
  | 'histogram'
  | 'heatmap'
  | 'boxplot'
  | 'grouped_bar'
  | 'donut';


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
  /**
   * The chart this message was about, when the user attached one. Kept on the
   * message so the transcript still says which chart was being edited after the
   * attachment itself is consumed and cleared.
   */
  referencedTitle?: string;
  /** Grounded answers offered with a question; picking one replies with its label. */
  options?: ChatOption[];
  timestamp: number;
}

/**
 * User overrides layered on top of the theme the backend bakes into every spec.
 *
 * Cumulative state, not a one-shot patch: an edit merges into this block and the
 * whole block is re-applied to the spec, which is what keeps repeated edits from
 * compounding. `null` on a field means "revert this to the theme"; absent means
 * "leave it as it is".
 *
 * Snake-cased because this is a wire type: it is sent to `POST /charts/style`
 * and stored verbatim in the saved chart's `chart_spec`, so it must stay
 * field-for-field identical to backend `schema/chart_style.ChartStyle`.
 */
export interface ChartStyle {
  title?: string | null;
  x_title?: string | null;
  y_title?: string | null;
  legend?: boolean | null;
  mark_color?: string | null;
  series_colors?: Record<string, string> | null;
  color_scheme?: string[] | null;
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
  /**
   * The agent's own identity for this chart, carried so a refinement ("make it a
   * line chart") lands on the card it refined instead of appending a second one.
   */
  agentChartId?: string;
  /** Agent / inferred chart type used by the canvas Filter panel. */
  chartType?: string;
  style?: ChartStyle;
  /**
   * Bumped on every in-place change to `vegaLiteSpec` — a style edit or a
   * refinement swapping the spec. This is what `persistSignature` watches:
   * hashing the spec itself is not an option, since it carries every result row
   * and the signature is recomputed on every pointer frame of a drag.
   */
  specVersion?: number;
  /** The version the server holds. An outcome of saving, like `backendChartId`. */
  syncedSpecVersion?: number;
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
