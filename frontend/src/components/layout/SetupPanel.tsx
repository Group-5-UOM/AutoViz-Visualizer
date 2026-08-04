import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  BarChart3,
  ChartPie,
  LineChart,
  ScatterChart,
  AreaChart,
  ChartColumn,
  Grid3x3,
  Box,
  Donut,
  Pencil,
  SendHorizontal,
  X,
} from 'lucide-react';
import type { ChartType, ChatMessage } from '../../types/dashboard';
import './ToolSidePanel.css';

const CHART_OPTIONS: {
  id: ChartType;
  label: string;
  description: string;
  icon: typeof BarChart3;
}[] = [
  { id: 'bar', label: 'Bar', description: 'Compare categories', icon: BarChart3 },
  { id: 'grouped_bar', label: 'Grouped bar', description: 'Compare series side by side', icon: ChartColumn },
  { id: 'line', label: 'Line', description: 'Show trends over time', icon: LineChart },
  { id: 'area', label: 'Area', description: 'Trends with filled volume', icon: AreaChart },
  { id: 'scatter', label: 'Scatter', description: 'Relationships between numbers', icon: ScatterChart },
  { id: 'pie', label: 'Pie', description: 'Parts of a whole', icon: ChartPie },
  { id: 'donut', label: 'Donut', description: 'Composition with a center hole', icon: Donut },
  { id: 'histogram', label: 'Histogram', description: 'Distribution of one number', icon: BarChart3 },
  { id: 'heatmap', label: 'Heatmap', description: 'Intensity across two axes', icon: Grid3x3 },
  { id: 'boxplot', label: 'Box plot', description: 'Spread and outliers', icon: Box },
];

interface SetupPanelProps {
  open: boolean;
  hasDataset: boolean;
  datasetName?: string | null;
  isThinking: boolean;
  messages: ChatMessage[];
  onClose: () => void;
  onAsk: (chartType: ChartType, question: string) => void;
}

export function SetupPanel({
  open,
  hasDataset,
  datasetName,
  isThinking,
  messages,
  onClose,
  onAsk,
}: SetupPanelProps) {
  const [selected, setSelected] = useState<ChartType>('bar');
  const [draft, setDraft] = useState('');
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = listRef.current;
    if (!el || !open) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, isThinking, open]);

  if (!open) return null;

  const selectedMeta = CHART_OPTIONS.find((c) => c.id === selected) ?? CHART_OPTIONS[0];
  const canAsk = hasDataset && Boolean(draft.trim()) && !isThinking;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const question = draft.trim();
    if (!canAsk || !question) return;
    onAsk(selected, question);
    setDraft('');
  };

  return (
    <section className="tool-panel tool-panel--setup" aria-label="Chart setup">
      <header className="tool-panel-header">
        <div className="tool-panel-header-title">
          <Pencil size={16} />
          <span>Setup</span>
        </div>
        <button type="button" className="tool-panel-close" onClick={onClose} aria-label="Close setup panel">
          <X size={16} />
        </button>
      </header>

      <div className="tool-panel-body tool-panel-body--setup">
        <p className="tool-panel-copy">
          Choose a chart type, then ask what to plot. The bot will generate that chart on the canvas.
        </p>

        {!hasDataset ? (
          <div className="tool-empty">Upload a CSV with Add before generating charts.</div>
        ) : (
          <>
            {datasetName && (
              <p className="tool-panel-copy">
                Dataset: <strong style={{ color: 'var(--text-primary)' }}>{datasetName}</strong>
              </p>
            )}

            <div className="tool-panel-section">
              <h3>Chart type</h3>
              <div className="tool-chart-grid" role="listbox" aria-label="Chart types">
                {CHART_OPTIONS.map(({ id, label, description, icon: Icon }) => {
                  const active = selected === id;
                  return (
                    <button
                      key={id}
                      type="button"
                      role="option"
                      aria-selected={active}
                      className={`tool-chart-option ${active ? 'is-active' : ''}`}
                      onClick={() => setSelected(id)}
                      title={description}
                    >
                      <Icon size={16} />
                      <span>{label}</span>
                    </button>
                  );
                })}
              </div>
              <p className="tool-panel-copy">
                Selected: <strong style={{ color: 'var(--text-primary)' }}>{selectedMeta.label}</strong>
                {' — '}
                {selectedMeta.description}
              </p>
            </div>

            <div className="tool-panel-section tool-setup-chat">
              <h3>Ask the bot</h3>
              <div className="tool-setup-messages" ref={listRef}>
                {messages.length === 0 && !isThinking && (
                  <div className="tool-empty">
                    Example: “average fare by passenger class” or “sales over time”
                  </div>
                )}
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`tool-setup-bubble tool-setup-bubble--${msg.role}`}
                  >
                    {msg.content}
                  </div>
                ))}
                {isThinking && (
                  <div className="tool-setup-bubble tool-setup-bubble--assistant">
                    Drawing your {selectedMeta.label.toLowerCase()} chart…
                  </div>
                )}
              </div>

              <form className="tool-setup-compose" onSubmit={handleSubmit}>
                <input
                  type="text"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  placeholder={`Ask for a ${selectedMeta.label.toLowerCase()} chart…`}
                  disabled={!hasDataset || isThinking}
                  aria-label="Question for chart"
                />
                <button type="submit" disabled={!canAsk} aria-label="Generate chart">
                  <SendHorizontal size={16} />
                </button>
              </form>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

export function buildChartPrompt(chartType: ChartType, question: string): string {
  const label = CHART_OPTIONS.find((c) => c.id === chartType)?.label ?? chartType;
  return (
    `Create a ${label} chart (chart type must be "${chartType}") that answers this: ${question}. ` +
    `Prefer this chart type unless the data cannot support it.`
  );
}
