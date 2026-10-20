import { expect, test } from '@playwright/test';
import { canvas, confirmNamedUpload, irisCsvPath, registerAndEnterBoard } from './helpers';

test.describe('Board happy path', () => {
  test('empty board shows upload prompt and AI chat', async ({ page }) => {
    await registerAndEnterBoard(page);

    await expect(canvas(page)).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Add a data file' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add data file' })).toBeVisible();

    await expect(page.getByRole('region', { name: 'AI chat' })).toBeVisible();
    await expect(
      page.getByRole('note').filter({ hasText: /Add a CSV file to the canvas to start chatting/i }),
    ).toBeVisible();
  });

  test('upload CSV unlocks the chat composer', async ({ page }) => {
    await registerAndEnterBoard(page);

    await page.locator('input.canvas-file-input').setInputFiles(irisCsvPath());
    await confirmNamedUpload(page);

    await expect(page.getByRole('heading', { name: 'Add a data file' })).toHaveCount(0, {
      timeout: 45_000,
    });
    await expect(page.getByRole('region', { name: 'AI chat' })).toBeVisible();

    // After consent (or if already accepted), the composer should be usable.
    const consent = page.getByRole('button', { name: /I understand/i });
    if (await consent.isVisible().catch(() => false)) {
      await consent.click();
    }
    await expect(
      page.getByPlaceholder(/Ask for a chart|Change |Add a data file first/i),
    ).toBeEnabled({ timeout: 30_000 });
  });

  test('settings page is reachable from the board', async ({ page }) => {
    await registerAndEnterBoard(page);
    await page.goto('/settings');
    await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Account', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Back' }).click();
    await expect(page).toHaveURL(/\/dashboard/);
  });
});
