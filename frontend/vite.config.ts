import { fileURLToPath, URL } from 'node:url'
import babel from '@rolldown/plugin-babel'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const backend = 'http://127.0.0.1:8000'

export default defineConfig(({ command }) => ({
  // Built assets ride the backend's existing /static mount, so the app adds no
  // anonymous route of its own. In dev the app is served from the root instead,
  // so /app/... resolves through Vite's SPA fallback just like it does in prod.
  base: command === 'build' ? '/static/app/' : '/',
  plugins: [
    // Must come before react(): it rewrites route files into lazy chunks.
    tanstackRouter({ target: 'react', autoCodeSplitting: true }),
    react(),
    // React Compiler through Babel, as documented by @vitejs/plugin-react 6.
    babel({ presets: [reactCompilerPreset()] }),
  ],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir: '../web/static/app',
    emptyOutDir: true,
    manifest: true,
  },
  server: {
    // Same origin as far as the browser is concerned: the session cookie set by
    // /login lands on the dev server's host and rides every proxied call. Host is
    // kept (no changeOrigin) so the backend's Origin check still matches.
    proxy: {
      '/api': backend,
      '/login': backend,
      '/logout': backend,
      // The login page's own CSS/JS and the guarded uploads.
      '/static': backend,
    },
  },
  test: {
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // Vitest blanks CSS by default; the token tests read the real files.
    css: { include: [/\.css/] },
  },
}))
