import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import babel from '@rolldown/plugin-babel'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig } from 'vitest/config'

const backend = 'http://127.0.0.1:8000'

// What the device keeps is only good for the API contract it was made under, so the persisted
// query cache is stamped with a hash of the committed schema and dropped when the schema moves.
const apiBuster = createHash('sha256')
  .update(readFileSync(new URL('./src/api/openapi.json', import.meta.url)))
  .digest('hex')
  .slice(0, 16)

// Object form on purpose: the string shorthand turns changeOrigin on, which
// swaps the Host for the backend's while the browser's Origin stays put, and the
// backend answers 403 to any unsafe request whose Origin differs from its Host.
const toBackend = { target: backend, changeOrigin: false }

function preloadFonts() {
  return {
    name: 'preload-fonts',
    apply: 'build' as const,
    transformIndexHtml(html: string, { bundle }: { bundle?: Record<string, unknown> }) {
      if (!bundle) return html
      const tags: string[] = []
      for (const fileName of Object.keys(bundle)) {
        if (!fileName.endsWith('.woff2')) continue
        const lower = fileName.toLowerCase()
        const isTargetFamily = lower.includes('geologica') || lower.includes('golos')
        const isTargetSubset =
          (lower.includes('cyrillic') && !lower.includes('cyrillic-ext')) ||
          (lower.includes('latin') && !lower.includes('latin-ext'))
        const isNormal = lower.includes('normal')
        if (isTargetFamily && isTargetSubset && isNormal) {
          tags.push(`<link rel="preload" as="font" type="font/woff2" crossorigin href="/static/app/${fileName}">`)
        }
      }
      if (tags.length === 0) return html
      return html.replace('</head>', `    ${tags.join('\n    ')}\n  </head>`)
    },
  }
}

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
    preloadFonts(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      registerType: 'autoUpdate',
      injectRegister: null,
      manifest: {
        // The whole site, not the folder the build is served from: the login and the
        // doctor's report open inside the installed app too.
        scope: '/',
        start_url: '/app/today',
        name: 'Vitals',
        short_name: 'Vitals',
        display: 'standalone',
        background_color: '#1B1820',
        theme_color: '#1B1820',
        icons: [
          {
            src: '/static/icons/icon-192.png',
            sizes: '192x192',
            type: 'image/png',
          },
          {
            src: '/static/icons/icon-512.png',
            sizes: '512x512',
            type: 'image/png',
          },
        ],
      },
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
      },
    }),
  ],
  define: { __API_BUSTER__: JSON.stringify(apiBuster) },
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
    // /login lands on the dev server's host and rides every proxied call.
    proxy: {
      '/api': toBackend,
      '/login': toBackend,
      '/logout': toBackend,
      // The login page's own CSS/JS and the guarded uploads.
      '/static': toBackend,
    },
  },
  test: {
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // Vitest blanks CSS by default; the token tests read the real files.
    css: { include: [/\.css/] },
  },
}))
