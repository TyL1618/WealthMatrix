const CACHE     = 'wm-v1';
const CDN_CACHE = 'wm-cdn-v1';
const SHELL     = ['/WealthMatrix/', '/WealthMatrix/index.html'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE && k !== CDN_CACHE).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Never intercept Supabase API calls
  if (url.hostname.endsWith('.supabase.co')) return;

  // CDN resources (Chart.js, Supabase JS): cache-first
  if (url.hostname.endsWith('jsdelivr.net')) {
    e.respondWith(
      caches.open(CDN_CACHE).then(cache =>
        cache.match(e.request).then(hit => {
          if (hit) return hit;
          return fetch(e.request).then(res => {
            if (res.ok) cache.put(e.request, res.clone());
            return res;
          });
        })
      )
    );
    return;
  }

  // App shell: network-first, fallback to cached version when offline
  if (url.pathname.startsWith('/WealthMatrix')) {
    e.respondWith(
      fetch(e.request)
        .then(res => {
          if (res.ok) caches.open(CACHE).then(c => c.put(e.request, res.clone()));
          return res;
        })
        .catch(() => caches.match(e.request).then(c => c || caches.match('/WealthMatrix/')))
    );
  }
});
