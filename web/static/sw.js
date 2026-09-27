// v9 — bumped so `activate` drops the v8 cache with the move to plain page
// loads (every tap is now a navigation that asks for the page's assets).
const CACHE_NAME = 'vitals-os-v9';

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

  // /static/uploads/* is user data (lab sheets, InBody printouts, progress
  // photos), not app shell — caching it would leave medical images in Cache
  // Storage forever, outside the session and untouched by logout.
  if (sameOrigin && url.pathname.startsWith('/static/')
      && !url.pathname.startsWith('/static/uploads/')) {
    // A ?v=<mtime> URL (static_version() in templating.py) names one exact
    // build of the file — a deploy changes the URL, never the bytes behind it.
    // So once cached it is served straight from the cache with no background
    // refetch: every page load asks for a dozen of these, and revalidating
    // each one on every tap is a dozen round trips to the server for nothing.
    // ponytail: superseded builds stay cached until CACHE_NAME is next bumped —
    // a few hundred KB a year; prune by URL path on activate if that matters.
    if (url.searchParams.has('v')) {
      event.respondWith(
        caches.open(CACHE_NAME).then((cache) =>
          cache.match(req).then((cached) => cached || fetch(req).then((res) => {
            if (res && res.status === 200) cache.put(req, res.clone());
            return res;
          }))
        )
      );
      return;
    }
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
