// Bump this version whenever the offline shell changes.
const VERSION = 'v12';
const BASE = new URL('./', self.location.href);
const PREFIX = 'webclock-' + BASE.pathname + '-';
const CACHE = PREFIX + VERSION;
const SHELL = ['', 'static/clock.css', 'static/time-format.js', 'static/time-inputs.js', 'static/time-inputs.css', 'static/clock.js', 'static/offline.js',
    'static/brand/logo.svg', 'static/brand/icon-32.png', 'static/brand/apple-touch-icon.png', 'static/brand/favicon.ico'].map(path => new URL(path, BASE).href);

self.addEventListener('install', event => {
    event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(
        SHELL.map(url => new Request(url, {cache: 'reload'}))
    )));
});

self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        for (const name of await caches.keys()) {
            if (name.startsWith(PREFIX) && name !== CACHE) await caches.delete(name);
        }
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', event => {
    if (event.request.method !== 'GET') return;
    const url = new URL(event.request.url);
    if (url.origin !== BASE.origin) return;
    // Only the clock shell is cached. Never intercept admin, API, or calendar requests.
    const key = url.pathname === BASE.pathname + 'index.html' ? BASE.href : url.origin + url.pathname;
    if (!SHELL.includes(key)) return;
    event.respondWith((async () => {
        const cache = await caches.open(CACHE);
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 3000);
        try {
            const response = await fetch(event.request, {signal: controller.signal});
            if (!response.ok) throw new Error('Shell unavailable');
            // Cache failure must not prevent an online page from opening.
            event.waitUntil(cache.put(key, response.clone()).catch(() => {}));
            return response;
        } catch (error) {
            return await cache.match(key) || new Response('Offline clock not ready', {status: 503});
        } finally {
            clearTimeout(timeout);
        }
    })());
});
