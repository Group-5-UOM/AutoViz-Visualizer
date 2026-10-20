import { expect, test } from '@playwright/test';
import { canvas, login, registerAndEnterBoard, signOut, uniqueUser } from './helpers';

test.describe('Authentication', () => {
  test('register creates a session and opens the board', async ({ page }) => {
    await registerAndEnterBoard(page);
    await expect(canvas(page)).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Add a data file' })).toBeVisible();
  });

  test('login rejects bad credentials', async ({ page }) => {
    await page.goto('/login');
    await page.getByPlaceholder('you@university.edu').fill('nobody@example.com');
    await page.getByPlaceholder('Enter your password').fill('wrong-password');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test('login with a valid account reaches the board', async ({ page }) => {
    const user = uniqueUser('login');
    await page.goto('/login');
    await page.getByRole('button', { name: 'Create one' }).click();
    await page.getByPlaceholder('Choose a username').fill(user.username);
    await page.getByPlaceholder('you@university.edu').fill(user.email);
    await page.getByPlaceholder('Enter your password').fill(user.password);
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page).toHaveURL(/\/dashboard/);

    await signOut(page);

    await login(page, user.email, user.password);
    await expect(canvas(page)).toBeVisible();
  });
});
