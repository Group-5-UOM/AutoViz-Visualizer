/**
 * Byte-level tests for the hand-written PDF writer.
 *
 * The reason these exist rather than a snapshot: the cross-reference table is a
 * list of absolute byte offsets, so *any* change to an earlier object silently
 * invalidates every offset after it. That failure does not throw and does not
 * look wrong in a hex dump — it produces a file some readers open and others
 * reject. So the offsets are re-derived here and checked against what they
 * claim to point at.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { inflateSync } from 'node:zlib';

import {
  buildImagePdf,
  deflate,
  rgbFromRgba,
  type PdfImage,
} from '../src/lib/pdf.ts';

const FIXED_DATE = new Date(Date.UTC(2026, 7, 15, 9, 30, 0));

function image(width: number, height: number, byteLength = 32): PdfImage {
  return {
    width,
    height,
    data: new Uint8Array(byteLength).fill(0x42),
    filter: 'FlateDecode',
  };
}

/** PDF is latin-1 at the syntax level; the streams inside are opaque bytes. */
function text(pdf: Uint8Array): string {
  return Buffer.from(pdf).toString('latin1');
}

interface Xref {
  offsets: number[];
  startxref: number;
  size: number;
}

function parseXref(pdf: Uint8Array): Xref {
  const body = text(pdf);
  const marker = body.lastIndexOf('startxref');
  assert.notEqual(marker, -1, 'no startxref');
  const startxref = Number.parseInt(body.slice(marker + 'startxref'.length).trim(), 10);

  const table = body.slice(startxref);
  const header = /^xref\n0 (\d+)\n/.exec(table);
  assert.ok(header, 'xref table does not start with a subsection header');
  const size = Number.parseInt(header[1], 10);

  // Entries are fixed-width by specification: exactly 20 bytes each.
  const first = startxref + header[0].length;
  const offsets: number[] = [];
  for (let i = 0; i < size; i += 1) {
    const entry = body.slice(first + i * 20, first + (i + 1) * 20);
    assert.equal(entry.length, 20, `entry ${i} is not 20 bytes`);
    assert.match(entry, /^\d{10} \d{5} [nf] \n$/, `entry ${i} is malformed: ${JSON.stringify(entry)}`);
    offsets.push(Number.parseInt(entry.slice(0, 10), 10));
  }
  return { offsets, startxref, size };
}

test('writes a PDF header and terminator', () => {
  const pdf = buildImagePdf(image(800, 500), { now: FIXED_DATE });
  assert.equal(text(pdf).slice(0, 9), '%PDF-1.4\n');
  // The binary comment on line 2 stops transfer tools from mangling the file:
  // '%' followed by four bytes above 127.
  assert.equal(pdf[9], 0x25, 'line 2 should be a comment');
  assert.ok(
    [10, 11, 12, 13].every((i) => pdf[i] > 127),
    'binary marker comment must contain bytes above 127',
  );
  assert.ok(text(pdf).endsWith('%%EOF\n'));
});

test('every xref offset points at the object that claims it', () => {
  const pdf = buildImagePdf(image(800, 500), { now: FIXED_DATE });
  const body = text(pdf);
  const { offsets, size, startxref } = parseXref(pdf);

  assert.equal(size, 7, 'expected 6 objects plus the free entry');
  assert.equal(offsets[0], 0, 'entry 0 must be the free-list head');

  for (let id = 1; id < size; id += 1) {
    const at = body.slice(offsets[id], offsets[id] + 16);
    assert.ok(
      at.startsWith(`${id} 0 obj\n`),
      `xref says object ${id} is at ${offsets[id]}, but that is ${JSON.stringify(at)}`,
    );
  }

  assert.ok(body.slice(startxref).startsWith('xref\n'), 'startxref does not point at the table');
  assert.match(body, /\/Size 7 \/Root 1 0 R \/Info 6 0 R \/ID \[<[0-9a-f]{32}> <[0-9a-f]{32}>\]/);
});

test('stream lengths match the bytes actually written', () => {
  const data = new Uint8Array(1234).fill(7);
  const pdf = buildImagePdf({ width: 100, height: 80, data, filter: 'FlateDecode' }, { now: FIXED_DATE });
  const body = text(pdf);

  const declared = /\/Filter \/FlateDecode \/Length (\d+) >>\nstream\n/.exec(body);
  assert.ok(declared, 'image stream dictionary not found');
  assert.equal(Number.parseInt(declared[1], 10), data.length);

  // And the declared length really does land on `endstream`.
  const streamStart = declared.index + declared[0].length;
  assert.equal(body.slice(streamStart + data.length, streamStart + data.length + 11), '\nendstream\n');

  const content = /<< \/Length (\d+) >>\nstream\n/.exec(body);
  assert.ok(content);
  const contentStart = content.index + content[0].length;
  const contentEnd = contentStart + Number.parseInt(content[1], 10);
  assert.equal(body.slice(contentEnd, contentEnd + 10), 'endstream\n');
});

test('page orientation follows the image, and the image is centred inside the margins', () => {
  const wide = text(buildImagePdf(image(1600, 900), { now: FIXED_DATE }));
  const tall = text(buildImagePdf(image(900, 1600), { now: FIXED_DATE }));

  assert.match(wide, /\/MediaBox \[0 0 841\.89 595\.28\]/, 'a wide dashboard should get a landscape page');
  assert.match(tall, /\/MediaBox \[0 0 595\.28 841\.89\]/, 'a tall dashboard should get a portrait page');

  const placement = /q\n([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm\n\/Im0 Do\nQ/.exec(wide);
  assert.ok(placement, 'content stream does not place the image');
  const [w, h, x, y] = placement.slice(1, 5).map(Number);

  const margin = 24;
  assert.ok(w <= 841.89 - margin * 2 + 0.01, `image is wider than the margins allow: ${w}`);
  assert.ok(h <= 595.28 - margin * 2 + 0.01, `image is taller than the margins allow: ${h}`);
  // Centred: equal space left and right, top and bottom.
  assert.ok(Math.abs(x - (841.89 - w) / 2) < 0.01, 'not horizontally centred');
  assert.ok(Math.abs(y - (595.28 - h) / 2) < 0.01, 'not vertically centred');
  // Aspect ratio preserved — a stretched dashboard misreports every bar length.
  assert.ok(Math.abs(w / h - 1600 / 900) < 0.001, 'aspect ratio was not preserved');
});

test('a small image is scaled up to fill the page rather than left as a stamp', () => {
  const body = text(buildImagePdf(image(200, 120), { now: FIXED_DATE }));
  const placement = /q\n([\d.]+) 0 0 ([\d.]+) /.exec(body);
  assert.ok(placement);
  assert.ok(Number(placement[1]) > 700, `expected the image to fill the page, got ${placement[1]}pt wide`);
});

test('title is escaped, and unencodable characters are dropped rather than corrupting the string', () => {
  const body = text(
    buildImagePdf(image(800, 500), {
      now: FIXED_DATE,
      title: 'sales (2026) \\ Q3 — café',
    }),
  );
  assert.match(body, /\/Title \(sales \\\(2026\\\) \\\\ Q3  caf\)/);
  // Whatever happens to the title, the dictionary must still close.
  assert.match(body, /\/CreationDate \(D:20260815093000Z\) >>/);
});

test('output is deterministic for identical input', () => {
  const a = buildImagePdf(image(800, 500), { now: FIXED_DATE, title: 'same' });
  const b = buildImagePdf(image(800, 500), { now: FIXED_DATE, title: 'same' });
  assert.deepEqual(Buffer.from(a), Buffer.from(b));

  const c = buildImagePdf(image(800, 501), { now: FIXED_DATE, title: 'same' });
  assert.notDeepEqual(Buffer.from(a), Buffer.from(c), '/ID should distinguish different documents');
});

test('rgbFromRgba drops the alpha channel and composites translucency onto the background', () => {
  const rgba = new Uint8ClampedArray([
    10, 20, 30, 255, // opaque: passes through untouched
    0, 0, 0, 0, // fully transparent: becomes the background, not black
    0, 0, 0, 128, // half transparent black over white: mid grey
  ]);
  const rgb = rgbFromRgba(rgba, [255, 255, 255]);
  assert.equal(rgb.length, 9);
  assert.deepEqual([...rgb.slice(0, 3)], [10, 20, 30]);
  assert.deepEqual([...rgb.slice(3, 6)], [255, 255, 255]);
  assert.deepEqual([...rgb.slice(6, 9)], [127, 127, 127]);
});

test('the deflated image stream inflates back to the exact pixels', async () => {
  const width = 64;
  const height = 48;
  const rgba = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < rgba.length; i += 4) {
    rgba[i] = i % 251;
    rgba[i + 1] = (i * 7) % 253;
    rgba[i + 2] = (i * 13) % 249;
    rgba[i + 3] = 255;
  }

  const rgb = rgbFromRgba(rgba);
  const compressed = await deflate(rgb);
  // zlib-wrapped, which is what /FlateDecode reads — a raw deflate stream here
  // would produce a file that only some readers accept.
  assert.equal(compressed[0] & 0x0f, 8, 'not a zlib stream (CM should be 8)');

  const inflated = new Uint8Array(inflateSync(Buffer.from(compressed)));
  assert.equal(inflated.length, width * height * 3);
  assert.deepEqual(Buffer.from(inflated), Buffer.from(rgb));
});
