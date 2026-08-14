// Extension spelled out so Node can resolve this module too — the tests import
// the helpers below directly, and Node's ESM loader does not guess extensions
// the way the bundler does.
import { canvasToPdf, PDF_RASTER_SCALE } from './pdf.ts';

export type ExportFormat = 'png' | 'pdf';

/**
 * The canvas backdrop, baked into the export.
 *
 * html2canvas renders a transparent background as transparent, and a PNG whose
 * background is transparent looks black in most PDF viewers and in some image
 * previewers. Pinned to the same grey as `--bg-app`.
 */
export const CANVAS_BACKGROUND = '#f4f5f7';
const CANVAS_BACKGROUND_RGB: [number, number, number] = [0xf4, 0xf5, 0xf7];

/**
 * A file name that every operating system will accept.
 *
 * Dashboards are named by the user and datasets carry their original file name,
 * so both routinely contain characters Windows rejects outright
 * (`: * ? " < > |`) and separators that would otherwise read as a path.
 *
 * Stated as what is allowed rather than what is forbidden — letters in any
 * script, digits, and a short list of punctuation — because a blacklist of
 * unsafe characters is a list you find out was incomplete from a bug report.
 * Everything else, control characters included, becomes a hyphen.
 *
 * Spaces are kept. They are legal everywhere the file might land, and
 * "Quarterly revenue.pdf" is a better thing to find in a downloads folder than
 * "Quarterly-revenue.pdf".
 */
export function exportFileName(base: string, extension: ExportFormat): string {
  const cleaned = base
    .replace(/\.[A-Za-z0-9]{1,5}$/, '') // drop a source extension like ".csv"
    .replace(/[^\p{L}\p{N} .()_-]+/gu, '-')
    .replace(/\s+/g, ' ')
    .replace(/-{2,}/g, '-')
    .trim()
    .replace(/^[-.]+|[-.]+$/g, '');
  const safe = cleaned.slice(0, 80) || 'dashboard';
  return `${safe}.${extension}`;
}

/** `canvas.toBlob`, promised. Preferred over `toDataURL` — a large dashboard
 *  produces a data URL big enough for browsers to refuse to navigate to. */
function canvasToPng(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error('The browser could not encode the dashboard image.'));
    }, 'image/png');
  });
}

/** Hand a blob to the browser as a download, then release the object URL. */
export function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoked on a later turn: revoking synchronously can beat the download the
  // click starts, which then fails with no error raised anywhere.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export interface ExportOptions {
  format: ExportFormat;
  /** Used for the file name and, for PDF, the document title. */
  name: string;
}

/**
 * Rasterise the dashboard element and save it in the requested format.
 *
 * Resolves to the file name written, so the caller can say which file it was
 * rather than "export complete" — a browser that saves downloads silently gives
 * the user no other way to find it.
 */
export async function exportDashboard(
  element: HTMLElement,
  { format, name }: ExportOptions,
): Promise<string> {
  // Loaded on demand. html2canvas is the single largest dependency in the app
  // and nothing before the first export needs it, so it stays out of the
  // initial bundle — and keeping it out of this module's import graph is what
  // lets the pure helpers above be tested under Node.
  const { default: html2canvas } = await import('html2canvas');

  const canvas = await html2canvas(element, {
    backgroundColor: CANVAS_BACKGROUND,
    // A PDF is zoomed and printed, so it is rendered above device resolution.
    // A PNG is looked at on a screen, where matching the device ratio is what
    // keeps it sharp without doubling the file for nothing.
    scale: format === 'pdf' ? PDF_RASTER_SCALE : window.devicePixelRatio || 1,
  });

  if (canvas.width === 0 || canvas.height === 0) {
    throw new Error('The canvas was empty when it was captured.');
  }

  const fileName = exportFileName(name, format);
  const blob =
    format === 'pdf'
      ? await canvasToPdf(canvas, { title: name, background: CANVAS_BACKGROUND_RGB })
      : await canvasToPng(canvas);

  downloadBlob(blob, fileName);
  return fileName;
}
