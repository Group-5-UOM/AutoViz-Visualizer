// Records a ~4-minute walkthrough of AutoViz against a running local stack.
// Usage: node scripts/record-demo.mjs   (expects the app on http://127.0.0.1:5173)
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:5173';
const DATA = path.resolve(here, '../../test-data/demo/penguins-raw.csv');
const OUT = path.resolve(here, '../../../presentation/demo-video');
const W = 1600;
const H = 900;

fs.mkdirSync(OUT, { recursive: true });

const overlay = () => {
  const install = () => {
    if (document.getElementById('__cap')) return;
    const style = document.createElement('style');
    style.textContent = `
      #__cursor{position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;
        background:rgba(184,58,12,.35);border:2px solid #b83a0c;pointer-events:none;z-index:2147483647;
        transition:left .35s ease, top .35s ease, transform .15s ease}
      #__cursor.down{transform:scale(.6);background:rgba(184,58,12,.7)}
      #__cap{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);max-width:1100px;padding:12px 22px;
        background:rgba(20,32,46,.92);color:#fff;font:600 21px/1.35 system-ui,sans-serif;border-radius:10px;
        box-shadow:0 6px 24px rgba(0,0,0,.25);pointer-events:none;z-index:2147483646;text-align:center;
        transition:opacity .3s ease}
      #__cap:empty{opacity:0}
      #__cap small{display:block;font-weight:400;font-size:16px;opacity:.85;margin-top:3px}`;
    document.head.appendChild(style);
    const cursor = document.createElement('div');
    cursor.id = '__cursor';
    const cap = document.createElement('div');
    cap.id = '__cap';
    document.body.append(cursor, cap);
    cap.innerHTML = sessionStorage.getItem('__cap') ?? '';
    addEventListener('mousemove', (e) => { cursor.style.left = `${e.clientX}px`; cursor.style.top = `${e.clientY}px`; }, true);
    addEventListener('mousedown', () => cursor.classList.add('down'), true);
    addEventListener('mouseup', () => cursor.classList.remove('down'), true);
    window.__caption = (html) => { sessionStorage.setItem('__cap', html); cap.innerHTML = html; };
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
};

const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const context = await browser.newContext({
  viewport: { width: W, height: H },
  recordVideo: { dir: OUT, size: { width: W, height: H } },
  acceptDownloads: true,
});
await context.addInitScript(overlay);
const page = await context.newPage();
const t0 = Date.now();
const cuts = [];
const now = () => (Date.now() - t0) / 1000;

const pause = (ms) => page.waitForTimeout(ms * 1.25);
const caption = async (title, sub = '') => {
  await page.evaluate((html) => window.__caption?.(html), sub ? `${title}<small>${sub}</small>` : title);
};
const moveTo = async (locator) => {
  const box = await locator.boundingBox();
  if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 12 });
  await pause(350);
};
const click = async (locator) => { await moveTo(locator); await locator.click(); };
const type = async (locator, text) => { await click(locator); await locator.pressSequentially(text, { delay: 45 }); };
const charts = page.locator('.chart-widget-body');

/** Waits for the AI; the waiting stretch is logged so it can be trimmed. */
async function waitForAi(until) {
  const start = now();
  await until();
  await page.getByLabel('Thinking').waitFor({ state: 'detached', timeout: 120_000 }).catch(() => {});
  const end = now();
  if (end - start > 5) cuts.push([start + 2.5, end - 0.8]);
}

/** Sends a question; if the AI asks back, picks the option matching `prefer` and carries on. */
async function ask(question, sub, prefer = /average|mean/i) {
  const box = page.getByPlaceholder(/Ask for a chart/i);
  await caption(`“${question}”`, sub);
  await type(box, question);
  await pause(400);
  const before = await charts.count();
  await click(page.getByRole('button', { name: 'Send message' }));
  await settle(before, prefer);
}

async function settle(before, prefer) {
  for (let round = 0; round < 3; round += 1) {
    const optionsBefore = await page.locator('.chat-options').count();
    let outcome = 'chart';
    await waitForAi(() => Promise.race([
      charts.nth(before).locator('svg, canvas').first().waitFor({ timeout: 180_000 }).then(() => { outcome = 'chart'; }).catch(() => {}),
      page.locator('.chat-options').nth(optionsBefore).waitFor({ timeout: 180_000 }).then(() => { outcome = 'question'; }).catch(() => {}),
    ]));
    if (outcome === 'chart' || (await charts.count()) > before) break;
    const options = page.locator('.chat-options').last();
    await pause(1000);
    await caption('The AI asked a question back instead of guessing', 'Every option is grounded in the real data');
    await moveTo(options);
    await pause(3000);
    const buttons = options.getByRole('button');
    const preferred = buttons.filter({ hasText: prefer }).first();
    await click((await preferred.count()) ? preferred : buttons.first());
  }
  await pause(1500);
  await moveTo(charts.nth(before));
  await pause(2500);
}

try {
  // 1. Sign in
  await page.goto(`${BASE}/login`);
  await caption('AutoViz AI', 'Ask questions about a spreadsheet in plain language — get charts you can check');
  await pause(3500);
  await caption('Create an account', 'Every dataset, chart and dashboard belongs to this account only');
  await click(page.getByRole('button', { name: 'Create one' }));
  const tag = Date.now().toString().slice(-6);
  await type(page.getByPlaceholder('Choose a username'), `demo_${tag}`);
  await type(page.getByPlaceholder('you@university.edu'), `demo_${tag}@example.com`);
  await type(page.getByPlaceholder('Enter your password'), 'demo-pass-2026');
  await click(page.getByRole('button', { name: 'Create account' }));
  await page.locator('[aria-label="Dashboard canvas"]').waitFor();
  await pause(1500);

  // 2. Upload
  await caption('Upload a data file', 'CSV, Excel, Parquet or JSON — the file stays on our server');
  await moveTo(page.getByRole('button', { name: /Add data file/i }));
  await pause(800);
  await page.locator('input.canvas-file-input').setInputFiles(DATA);
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Dataset name').waitFor({ timeout: 30_000 });
  await dialog.getByLabel('Dataset name').fill('');
  await type(dialog.getByLabel('Dataset name'), 'Palmer penguins');
  const upload = dialog.getByRole('button', { name: 'Upload', exact: true });
  await upload.waitFor();
  await click(upload);
  await page.getByRole('heading', { name: 'Add a data file' }).waitFor({ state: 'detached', timeout: 60_000 });
  await caption('344 penguins × 7 columns', 'species, island, bill length & depth, flipper length, body mass, sex');
  await pause(3500);

  // 3. Privacy notice
  const accept = page.getByRole('button', { name: /I understand/i });
  await accept.waitFor({ timeout: 30_000 });
  await caption('What the AI is allowed to see', 'The question, column names and types, a short profile — never the raw rows or the file');
  await moveTo(accept);
  await pause(5000);
  await click(accept);
  await pause(800);

  // 4. View and clean the dataset
  const sheet = page.locator('[aria-label="Dataset spreadsheet"]');
  const sheetBtn = (name) => sheet.getByRole('button', { name, exact: true });
  const scrollSheet = async (where) => {
    await sheet.locator('.dataset-sheet-scroll').evaluate((el, w) => {
      el.scrollTo({ top: w === 'bottom' ? el.scrollHeight : 0, behavior: 'smooth' });
    }, where);
    await pause(1800);
  };
  await caption('Open the uploaded data', 'The whole file as an editable spreadsheet');
  const openData = page.getByRole('button', { name: 'Open Data' });
  await click((await openData.isVisible()) ? openData : page.getByRole('button', { name: 'Edit Dataset' }));
  await sheet.locator('.dataset-sheet-table').waitFor({ timeout: 60_000 });
  await pause(1500);
  await caption('Row 4 is empty — a penguin with no measurements', 'The raw file has 11 rows with missing values');
  await moveTo(sheet.getByLabel('bill_length_mm row 4', { exact: true }));
  await pause(4000);
  await caption('344 rows in the raw file');
  await scrollSheet('bottom');
  await pause(2500);
  await scrollSheet('top');

  await caption('Click any cell to edit it', 'Like a spreadsheet — body mass of penguin 1: 3750 → 3800');
  const cell = sheet.getByLabel('body_mass_g row 1', { exact: true });
  await click(cell);
  await cell.press('ControlOrMeta+a');
  await cell.pressSequentially('3800', { delay: 120 });
  await cell.press('Tab');
  await pause(2500);

  await caption('Drop Empty — remove every row with a missing value', 'One click, no formulas');
  await click(sheetBtn('Drop Empty'));
  await pause(2500);
  await caption('Now 333 rows', '“Changes not saved” — nothing is stored until you press Save');
  await scrollSheet('bottom');
  await moveTo(sheet.locator('.dataset-sheet-dirty'));
  await pause(3500);

  await caption('Discard undoes every unsaved edit', 'The empty rows and the original body mass come back');
  await click(sheetBtn('Discard'));
  await pause(1500);
  await scrollSheet('bottom');
  await pause(2000);
  await scrollSheet('top');
  await moveTo(sheet.getByLabel('body_mass_g row 1', { exact: true }));
  await pause(3000);

  await caption('Drop Empty again, then Save', 'Saving stores the cleaned table as a new dataset');
  await click(sheetBtn('Drop Empty'));
  await pause(2000);
  const saveStart = now();
  await click(sheetBtn('Save'));
  await sheet.waitFor({ state: 'detached', timeout: 90_000 });
  if (now() - saveStart > 6) cuts.push([saveStart + 2.5, now() - 0.8]);
  await pause(1200);
  await caption('Saved: 333 clean penguins × 7 columns', 'Every chart from here on uses the cleaned data');
  const ready = page.getByText(/333 rows/);
  if (await ready.isVisible()) await moveTo(ready);
  await pause(4000);

  // 5. Prompts
  await ask('Which penguin species has the deepest bills?', 'The AI writes a plan; our code runs it as SQL and draws the chart');
  await caption('Every number in the summary is checked against the query result', 'Unsupported numbers are replaced by a template');
  await pause(3500);
  await ask('Is flipper length related to body mass? Colour by species.', 'A relationship question gives a scatter plot');
  await ask('How many penguins live on each island?', 'Counting rows per group — still no number computed by the AI');
  await ask('Show the distribution of body mass', 'A distribution question gives a histogram');

  // 6. Ambiguity
  const vague = 'Which species is best?';
  await caption(`“${vague}”`, 'Best at what? AutoViz asks instead of guessing');
  await type(page.getByPlaceholder(/Ask for a chart/i), vague);
  const beforeVague = await charts.count();
  await click(page.getByRole('button', { name: 'Send message' }));
  await settle(beforeVague, /flipper/i);
  await caption('Answered with the measure the user picked');
  await pause(2500);

  // 7. Plan JSON: open, edit, re-run
  const first = page.locator('.chart-widget').first();
  await caption('Every chart has a plan you can read', 'Click { } on the chart');
  await moveTo(first);
  await pause(600);
  await click(page.locator('.chart-widget-actions').first().getByRole('button', { name: 'View / edit analysis plan' }));
  const editor = page.getByLabel('analysis_plan');
  await editor.waitFor();
  await pause(800);
  await caption('This JSON is everything the AI decided', 'Filter, grouping, aggregation, chart — no code, no numbers');
  await moveTo(editor);
  await pause(5500);
  const plan = JSON.parse(await editor.inputValue());
  plan.group_by = ['species', 'sex'];
  delete plan.chart;
  await caption('Edit the plan: group by species and sex', '"group_by": ["species", "sex"]');
  await click(editor);
  await editor.fill(JSON.stringify(plan, null, 2));
  await pause(3000);
  await caption('Run plan — the chart is rebuilt without calling the AI');
  await click(page.getByRole('button', { name: 'Run plan' }));
  await page.getByRole('button', { name: 'Run plan' }).waitFor({ timeout: 60_000 });
  await pause(1500);
  await moveTo(first);
  await caption('One field changed, the chart changed with it', 'Now split by sex — a grouped bar chart, re-run from the edited plan');
  await pause(5500);
  const close = page.getByRole('button', { name: 'Close plan editor' });
  if (await close.isVisible()) await click(close);
  await pause(800);

  // 8. Export
  await caption('Export the dashboard', 'One picture of the canvas, or a single-page PDF');
  const exportBtn = page.getByRole('button', { name: /^Export/ });
  await click(exportBtn);
  await pause(1200);
  let dl = page.waitForEvent('download', { timeout: 60_000 });
  await click(page.getByRole('menuitem', { name: /PNG image/i }).or(page.getByRole('button', { name: /PNG image/i })).first());
  await (await dl).saveAs(path.join(OUT, 'autoviz-dashboard.png'));
  await pause(2000);
  await click(exportBtn);
  await pause(1000);
  dl = page.waitForEvent('download', { timeout: 60_000 });
  await click(page.getByRole('menuitem', { name: /PDF document/i }).or(page.getByRole('button', { name: /PDF document/i })).first());
  await (await dl).saveAs(path.join(OUT, 'autoviz-dashboard.pdf'));
  await caption('Saved to downloads', 'autoviz-dashboard.png · autoviz-dashboard.pdf');
  await pause(3000);

  await caption('The AI plans. Code calculates.', 'Every chart can be checked — and your raw data never goes to the model');
  await page.mouse.move(W / 2, H / 2 - 100, { steps: 10 });
  await pause(5000);
} catch (err) {
  await page.screenshot({ path: path.join(OUT, 'failure.png') });
  console.error('FAILED at', now().toFixed(1), 's:', err.message);
  process.exitCode = 1;
} finally {
  const video = page.video();
  await context.close();
  await browser.close();
  const raw = await video.path();
  fs.renameSync(raw, path.join(OUT, 'raw.webm'));
  fs.writeFileSync(path.join(OUT, 'cuts.json'), JSON.stringify({ total: now(), cuts }, null, 2));
  console.log('video', path.join(OUT, 'raw.webm'), 'length', now().toFixed(1), 's, cuts', JSON.stringify(cuts));
}
