/**
 * Floodman Portal - Service Worker
 * Enables offline functionality and app installability
 */

const CACHE_NAME = 'floodman-portal-erp-v2';
const STATIC_ASSETS = [
    '/portal/assets/style.css',
    '/portal/assets/floodman-erp.css?v=20260911',
    '/portal/assets/script.js',
    '/portal/assets/offline.js',
    '/portal/manifest.json'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('[SW] Caching static assets');
            // Cache what we can, ignore failures (some pages need auth)
            return Promise.allSettled(
                STATIC_ASSETS.map(url =>
                    cache.add(url).catch(() => console.log('[SW] Could not cache:', url))
                )
            );
        })
    );
    self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating...');
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName.startsWith('floodman-portal-') && cacheName !== CACHE_NAME) {
                        console.log('[SW] Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
    self.clients.claim();
});

// Fetch event - network first, fall back to cache
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    // Skip external requests
    if (url.origin !== location.origin) {
        return;
    }

    // Skip API calls (let them handle their own offline behavior)
    if (!url.pathname.startsWith('/portal/assets/') && url.pathname !== '/portal/manifest.json') {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // Cache successful responses
                if (response.status === 200) {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseClone);
                    });
                }
                return response;
            })
            .catch(() => {
                // Network failed, try cache
                return caches.match(event.request).then((cachedResponse) => {
                    if (cachedResponse) {
                        return cachedResponse;
                    }
                    // Return offline page for navigation requests
                    if (event.request.mode === 'navigate') {
                        return caches.match('/portal/index.php');
                    }
                });
            })
    );
});

// Handle background sync for photos
self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-photos') {
        console.log('[SW] Background sync triggered');
        event.waitUntil(syncPhotos());
    }
});

// Message handler for manual sync trigger
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

async function syncPhotos() {
    // The actual sync logic is in offline.js
    // This just notifies clients to sync
    const clients = await self.clients.matchAll();
    clients.forEach(client => {
        client.postMessage({ type: 'SYNC_PHOTOS' });
    });
}
