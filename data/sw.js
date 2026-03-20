/**
 * IHC Fleet Dashboard – Service Worker
 * Offline-first caching so mechanics can view the last-known
 * dashboard state even without a network connection.
 */

const CACHE_NAME = 'ihc-fleet-v1';

// Assets to pre-cache on install
const PRECACHE_ASSETS = [
  './index.html',
  './manifest.json',
  './icon.svg',
  './icon-192.png',
  './icon-512.png',
];

// External CDN assets to cache on first fetch
const CDN_CACHE_NAME = 'ihc-fleet-cdn-v1';

// JSON data files – always try network first, fall back to cache
const DATA_FILES = [
  './aircraft_locations.json',
  './aog_status.json',
  './flight_hours_history.json',
  './base_assignments.json',
  './dashboard_version.json',
];

// ── Install ─────────────────────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      // Pre-cache core assets; ignore failures for assets that may not exist yet
      return Promise.allSettled(
        PRECACHE_ASSETS.map((url) =>
          cache.add(url).catch(() => {/* skip missing assets during install */})
        )
      );
    }).then(() => self.skipWaiting())
  );
});

// ── Activate ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  const validCaches = [CACHE_NAME, CDN_CACHE_NAME];
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((name) => !validCaches.includes(name))
          .map((name) => caches.delete(name))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch ─────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Skip non-GET requests and browser-extension requests
  if (event.request.method !== 'GET') return;
  if (!url.protocol.startsWith('http')) return;

  // Data JSON files: network-first so mechanics always see latest data
  if (DATA_FILES.some((f) => url.pathname.endsWith(f.replace('./', '')))) {
    event.respondWith(networkFirstWithCache(event.request, CACHE_NAME));
    return;
  }

  // CDN assets (fonts, FullCalendar, Chart.js, Leaflet): cache-first
  if (
    url.hostname.includes('cdn.jsdelivr.net') ||
    url.hostname.includes('fonts.googleapis.com') ||
    url.hostname.includes('fonts.gstatic.com') ||
    url.hostname.includes('unpkg.com')
  ) {
    event.respondWith(cacheFirstWithNetwork(event.request, CDN_CACHE_NAME));
    return;
  }

  // Same-origin assets: cache-first, fall back to network
  if (url.origin === self.location.origin) {
    event.respondWith(cacheFirstWithNetwork(event.request, CACHE_NAME));
    return;
  }
});

// ── Strategies ────────────────────────────────────────────────────────────────

/**
 * Cache-first: serve from cache; if not found fetch from network and cache it.
 * Best for static assets that rarely change.
 */
async function cacheFirstWithNetwork(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;

  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch {
    return new Response('Offline – asset not cached', { status: 503 });
  }
}

/**
 * Network-first: try the network; on failure return the cached version.
 * Best for data that should be fresh but can fall back to stale.
 */
async function networkFirstWithCache(request, cacheName) {
  const cache = await caches.open(cacheName);

  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    return new Response(
      JSON.stringify({ offline: true, message: 'No cached data available' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } }
    );
  }
}

// ── Push Notifications (placeholder for future 2-way comms) ──────────────────
self.addEventListener('push', (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || 'IHC Fleet Alert', {
      body: data.body || '',
      icon: './icon-192.png',
      badge: './icon-192.png',
      tag: data.tag || 'ihc-fleet',
      data: { url: data.url || './' },
      vibrate: [200, 100, 200],
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || './';
  event.waitUntil(
    clients.matchAll({ type: 'window' }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url === targetUrl && 'focus' in client) {
          return client.focus();
        }
      }
      return clients.openWindow(targetUrl);
    })
  );
});
