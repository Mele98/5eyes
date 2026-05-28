import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

/**
 * Vitest-Konfiguration für die 5eyes Reporting-Sub-App.
 *
 * Separat von `vite.config.ts`, damit der Dev-Server-Block (Proxy) nicht
 * im Test-Setup interferiert. JSDOM-Environment für React-Component-Tests.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
