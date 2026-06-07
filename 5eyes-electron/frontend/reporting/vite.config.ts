import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

/**
 * Vite-Konfiguration der 5eyes Reporting-Sub-App.
 *
 * Build-Output landet in `dist/` relativ zu diesem Verzeichnis. Die
 * Electron-Shell (5eyes-electron/main/electron-main.cjs) lädt das
 * Resultat als statische Dateien — kein Dev-Server in Production.
 *
 * Dev-Modus: `npm run dev` öffnet http://localhost:5173 für lokales
 * Iterieren. API-Calls gehen an http://localhost:8000 (FastAPI-Backend),
 * Proxy konfiguriert weiter unten.
 */
export default defineConfig({
  plugins: [react()],
  // Bug-#6 (2026-06-07): Reporting-App wird vom 5eyes-Backend unter
  // /reporting/ als Static-Mount serviert (keine separate Vite-Instanz im
  // Demo/Production). `base` muss daher mit dem Backend-Mount-Pfad
  // uebereinstimmen, sonst zeigen Asset-URLs ins Leere.
  base: '/reporting/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '^/mandates/.*/advisory-report$': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/admin': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
    target: 'es2022',
  },
});
