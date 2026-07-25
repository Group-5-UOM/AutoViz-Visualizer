import type { ChartWidget } from '../types/dashboard';

const sampleSales = [
  { category: 'Electronics', sales: 4200 },
  { category: 'Clothing', sales: 3100 },
  { category: 'Home', sales: 2800 },
  { category: 'Sports', sales: 1950 },
  { category: 'Books', sales: 1420 },
];

const sampleTrend = [
  { month: 'Jan', revenue: 12 },
  { month: 'Feb', revenue: 15 },
  { month: 'Mar', revenue: 14 },
  { month: 'Apr', revenue: 18 },
  { month: 'May', revenue: 22 },
  { month: 'Jun', revenue: 25 },
];

const sampleScatter = [
  { advertising: 10, sales: 22 },
  { advertising: 15, sales: 28 },
  { advertising: 20, sales: 35 },
  { advertising: 25, sales: 40 },
  { advertising: 30, sales: 48 },
  { advertising: 35, sales: 52 },
];

function baseConfig() {
  return {
    $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
    background: 'transparent',
    config: {
      view: { stroke: null },
      axis: {
        labelColor: '#60636c',
        titleColor: '#1c1f26',
        gridColor: '#e6e9ee',
        domainColor: '#d9dde3',
        tickColor: '#d9dde3',
        labelFont: 'DM Sans',
        titleFont: 'DM Sans',
      },
      legend: {
        labelColor: '#60636c',
        titleColor: '#1c1f26',
        labelFont: 'DM Sans',
        titleFont: 'DM Sans',
      },
    },
  };
}

export function createMockChartFromPrompt(
  prompt: string,
  existingCount: number,
): Omit<ChartWidget, 'id'> {
  const lower = prompt.toLowerCase();
  const col = existingCount % 2;
  const row = Math.floor(existingCount / 2);
  const x = 24 + col * 420;
  const y = 24 + row * 320;

  if (lower.includes('line') || lower.includes('trend') || lower.includes('over time')) {
    return {
      title: 'Revenue trend over time',
      explanation:
        'Line chart showing monthly revenue. Generated from your request about trends over time.',
      x,
      y,
      width: 400,
      height: 280,
      vegaLiteSpec: {
        ...baseConfig(),
        width: 'container',
        height: 200,
        data: { values: sampleTrend },
        mark: { type: 'line', point: true, strokeWidth: 2.5, color: '#2563eb' },
        encoding: {
          x: { field: 'month', type: 'ordinal', title: 'Month', sort: null },
          y: { field: 'revenue', type: 'quantitative', title: 'Revenue ($k)' },
          tooltip: [
            { field: 'month', type: 'ordinal' },
            { field: 'revenue', type: 'quantitative' },
          ],
        },
      },
    };
  }

  if (lower.includes('scatter') || lower.includes('correlation') || lower.includes('relationship')) {
    return {
      title: 'Advertising vs sales',
      explanation:
        'Scatter plot exploring the relationship between advertising spend and sales.',
      x,
      y,
      width: 400,
      height: 280,
      vegaLiteSpec: {
        ...baseConfig(),
        width: 'container',
        height: 200,
        data: { values: sampleScatter },
        mark: { type: 'point', filled: true, size: 80, color: '#0f7b4b' },
        encoding: {
          x: { field: 'advertising', type: 'quantitative', title: 'Advertising ($k)' },
          y: { field: 'sales', type: 'quantitative', title: 'Sales ($k)' },
          tooltip: [
            { field: 'advertising', type: 'quantitative' },
            { field: 'sales', type: 'quantitative' },
          ],
        },
      },
    };
  }

  if (lower.includes('pie') || lower.includes('share') || lower.includes('proportion')) {
    return {
      title: 'Sales share by category',
      explanation: 'Pie chart showing how sales are distributed across product categories.',
      x,
      y,
      width: 400,
      height: 280,
      vegaLiteSpec: {
        ...baseConfig(),
        width: 'container',
        height: 200,
        data: { values: sampleSales },
        mark: { type: 'arc', innerRadius: 40 },
        encoding: {
          theta: { field: 'sales', type: 'quantitative' },
          color: {
            field: 'category',
            type: 'nominal',
            scale: {
              range: ['#2563eb', '#0f7b4b', '#d97706', '#7c3aed', '#0891b2'],
            },
            legend: { title: 'Category' },
          },
          tooltip: [
            { field: 'category', type: 'nominal' },
            { field: 'sales', type: 'quantitative' },
          ],
        },
      },
    };
  }

  if (lower.includes('area')) {
    return {
      title: 'Cumulative revenue area',
      explanation: 'Area chart highlighting revenue growth across months.',
      x,
      y,
      width: 400,
      height: 280,
      vegaLiteSpec: {
        ...baseConfig(),
        width: 'container',
        height: 200,
        data: { values: sampleTrend },
        mark: { type: 'area', line: true, color: '#2563eb', opacity: 0.35 },
        encoding: {
          x: { field: 'month', type: 'ordinal', title: 'Month', sort: null },
          y: { field: 'revenue', type: 'quantitative', title: 'Revenue ($k)' },
          tooltip: [
            { field: 'month', type: 'ordinal' },
            { field: 'revenue', type: 'quantitative' },
          ],
        },
      },
    };
  }

  return {
    title: 'Sales by category',
    explanation:
      'Bar chart comparing sales across categories. Ask about trends, pie share, or correlations for other chart types.',
    x,
    y,
    width: 400,
    height: 280,
    vegaLiteSpec: {
      ...baseConfig(),
      width: 'container',
      height: 200,
      data: { values: sampleSales },
      mark: { type: 'bar', cornerRadiusEnd: 4, color: '#2563eb' },
      encoding: {
        x: { field: 'category', type: 'nominal', title: 'Category' },
        y: { field: 'sales', type: 'quantitative', title: 'Sales' },
        tooltip: [
          { field: 'category', type: 'nominal' },
          { field: 'sales', type: 'quantitative' },
        ],
      },
    },
  };
}

export function assistantReplyForChart(title: string): string {
  return `I've added “${title}” to your dashboard canvas. You can select the chart to move or resize it.`;
}
