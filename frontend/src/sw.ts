/// <reference lib="webworker" />
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { NetworkOnly } from 'workbox-strategies'

declare let self: ServiceWorkerGlobalScope

// Clean up older Workbox precaches
cleanupOutdatedCaches()

// Precache app shell assets injected at build time
precacheAndRoute(self.__WB_MANIFEST)

// Navigation fallback: /app/* -> index.html from cache
const handler = createHandlerBoundToURL('/static/app/index.html')
const navigationRoute = new NavigationRoute(handler, {
  allowlist: [/^\/app(\/.*)?$/],
  denylist: [/^\/api/, /^\/static\/uploads/],
})
registerRoute(navigationRoute)

// Explicitly do not cache /api/* (handled by TanStack Query / idb-keyval)
registerRoute(/^\/api\/.*/i, new NetworkOnly())

// NEVER cache /static/uploads/*
registerRoute(/^\/static\/uploads\/.*/i, new NetworkOnly())

// On activate, delete legacy caches matching vitals-os-*
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key.startsWith('vitals-os-')).map((key) => caches.delete(key))
      )
    )
  )
})
