import { test, expect } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

test.describe('Dashboard E2E', () => {
  test('uploads a dataset, asks a question, and renders a chart', async ({ page }) => {
    // 1. Navigate to the dashboard
    await page.goto('/');
    await expect(page).toHaveTitle(/AutoViz/i);

    // If redirected to login, create a new account
    if (page.url().includes('/login')) {
      await page.getByText('Create one').click();
      const ts = Date.now();
      const testUser = `testuser_${ts}`;
      await page.getByPlaceholder('Choose a username').fill(testUser);
      await page.getByPlaceholder('you@university.edu').fill(`${testUser}@university.edu`);
      await page.getByPlaceholder('Enter your password').fill('password123');
      await page.getByRole('button', { name: 'Create account' }).click();
      
      // Wait for navigation back to dashboard
      await expect(page).toHaveURL(/.*dashboard.*/, { timeout: 15000 });
    }

    // 2. Upload iris.csv
    const fileInput = page.locator('input[type="file"]').first();
    const filePath = path.resolve(__dirname, '../../test-data/general-testing/iris.csv');
    
    // Wait for the input to be attached to the DOM
    await fileInput.waitFor({ state: 'attached' });
    await fileInput.setInputFiles(filePath);

    // 3. Handle the "Name this dataset" modal
    await page.getByRole('button', { name: 'Upload' }).click({ force: true });

    // 3. Wait for the upload to process and the dataset to become active.
    // The chat input placeholder changes when a dataset is active.
    const chatInput = page.getByPlaceholder(/Ask for a chart/i).first();
    await expect(chatInput).toBeVisible({ timeout: 15000 });

    // 4. Ask a question
    await chatInput.fill('Show a scatter plot of sepal_length vs sepal_width');
    await chatInput.press('Enter');

    // 5. Wait for the chart widget to appear on the canvas
    const chartWidget = page.locator('.chart-widget').first();
    // Chart generation can take several seconds via the backend LLM (especially when tests run in parallel)
    await expect(chartWidget).toBeVisible({ timeout: 300000 });

    // 6. Test dragging the widget
    const widgetBoundingBox = await chartWidget.boundingBox();
    if (widgetBoundingBox) {
      await page.mouse.move(widgetBoundingBox.x + 10, widgetBoundingBox.y + 10);
      await page.mouse.down();
      await page.mouse.move(widgetBoundingBox.x + 100, widgetBoundingBox.y + 100);
      await page.mouse.up();
    }

    // 7. Test saving the dashboard
    await page.getByRole('button', { name: 'Save' }).click();
    // Check for success saving indicator (if any) or just that it didn't crash

    // 8. Test deleting the widget
    await page.getByRole('button', { name: 'Delete chart' }).first().click();
    await expect(chartWidget).not.toBeVisible();
  });
});
