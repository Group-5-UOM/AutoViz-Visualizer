import { expect, type Page } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

/** Unique credentials so re-runs never collide on email uniqueness. */
export function uniqueUser(prefix = 'e2e') {
  const stamp = `${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
  return {
    username: `${prefix}_${stamp}`.slice(0, 32),
    email: `${prefix}_${stamp}@example.com`,
    password: 'playwright-pass-1',
  };
}

export function irisCsvPath() {
  return path.resolve(here, '../../test-data/general-testing/iris.csv');
}

export function canvas(page: Page) {
  return page.locator('[aria-label="Dashboard canvas"]');
}

/** Register a fresh account and land on the dashboard. */
export async function registerAndEnterBoard(page: Page) {
  const user = uniqueUser();
  await page.goto('/login');
  await page.getByRole('button', { name: 'Create one' }).click();
  await expect(page.getByRole('region', { name: 'Create account' })).toBeVisible();
  await page.getByPlaceholder('Choose a username').fill(user.username);
  await page.getByPlaceholder('you@university.edu').fill(user.email);
  await page.getByPlaceholder('Enter your password').fill(user.password);
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(canvas(page)).toBeVisible();
  return user;
}

/** Sign in with an existing account. */
export async function login(page: Page, email: string, password: string) {
  await page.goto('/login');
  await page.getByPlaceholder('you@university.edu').fill(email);
  await page.getByPlaceholder('Enter your password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(canvas(page)).toBeVisible();
}

/**
 * Sign out from the board topbar.
 * On narrow Chromium viewports the icon can sit under an overflow parent;
 * force avoids a pointer-events false negative that WebKit does not hit.
 */
export async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click({ force: true });
  await expect(page).toHaveURL(/\/login/);
}

/** Confirm the "Name this dataset" dialog (CSV / single-table path). */
export async function confirmNamedUpload(page: Page) {
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Name this dataset' })).toBeVisible({
    timeout: 30_000,
  });
  const upload = dialog.getByRole('button', { name: 'Upload', exact: true });
  await expect(upload).toBeEnabled({ timeout: 30_000 });
  // Blur first: mobile Chromium keeps the soft keyboard / focused input
  // covering the footer, so a normal click lands on Cancel or the header.
  await dialog.getByLabel('Dataset name').blur();
  await upload.click({ force: true });
}
