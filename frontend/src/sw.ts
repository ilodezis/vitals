/// <reference lib="webworker" />
import { cleanupOutdatedCaches, createHandlerBoundToURL, precacheAndRoute } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { NetworkOnly } from 'workbox-strategies'
import { APP_NAVIGATIONS } from './app/swRoutes'

declare let self: ServiceWorkerGlobalScope

// Clean up older Workbox precaches
cleanupOutdatedCaches()

// Precache app shell assets injected at build time
precacheAndRoute(self.__WB_MANIFEST)

// Navigation fallback: the screens' addresses -> index.html from cache
const handler = createHandlerBoundToURL('/static/app/index.html')
const navigationRoute = new NavigationRoute(handler, {
  allowlist: APP_NAVIGATIONS,
  denylist: [/^\/api/, /^\/static\/uploads/],
})
registerRoute(navigationRoute)

// Explicitly do not cache /api/* (handled by TanStack Query / idb-keyval)
registerRoute(/^\/api\/.*/i, new NetworkOnly())

// NEVER cache /static/uploads/*
registerRoute(/^\/static\/uploads\/.*/i, new NetworkOnly())

// A new build takes over as soon as it is installed. Left to wait, it would sit behind the old
// one until every tab and the installed app were closed, and a deploy would not show up.
self.addEventListener('install', () => {
  void self.skipWaiting()
})

// On activate, delete legacy caches matching vitals-os-* and take the open pages over
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key.startsWith('vitals-os-')).map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  )
})
