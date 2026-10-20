import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { canvas, confirmNamedUpload } from '../e2e/helpers';

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(here, '../../../presentation/screens');
const TIPS = path.resolve(here, '../../test-data/sales-retail/tips.csv');

const shot = (page: Page, name: string) =>
  page.screenshot({ path: path.join(OUT, `${name}.png`) });

async function ask(page: Page, question: string, expectedCharts: number) {
  await page.getByPlaceholder(/Ask for a chart/i).fill(question);
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.locator('.chart-widget-body')).toHaveCount(expectedCharts, { timeout: 180_000 });
  await expect(page.locator('.chart-widget-body').nth(expectedCharts - 1).locator('svg, canvas').first())
    .toBeVisible({ timeout: 60_000 });
  await expect(page.getByLabel('Thinking')).toHaveCount(0, { timeout: 60_000 });
  await page.waitForTimeout(1200);
}

const widgetButton = (page: Page, index: number, name: string) =>
  page.locator('.chart-widget-actions').nth(index).getByRole('button', { name, exact: true });

const sidebar = (page: Page, title: string) => page.locator(`#sidebar button[title="${title}"]`);

test('capture remaining screenshots', async ({ page }) => {
  test.skip(process.env.PART !== '2');
  const tag = String(Math.floor(1000 + Math.random() * 9000));
  await page.goto('/login');
  await page.getByRole('button', { name: 'Create one' }).click();
  await page.getByPlaceholder('Choose a username').fill(`demo_${tag}`);
  await page.getByPlaceholder('you@university.edu').fill(`demo_${tag}_${Date.now()}@example.com`);
  await page.getByPlaceholder('Enter your password').fill('presentation-pass-1');
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(canvas(page)).toBeVisible();
  await page.locator('input.canvas-file-input').setInputFiles(TIPS);
  await page.getByRole('dialog').getByLabel('Dataset name').fill('Restaurant tips');
  await confirmNamedUpload(page);
  await expect(page.getByRole('heading', { name: 'Add a data file' })).toHaveCount(0, { timeout: 60_000 });
  await page.getByRole('button', { name: /I understand/i }).click();

  await page.getByPlaceholder(/Ask for a chart/i).fill('Which days are the best?');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.locator('.chat-options').last()).toBeVisible({ timeout: 150_000 }).catch(() => {});
  await expect(page.getByLabel('Thinking')).toHaveCount(0, { timeout: 60_000 }).catch(() => {});
  await page.waitForTimeout(1200);
  await shot(page, '18-clarification');

  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, '16-settings');
  await page.mouse.move(900, 500);
  await page.mouse.wheel(0, 900);
  await page.waitForTimeout(600);
  await shot(page, '17-settings-lower');
});

test('capture product screenshots', async ({ page }) => {
  test.skip(process.env.PART === '2');
  const tag = String(Math.floor(1000 + Math.random() * 9000));
  await page.goto('/login');
  await page.waitForTimeout(800);
  await shot(page, '01-login');

  await page.getByRole('button', { name: 'Create one' }).click();
  await page.getByPlaceholder('Choose a username').fill(`demo_${tag}`);
  await page.getByPlaceholder('you@university.edu').fill(`demo_${tag}_${Date.now()}@example.com`);
  await page.getByPlaceholder('Enter your password').fill('presentation-pass-1');
  await page.waitForTimeout(400);
  await shot(page, '02-register');
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(canvas(page)).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, '03-empty-board');

  await page.locator('input.canvas-file-input').setInputFiles(TIPS);
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Name this dataset' })).toBeVisible({ timeout: 30_000 });
  await dialog.getByLabel('Dataset name').fill('Restaurant tips');
  await page.waitForTimeout(600);
  await shot(page, '04-name-upload');
  await confirmNamedUpload(page);
  await expect(page.getByRole('heading', { name: 'Add a data file' })).toHaveCount(0, { timeout: 60_000 });
  await page.waitForTimeout(1000);
  await shot(page, '05-llm-notice');

  await page.getByRole('button', { name: /I understand/i }).click();
  await ask(page, 'Show total bill by day of the week as a bar chart', 1);
  await shot(page, '06-first-chart');

  await ask(page, 'Scatter plot of total bill against tip, coloured by smoker', 2);
  await ask(page, 'Average tip by time of day', 3);
  await shot(page, '07-dashboard');

  await widgetButton(page, 0, 'View / edit analysis plan').click({ force: true });
  await expect(page.getByLabel('Analysis plan editor')).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, '08-plan-panel');
  await page.getByRole('button', { name: 'Close plan editor' }).click();

  await widgetButton(page, 0, 'Style options').click({ force: true });
  await page.waitForTimeout(800);
  await shot(page, '09-style-panel');
  await page.getByRole('button', { name: 'Close style options' }).click();

  await widgetButton(page, 0, 'About this chart').click({ force: true });
  await page.waitForTimeout(800);
  await shot(page, '10-about-chart');
  await page.getByRole('button', { name: 'Close about this chart' }).click({ force: true }).catch(() => {});

  await page.getByRole('button', { name: 'Export' }).click({ force: true });
  await page.waitForTimeout(600);
  await shot(page, '11-export-menu');
  await page.keyboard.press('Escape');
  await page.mouse.click(1200, 800);

  await page.getByTitle('Share dashboard').click({ force: true });
  await page.waitForTimeout(800);
  await shot(page, '12-share');
  await page.keyboard.press('Escape');
  await page.mouse.click(1200, 800);

  await page.getByRole('button', { name: 'Edit Dataset' }).click({ force: true });
  await expect(page.getByLabel('Dataset spreadsheet')).toBeVisible();
  await page.waitForTimeout(1200);
  await shot(page, '13-dataset-sheet');

  await page.getByRole('button', { name: 'Datasets' }).click({ force: true });
  await page.waitForTimeout(1000);
  await shot(page, '14-datasets');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Close' }).first().click({ force: true }).catch(() => {});

  await page.getByRole('button', { name: 'Dashboards' }).click({ force: true });
  await page.waitForTimeout(1000);
  await shot(page, '15-dashboards');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Close' }).first().click({ force: true }).catch(() => {});

  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, '16-settings');
  await page.mouse.wheel(0, 900);
  await page.waitForTimeout(600);
  await shot(page, '17-settings-lower');

  await page.goto('/dashboard');
  await expect(canvas(page)).toBeVisible();
  await page.getByRole('button', { name: 'AI Chat' }).click({ force: true });
  const composer = page.getByPlaceholder(/Ask for a chart/i);
  await expect(composer).toBeEnabled({ timeout: 60_000 });
  await composer.fill('Which days are the best?');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.locator('.chat-options').last()).toBeVisible({ timeout: 150_000 }).catch(() => {});
  await expect(page.getByLabel('Thinking')).toHaveCount(0, { timeout: 60_000 }).catch(() => {});
  await page.waitForTimeout(1200);
  await shot(page, '18-clarification');
});
