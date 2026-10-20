import { defineConfig } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base,
  testDir: './e2e-screens',
  timeout: 600_000,
  expect: { timeout: 120_000 },
  reporter: [['list']],
  retries: 0,
  use: {
    ...base.use,
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 2,
    screenshot: 'off',
  },
  projects: [{ name: 'screens', use: { browserName: 'chromium', channel: 'chrome' } }],
});
