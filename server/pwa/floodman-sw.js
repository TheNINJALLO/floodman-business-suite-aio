/* Floodman Operations service worker */
'use strict';

const RELEASE = '4.7.2';
const STATIC_CACHE = `floodman-static-${RELEASE}`;
const OFFLINE_CACHE = `floodman-offline-${RELEASE}`;
const MANAGED_PREFIXES = ['floodman-static-', 'floodman-offline-'];
const PRECACHE = [
  '/manifest.webmanifest',
  '/floodman-offline.html',
  '/floodman-starting.html',
  '/install-app',
  '/floodman-pwa.css',
  '/floodman-workspace.css',
  '/floodman-pwa.js',
  '/floodman-brand/floodman-mark.svg',
  '/floodman-brand/floodman-wordmark.svg',
  '/floodman-pwa-icons/icon-192.png',
  '/floodman-pwa-icons/icon-512.png',
  '/floodman-pwa-icons/icon-maskable-512.png',
  '/floodman-pwa-icons/apple-touch-icon-180.png',
  '/floodman-pwa-icons/badge-96.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(STATIC_CACHE);
    await cache.addAll(PRECACHE);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((key) => {
      const managed = MANAGED_PREFIXES.some((prefix) => key.startsWith(prefix));
      return managed && key !== STATIC_CACHE && key !== OFFLINE_CACHE ? caches.delete(key) : Promise.resolve(false);
    }));
    await self.clients.claim();
  })());
});

async function fetchWithDeadline(request, ms) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetch(new Request(request, { signal: controller.signal }));
  } finally {
    clearTimeout(timer);
  }
}

async function healthOk(path, ms = 4500) {
  try {
    const response = await fetchWithDeadline(new Request(`${path}?sw=${Date.now()}`, {
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    }), ms);
    if (!response.ok) return false;
    const payload = await response.json().catch(() => ({}));
    return payload.status === 'ok' || payload.status === 'ready';
  } catch (_) {
    return false;
  }
}

async function cachedPage(path, fallbackText, status = 503) {
  const cached = await caches.match(path, { ignoreSearch: true });
  if (cached) return cached;
  try {
    const response = await fetch(path, { cache: 'no-store' });
    if (response.ok) return response;
  } catch (_) {}
  return new Response(fallbackText, { status, headers: { 'Content-Type': 'text/plain' } });
}

async function networkNavigation(request) {
  const url = new URL(request.url);
  const dynamicOfficeRoute = /^\/(?:office|login|logout|setup|customer)(?:\/|$)/.test(url.pathname);
  const deadline = dynamicOfficeRoute ? 30000 : 15000;
  try {
    return await fetchWithDeadline(request, deadline);
  } catch (_) {
    // A private proxied connection can be healthy even when the browser's
    // generic internet flag is false. Ask the actual Floodman services before
    // displaying an offline page.
    const hubOnline = await healthOk('/health/live');
    if (hubOnline) {
      return cachedPage('/floodman-starting.html', 'Floodman Office is starting. Refresh shortly.', 503);
    }
    return cachedPage('/floodman-offline.html', 'Floodman Operations is offline.', 503);
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request, { ignoreSearch: true });
  if (cached) {
    fetch(request).then(async (response) => {
      if (response && response.ok) {
        const cache = await caches.open(STATIC_CACHE);
        await cache.put(request, response.clone());
      }
    }).catch(() => {});
    return cached;
  }
  const response = await fetch(request);
  if (response && response.ok) {
    const cache = await caches.open(STATIC_CACHE);
    await cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(networkNavigation(request));
    return;
  }

  const pwaAsset = url.pathname === '/manifest.webmanifest' ||
    url.pathname === '/floodman-pwa.js' ||
    url.pathname === '/floodman-pwa.css' ||
    url.pathname === '/floodman-workspace.css' ||
    url.pathname === '/floodman-offline.html' ||
    url.pathname === '/floodman-starting.html' ||
    url.pathname === '/install-app' ||
    url.pathname.startsWith('/floodman-pwa-icons/') ||
    url.pathname.startsWith('/floodman-brand/');

  if (pwaAsset) event.respondWith(cacheFirst(request));
  // Customer, document, API, Office, signing, and ERP responses remain network-only.
});

self.addEventListener('message', (event) => {
  const type = event.data && event.data.type;
  if (type === 'SKIP_WAITING') self.skipWaiting();
  if (type === 'CLEAR_PWA_CACHES') {
    event.waitUntil((async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((key) => MANAGED_PREFIXES.some((prefix) => key.startsWith(prefix))).map((key) => caches.delete(key)));
    })());
  }
});

self.addEventListener('push', (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) { payload = { body: event.data ? event.data.text() : '' }; }
  const title = payload.title || 'Floodman Operations';
  const options = {
    body: payload.body || 'Floodman has an update for you.',
    icon: '/floodman-pwa-icons/icon-192.png',
    badge: '/floodman-pwa-icons/badge-96.png',
    data: { url: payload.url || '/workspace' },
    tag: payload.tag || 'floodman-update',
    renotify: Boolean(payload.renotify)
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || '/workspace', self.location.origin).href;
  event.waitUntil((async () => {
    const clientsList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of clientsList) {
      if ('focus' in client) {
        if ('navigate' in client) await client.navigate(target);
        return client.focus();
      }
    }
    return self.clients.openWindow(target);
  })());
});
