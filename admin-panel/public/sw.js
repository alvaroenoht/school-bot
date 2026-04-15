const CACHE = 'edulink-v2';
const SHELL = ['/manifest.json', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // API: always network
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(req));
    return;
  }

  // HTML navigations: network-first, fall back to cached shell only if offline
  const isNav = req.mode === 'navigate' ||
    (req.headers.get('accept') || '').includes('text/html');
  if (isNav) {
    e.respondWith(
      fetch(req).catch(() => caches.match(req).then(c => c || caches.match('/')))
    );
    return;
  }

  // Next.js hashed assets: cache-first (immutable by hash)
  if (url.pathname.startsWith('/_next/static/')) {
    e.respondWith(
      caches.match(req).then(cached => cached || fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy));
        return res;
      }))
    );
    return;
  }

  // Everything else: network, fall back to cache
  e.respondWith(fetch(req).catch(() => caches.match(req)));
});
