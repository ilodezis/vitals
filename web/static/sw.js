const CACHE_NAME = 'vitals-os-v4';

const OFFLINE_PAGE = '/static/offline.html';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.add(OFFLINE_PAGE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => caches.match(OFFLINE_PAGE))
    );
    return;
  }

  if (sameOrigin && url.pathname.startsWith('/static/')) {
    // Stale-while-revalidate: serve the cached copy instantly (offline-friendly),
    // but ALWAYS kick off a background fetch to refresh the cache. Cache-first
    // (the old strategy) pinned /static/* to whatever was cached until CACHE_NAME
    // was bumped by hand, so updated CSS/JS stayed stale after a deploy. Now a
    // deploy is picked up on the next load after one stale paint.
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) =>
        cache.match(req).then((cached) => {
          const network = fetch(req)
            .then((res) => {
              if (res && res.status === 200) {
                cache.put(req, res.clone());
              }
              return res;
            })
            .catch(() => cached);
          return cached || network;
        })
      )
    );
  }
});
