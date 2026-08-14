/**
 * A single-page PDF containing one raster image, written by hand.
 *
 * The dashboard is exported by rasterising the canvas (html2canvas) and wrapping
 * the result in a PDF page. Wrapping a bitmap is the whole job, so this is a
 * few hundred bytes of PDF structure around an image stream rather than a reason
 * to take on jsPDF — which ships its own deflate implementation to do what
 * `CompressionStream` now does natively.
 *
 * Two encodings, in preference order:
 *
 *   - **FlateDecode** — the canvas pixels as raw RGB, zlib-deflated. Lossless,
 *     which matters because a dashboard is mostly text and thin axis rules, and
 *     those are exactly what a lossy codec smears.
 *   - **DCTDecode** — a JPEG, used only when the lossless path is unavailable
 *     (no `CompressionStream`) or refuses (`getImageData` throwing on a canvas
 *     too large to buffer). Charts survive it at high quality; the fallback
 *     exists so export never simply fails.
 *
 * `buildImagePdf` is pure — bytes in, bytes out — so the byte-level structure is
 * tested in Node without a browser. Everything that touches a `<canvas>` sits
 * below it in this file.
 */

/** A4 in points, short edge first. PDF user space is 1/72". */
const A4_SHORT = 595.28;
const A4_LONG = 841.89;

/** Fallback JPEG quality, only reached when the lossless path cannot run. */
const JPEG_QUALITY = 0.94;

/**
 * Rasterise at 2× so chart text stays sharp when the page is zoomed or printed.
 * Above this the deflate cost grows faster than the page visibly improves.
 */
export const PDF_RASTER_SCALE = 2;

export type PdfImageFilter = 'FlateDecode' | 'DCTDecode';

/** An image already encoded into the form a PDF image stream expects. */
export interface PdfImage {
  /** Pixel dimensions — the image's own grid, not the page it lands on. */
  width: number;
  height: number;
  /** Stream bytes, encoded to match `filter`. */
  data: Uint8Array;
  filter: PdfImageFilter;
}

export interface PdfPageOptions {
  /** Written to the document's `/Title`, which is what a viewer shows in its tab. */
  title?: string;
  /** Page box in points. Defaults to A4 in the image's own orientation. */
  page?: { width: number; height: number };
  /** White space kept around the image, in points. */
  margin?: number;
  /** Injectable so the byte output of a test is deterministic. */
  now?: Date;
}

// --- byte-level PDF ---------------------------------------------------------

function ascii(text: string): Uint8Array {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i += 1) out[i] = text.charCodeAt(i) & 0xff;
  return out;
}

/**
 * A string safe to drop between the parentheses of a PDF literal string.
 *
 * Non-ASCII is dropped rather than encoded: the alternative is UTF-16BE with a
 * byte-order mark, and the only string this document carries is a title taken
 * from a file name.
 */
function pdfString(value: string): string {
  let out = '';
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0;
    if (code < 32 || code > 126) continue;
    if (ch === '(' || ch === ')' || ch === '\\') out += `\\${ch}`;
    else out += ch;
  }
  return out;
}

/** `D:YYYYMMDDHHmmSSZ` — the PDF date form, always written in UTC. */
function pdfDate(when: Date): string {
  const p = (n: number, width = 2) => String(n).padStart(width, '0');
  return (
    `D:${when.getUTCFullYear()}${p(when.getUTCMonth() + 1)}${p(when.getUTCDate())}` +
    `${p(when.getUTCHours())}${p(when.getUTCMinutes())}${p(when.getUTCSeconds())}Z`
  );
}

/** Two decimals is finer than a PDF point is worth, and keeps the file terse. */
function num(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

/**
 * The trailer's `/ID` — a 32-hex-digit file identifier.
 *
 * Optional by the letter of the spec and expected in practice: some readers
 * treat a trailer without one as damaged, and at least one reports the file as
 * encrypted rather than as malformed, which is a confusing way to find out.
 *
 * The spec suggests deriving it from the time, size and contents, which is what
 * this does — so it stays a pure function of its inputs and a test can pin the
 * exact bytes of a document.
 */
function fileId(seed: string): string {
  // Four FNV-1a passes over the seed, each salted differently, for 32 hex
  // digits. Not a cryptographic identity and not required to be one: this is a
  // label distinguishing two revisions of a file.
  let out = '';
  for (let salt = 0; salt < 4; salt += 1) {
    let hash = 0x811c9dc5 ^ (salt * 0x01000193);
    for (let i = 0; i < seed.length; i += 1) {
      hash ^= seed.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    out += hash.toString(16).padStart(8, '0');
  }
  return out;
}

/**
 * Where the image sits on the page: scaled to fit inside the margins, centred,
 * and never enlarged past... nothing, in fact — a small chart is scaled up to
 * fill the page, because a dashboard exported to a stamp in the corner of an A4
 * is not what anyone meant by "export as PDF".
 */
function fitImage(
  image: { width: number; height: number },
  page: { width: number; height: number },
  margin: number,
) {
  const availableWidth = Math.max(1, page.width - margin * 2);
  const availableHeight = Math.max(1, page.height - margin * 2);
  const scale = Math.min(availableWidth / image.width, availableHeight / image.height);
  const width = image.width * scale;
  const height = image.height * scale;
  return {
    width,
    height,
    x: (page.width - width) / 2,
    y: (page.height - height) / 2,
  };
}

/** A4 turned to match the image, so a wide dashboard gets a wide page. */
function defaultPage(image: { width: number; height: number }) {
  return image.width >= image.height
    ? { width: A4_LONG, height: A4_SHORT }
    : { width: A4_SHORT, height: A4_LONG };
}

/**
 * Assemble a one-page PDF around `image`.
 *
 * Object numbering is fixed (1 catalog, 2 pages, 3 page, 4 contents, 5 image,
 * 6 info) because the document shape never varies. Offsets for the cross
 * reference table are collected as the body is written; every xref entry is
 * exactly 20 bytes, which the spec requires and readers do rely on.
 */
export function buildImagePdf(image: PdfImage, options: PdfPageOptions = {}): Uint8Array {
  const page = options.page ?? defaultPage(image);
  const margin = options.margin ?? 24;
  const placed = fitImage(image, page, margin);
  const created = options.now ?? new Date();
  const title = pdfString(options.title ?? 'AutoViz dashboard');

  const chunks: Uint8Array[] = [];
  let cursor = 0;
  const write = (part: Uint8Array | string) => {
    const bytes = typeof part === 'string' ? ascii(part) : part;
    chunks.push(bytes);
    cursor += bytes.length;
  };

  const offsets = new Map<number, number>();
  const open = (id: number) => {
    offsets.set(id, cursor);
    write(`${id} 0 obj\n`);
  };
  const close = () => write('endobj\n');

  // The binary comment on line 2 is what tells a transfer agent this is not a
  // text file; without it a naive FTP-style tool may translate line endings and
  // corrupt the image stream.
  write('%PDF-1.4\n');
  write(new Uint8Array([0x25, 0xe2, 0xe3, 0xcf, 0xd3, 0x0a]));

  open(1);
  write('<< /Type /Catalog /Pages 2 0 R >>\n');
  close();

  open(2);
  write('<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n');
  close();

  open(3);
  write(
    '<< /Type /Page /Parent 2 0 R ' +
      `/MediaBox [0 0 ${num(page.width)} ${num(page.height)}] ` +
      '/Resources << /XObject << /Im0 5 0 R >> >> ' +
      '/Contents 4 0 R >>\n',
  );
  close();

  // `cm` maps the unit square the image is drawn into onto the page, so the
  // matrix is the placement: width, height, then the bottom-left corner.
  const content =
    `q\n${num(placed.width)} 0 0 ${num(placed.height)} ` +
    `${num(placed.x)} ${num(placed.y)} cm\n/Im0 Do\nQ\n`;
  open(4);
  write(`<< /Length ${content.length} >>\nstream\n${content}endstream\n`);
  close();

  open(5);
  write(
    '<< /Type /XObject /Subtype /Image ' +
      `/Width ${image.width} /Height ${image.height} ` +
      '/ColorSpace /DeviceRGB /BitsPerComponent 8 ' +
      `/Filter /${image.filter} /Length ${image.data.length} >>\nstream\n`,
  );
  write(image.data);
  write('\nendstream\n');
  close();

  open(6);
  write(
    `<< /Title (${title}) ` +
      '/Producer (AutoViz AI) /Creator (AutoViz AI) ' +
      `/CreationDate (${pdfDate(created)}) >>\n`,
  );
  close();

  const xrefOffset = cursor;
  const objectCount = 6;
  write(`xref\n0 ${objectCount + 1}\n`);
  write('0000000000 65535 f \n');
  for (let id = 1; id <= objectCount; id += 1) {
    write(`${String(offsets.get(id) ?? 0).padStart(10, '0')} 00000 n \n`);
  }
  const id = fileId(`${title}|${pdfDate(created)}|${image.width}x${image.height}|${image.data.length}`);
  write(
    `trailer\n<< /Size ${objectCount + 1} /Root 1 0 R /Info 6 0 R ` +
      `/ID [<${id}> <${id}>] >>\n` +
      `startxref\n${xrefOffset}\n%%EOF\n`,
  );

  const total = chunks.reduce((sum, part) => sum + part.length, 0);
  const pdf = new Uint8Array(total);
  let at = 0;
  for (const part of chunks) {
    pdf.set(part, at);
    at += part.length;
  }
  return pdf;
}

// --- image encoding ---------------------------------------------------------

/** True when the lossless path can run at all. */
export function canDeflate(): boolean {
  return typeof CompressionStream === 'function';
}

/** zlib-wrapped deflate, which is exactly what `/FlateDecode` reads. */
export async function deflate(bytes: Uint8Array): Promise<Uint8Array> {
  const compressed = new Blob([bytes as BlobPart])
    .stream()
    .pipeThrough(new CompressionStream('deflate'));
  return new Uint8Array(await new Response(compressed).arrayBuffer());
}

/**
 * RGBA pixels flattened to the RGB triples a `/DeviceRGB` image stream wants.
 *
 * Translucent pixels are composited onto `background` rather than having their
 * alpha discarded: dropping it outright turns anything the page let through
 * into black, which is how a transparent chart background becomes a black box.
 */
export function rgbFromRgba(
  rgba: Uint8ClampedArray | Uint8Array,
  background: [number, number, number] = [255, 255, 255],
): Uint8Array {
  const out = new Uint8Array((rgba.length / 4) * 3);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 3) {
    const alpha = rgba[i + 3];
    if (alpha === 255) {
      out[j] = rgba[i];
      out[j + 1] = rgba[i + 1];
      out[j + 2] = rgba[i + 2];
      continue;
    }
    const a = alpha / 255;
    out[j] = Math.round(rgba[i] * a + background[0] * (1 - a));
    out[j + 1] = Math.round(rgba[i + 1] * a + background[1] * (1 - a));
    out[j + 2] = Math.round(rgba[i + 2] * a + background[2] * (1 - a));
  }
  return out;
}

function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

/**
 * Encode a canvas for embedding, lossless where possible.
 *
 * Both failure modes of the lossless path are non-exceptional and both land on
 * JPEG: no `CompressionStream` in this browser, and `getImageData` throwing —
 * which it does on a tainted canvas, and can do on one large enough that the
 * RGBA buffer will not allocate.
 */
export async function encodeCanvasImage(
  canvas: HTMLCanvasElement,
  background: [number, number, number] = [255, 255, 255],
): Promise<PdfImage> {
  if (canDeflate()) {
    try {
      const context = canvas.getContext('2d');
      if (context) {
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
        return {
          width: canvas.width,
          height: canvas.height,
          data: await deflate(rgbFromRgba(pixels.data, background)),
          filter: 'FlateDecode',
        };
      }
    } catch (err) {
      console.warn('Lossless PDF encoding unavailable, falling back to JPEG:', err);
    }
  }

  const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY);
  const comma = dataUrl.indexOf(',');
  if (!dataUrl.startsWith('data:image/jpeg') || comma === -1) {
    throw new Error('This browser could not encode the dashboard image.');
  }
  return {
    width: canvas.width,
    height: canvas.height,
    data: base64ToBytes(dataUrl.slice(comma + 1)),
    filter: 'DCTDecode',
  };
}

export interface CanvasPdfOptions extends PdfPageOptions {
  /** Colour shown through any translucent pixel. Matches the canvas backdrop. */
  background?: [number, number, number];
}

/** Rasterised canvas → a one-page PDF, ready to download. */
export async function canvasToPdf(
  canvas: HTMLCanvasElement,
  options: CanvasPdfOptions = {},
): Promise<Blob> {
  const image = await encodeCanvasImage(canvas, options.background);
  const bytes = buildImagePdf(image, options);
  return new Blob([bytes as BlobPart], { type: 'application/pdf' });
}
