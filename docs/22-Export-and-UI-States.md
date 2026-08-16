# 22 — PDF Export and the FR-19 State Audit

**15 August 2026.** This closes the two milestone criteria that stood at 🟡 in
[`Docs/21`](21-Project-Status.md):

| # | Criterion | Was | Now |
|---|---|---|---|
| 7 | Image **and PDF** export work | 🟡 PNG only | ✅ Both, from one menu |
| 8 | Core error/loading states are complete | 🟡 Present, never audited | ✅ Audited against FR-19's six states, gaps closed |

FR-19 names the six exactly: *"UI exposes **loading**, **empty**, **success**,
**validation-error**, **recoverable-error**, and **retry** states."* Nobody had
ever checked the UI against that list. Doing so found four states in good shape,
one absent, and one that existed only as a red button.

---

## 1. PDF export

### What ships

The Export button is now a menu — **PNG image** or **PDF document**. The PDF is
one page, A4, turned landscape or portrait to match the dashboard, with the
canvas scaled to fit inside a 24 pt margin and centred.

### Why there is no new dependency

The obvious move was `jspdf`. It was not taken. Wrapping a bitmap in a PDF page
is a few hundred bytes of structure around an image stream, and jsPDF ships its
own deflate implementation to do what `CompressionStream` has done natively in
every target browser for years. It would have added ~400 kB to a bundle already
warning at 1.5 MB.

[`frontend/src/lib/pdf.ts`](../frontend/src/lib/pdf.ts) writes the file directly:

- **Lossless by default.** Canvas pixels → RGB triples → `CompressionStream('deflate')`
  → a `/FlateDecode` image stream. A dashboard is mostly text and thin axis
  rules, which is exactly what a lossy codec smears.
- **JPEG fallback** (`/DCTDecode`) when the lossless path cannot run — no
  `CompressionStream`, or `getImageData` throwing on a canvas too large to
  buffer. Export degrades rather than failing.
- **Rasterised at 2×**, because a PDF gets zoomed and printed. PNG stays at the
  device pixel ratio, where more resolution only costs file size.
- Translucent pixels are composited onto the canvas colour. Discarding alpha
  instead is how a transparent chart background becomes a black box.

`buildImagePdf` is pure — bytes in, bytes out — which is what makes the byte
layout testable under Node with no browser.

### Verification

The output was checked against an independent parser (`pypdf`), not just against
its own tests:

```
encrypted: False · pages: 1 · mediabox: [0, 0, 841.89, 595.28]
metadata:  {'/Title': 'AutoViz dashboard - verification', '/Producer': 'AutoViz AI', ...}
image:     /FlateDecode /DeviceRGB 8bpc 800x500
decoded:   1200000 bytes (expected 1200000)
```

Every sampled pixel round-tripped exactly, including a half-transparent black
stripe arriving as `(127, 127, 127)` over white rather than as black.

Nine tests in [`frontend/tests/pdf.test.ts`](../frontend/tests/pdf.test.ts) pin
the structure. The one that earns its place: **every cross-reference offset is
re-derived and checked against the object it claims to point at.** The xref
table is a list of absolute byte offsets, so any change to an earlier object
silently invalidates every offset after it — a failure that does not throw, does
not look wrong in a hex dump, and produces a file some readers open and others
reject.

Also pinned: 20-byte xref entries, stream `/Length` matching the bytes actually
written, orientation following the image, aspect ratio preserved (a stretched
dashboard misreports every bar length), title escaping, deterministic output,
and a deflate round-trip through `zlib.inflateSync`.

### One incidental win

`html2canvas` is now loaded on demand. Nothing before the first export needs it,
so it left the initial bundle: **1,553 kB → 1,353 kB**, with html2canvas in a
199 kB chunk that most sessions never fetch.

---

## 2. The FR-19 audit

### Where each state stands

| State | Where it lives now |
|---|---|
| **Loading** | Chat thinking-dots (`isThinking`) · upload (`uploading`) · chart restyle (`editBusy`, `styleBusy`) · save (`saveStatus === 'saving'`) · dataset and dashboard lists · preview panes · **export (new)** |
| **Empty** | Canvas with no dataset · canvas with a dataset and no charts · chat with only the welcome (suggestion chips) · no datasets · no saved dashboards · dashboard with no charts |
| **Success** | The answer in chat with "View on canvas" · `Saved` on the save button · **the export notice, naming the file written (new)** |
| **Validation-error** | **Typed and distinguished (new)** — blue chat bubble, no retry offered · upload rejection inline · restyle rejection inline |
| **Recoverable-error** | **Typed and distinguished (new)** — red chat bubble · notice stack for export, save, dashboard open and create · save button now reads `Retry save` and carries the reason |
| **Retry** | **New** — "Try again" on the last failed chat turn, in every notice, on both list panels, and on both preview panes · the save button re-arms autosave |

### What was actually wrong

**Validation and recoverable failures were indistinguishable.** The backend has
had a typed error taxonomy since July — `INVALID_PLAN`, `TYPE_MISMATCH`,
`TIMEOUT`, `EXECUTION_ERROR` and the rest, in the response body as `error_code`.
`ApiError` carried only `message` and `status`, so **the code was parsed and
thrown away**. The UI could not tell a question that cannot be answered from a
query that timed out, and offered the same nothing for both.

`ApiError` now carries `code`, and [`lib/errors.ts`](../frontend/src/lib/errors.ts)
classifies every failure as `validation`, `recoverable` or `fatal`. That single
decision drives whether a retry button appears — and getting it wrong is
expensive in both directions: a retry on a rejected request sends the user round
a loop that cannot succeed, and no retry on a dropped connection makes them
retype a question the server never saw.

**A rejected plan said "Request failed (422)".** Validation failures come back
as `{valid: false, errors: [...]}`, a shape `formatDetail` did not handle. The
most explanatory message the backend produces — the one naming the column or
aggregation it would not accept — never reached the user.

**`saveError` was computed and dropped.** `useDashboard` produced it, returned
it, and `BoardPage` never destructured it. The only sign of a failed save was
the button turning red and reading `Error`. Autosave deliberately stops retrying
after a failure, so a board could sit unsaved indefinitely with the reason known
only to the code that discarded it.

**A failed export looked exactly like a successful one.** `console.error`, no
UI. On a browser that saves downloads silently, there was no way to tell.

**Three `window.alert` calls and three silent `console.error` swallows.** Alerts
stop the page, name no cause, and vanish on dismissal. Two of them guessed:
*"Failed to delete dashboard. It might already be deleted."* The server knew;
nobody asked it.

**Two preview panes reported a failed fetch as an empty result** — "no charts",
"no rows". That is a claim about the data, made because a request failed.

**A dropped connection surfaced as `TypeError: Failed to fetch`.** Network
failures are now normalised into `ApiError` with status `0`, classified
recoverable.

### What was added

- [`hooks/useNotices.ts`](../frontend/src/hooks/useNotices.ts) — one channel for
  things the user needs told. Keyed, so a retry replaces the banner in place
  rather than stacking a second one. Success self-clears after four seconds;
  anything requiring action stays until dismissed. `notifyError` picks the state
  and the retry affordance from the error itself, not from the call site.
- [`components/layout/NoticeStack.tsx`](../frontend/src/components/layout/NoticeStack.tsx)
  — `role="status"` with `aria-live="polite"`, so a screen-reader user is told
  what happened without the sentence they are reading being interrupted.
  Failures never auto-dismiss, so none is announced and then gone.
- **Chat retry.** `sendMessage` was split, so a retry re-runs the exact request
  that failed — same attached chart, same chart-type pick — without posting the
  user's message twice. The failure bubble is dropped first, so a second failure
  does not leave two stacked. Offered only on the newest turn: an older failure
  has been superseded by whatever the user did next.

### Deliberate non-retries

A retry button is a promise. Three failures do not get one:

- **Validation errors.** The same words produce the same rejection.
- **A run that returned `status: "failed"`.** It has already been through the
  agent's repair loop; the same request would take the same path again.
- **An expired session (401).** Classified `fatal`; the app signs the user out
  and shows the login page.

### Tests

Sixteen tests across
[`tests/errors.test.ts`](../frontend/tests/errors.test.ts) and
[`tests/exportDashboard.test.ts`](../frontend/tests/exportDashboard.test.ts)
pin the classification table and the download file naming — including that
`EXECUTION_ERROR` is recoverable despite its 500-shaped status, that an
unrecognised code falls through to the status rather than becoming fatal, and
that `titanic.csv` exports as `titanic.pdf` and not `titanic.csv.pdf`.

---

## 3. The frontend now has tests

There was no test runner at all — the largest single hole in NFR-09. There is
now one, with **25 tests passing**, and it needed no new dependency:

```
npm test    # node --experimental-strip-types --test "tests/**/*.test.ts"
```

Node 22 runs TypeScript by stripping types. `tsconfig.test.json` is referenced
from the root project, so `tsc -b` type-checks the tests alongside everything
else, and `erasableSyntaxOnly` keeps them to syntax Node can strip.

This is a floor, not a ceiling. What is covered is pure logic — PDF bytes, error
classification, file naming. **Component and end-to-end tests are still absent**,
and those need a real runner (Vitest plus Testing Library) and a browser
environment. What has changed is that the answer to "how many frontend tests are
there" is no longer "none".

---

## 4. What is still open

- **Component and e2e tests** — see above.
- **A zero-row result still renders an empty chart** rather than an empty state.
  This is the known backend defect recorded during the July hardening review,
  not a UI gap: the frontend is drawing what it was handed.
- **Multi-page PDF.** A dashboard taller than one page is scaled down, not
  split. Fine for a demo board; worth revisiting if boards grow.
- **The six states are not covered by automated UI tests** — this audit is a
  read of the code, and the states were exercised by hand. That is what the
  usability cycle and a component suite would harden.

---

*Verified on 15 August 2026: `npm test` (25 passed), `tsc -b` (clean),
`npm run build` (clean), `oxlint` (3 pre-existing warnings, unchanged), and the
generated PDF parsed with `pypdf`.*
