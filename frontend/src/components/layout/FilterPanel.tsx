import { Filter, X } from 'lucide-react';
import type { ChartType } from '../../types/dashboard';
import { FILTERABLE_CHART_TYPES } from '../../lib/chartType';
import './ToolSidePanel.css';

interface FilterPanelProps {
  open: boolean;
  selectedTypes: ChartType[];
  onClose: () => void;
  onChange: (types: ChartType[]) => void;
  chartCounts: Partial<Record<ChartType | 'other', number>>;
}

export function FilterPanel({
  open,
  selectedTypes,
  onClose,
  onChange,
  chartCounts,
}: FilterPanelProps) {
  if (!open) return null;

  const toggle = (type: ChartType) => {
    if (selectedTypes.includes(type)) {
      onChange(selectedTypes.filter((t) => t !== type));
    } else {
      onChange([...selectedTypes, type]);
    }
  };

  return (
    <section className="tool-panel" aria-label="Filter charts">
      <header className="tool-panel-header">
        <div className="tool-panel-header-title">
          <Filter size={16} />
          <span>Filter</span>
        </div>
        <button type="button" className="tool-panel-close" onClick={onClose} aria-label="Close filter panel">
          <X size={16} />
        </button>
      </header>

      <div className="tool-panel-body">
        <p className="tool-panel-copy">
          Show only matching chart types on the canvas. Leave all unchecked to show every chart.
        </p>

        <div className="tool-panel-section">
          <h3>Chart types</h3>
          <div className="tool-filter-types">
            {FILTERABLE_CHART_TYPES.map((opt) => {
              const count = chartCounts[opt.id] ?? 0;
              const checked = selectedTypes.includes(opt.id);
              return (
                <label key={opt.id} className={`tool-filter-type ${checked ? 'is-active' : ''}`}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(opt.id)}
                  />
                  <span>{opt.label}</span>
                  <em>{count}</em>
                </label>
              );
            })}
          </div>
          {selectedTypes.length > 0 && (
            <button
              type="button"
              className="tool-action-btn"
              onClick={() => onChange([])}
              style={{ marginTop: 10 }}
            >
              <span>
                Clear filters
                <span className="tool-action-meta">Show all charts on the canvas</span>
              </span>
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
