import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getSharedDashboard, type SharedDashboardResult } from '../lib/dashboards';
import { DashboardCanvas } from '../components/canvas/DashboardCanvas';
import type { ChartWidget } from '../types/dashboard';
import './SharedBoardPage.css';

export function SharedBoardPage() {
  const { dashboardId } = useParams();
  const [dashboard, setDashboard] = useState<SharedDashboardResult | null>(null);
  const [widgets, setWidgets] = useState<ChartWidget[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!dashboardId) return;

    let mounted = true;
    getSharedDashboard(dashboardId)
      .then((data) => {
        if (!mounted) return;
        setDashboard(data);
        
        const loadedWidgets: ChartWidget[] = data.widgets.map((w) => {
          const chartData = data.charts[w.chart_id];
          const chartType = typeof chartData?.spec?.type === 'string' ? chartData.spec.type : undefined;
          return {
            id: `chart-${w.id}`,
            title: chartData?.name || 'Unknown Chart',
            explanation: '',
            vegaLiteSpec: (chartData?.spec as Record<string, unknown>) || {},
            x: w.x,
            y: w.y,
            width: w.w,
            height: w.h,
            backendChartId: w.chart_id,
            chartType,
            style: undefined,
            specVersion: 0,
            syncedSpecVersion: 0,
          };
        });
        setWidgets(loadedWidgets);
      })
      .catch((err) => {
        if (mounted) {
          setError(err.message || 'Dashboard not found or not public');
        }
      });
      
    return () => { mounted = false; };
  }, [dashboardId]);

  if (error) {
    return (
      <div className="shared-board-error">
        <h2>Cannot Load Dashboard</h2>
        <p>{error}</p>
      </div>
    );
  }

  if (!dashboard) {
    return <div className="shared-board-loading">Loading...</div>;
  }

  return (
    <div className="shared-board-page">
      <header className="shared-board-header">
        <h1>{dashboard.name}</h1>
        <div className="shared-board-badge">AutoViz AI</div>
      </header>
      <div className="shared-board-content">
        <DashboardCanvas
          widgets={widgets}
          selectedWidgetId={null}
          dataset={null}
          uploading={false}
          uploadError={null}
          onSelect={() => {}}
          onUpdate={() => {}}
          onEditStyle={async () => null}
          onOpenStyle={() => {}}
          onReference={() => {}}
          referencedWidgetId={null}
          onDelete={() => {}}
          onCsvSelected={() => {}}
          readOnly={true}
        />
      </div>
    </div>
  );
}
