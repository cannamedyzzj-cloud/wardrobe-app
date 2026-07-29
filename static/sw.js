// Samantha的衣橱 v1.1.0 — Service Worker
// 只缓存公共静态资源，不缓存任何用户私有数据
const CACHE_NAME = 'samantha-static-v1.1.0';

const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
];

// 不缓存的路径（Network Only）
const NETWORK_ONLY_PATTERNS = [
  /^\/$/,
  /^\/garments/,
  /^\/manage/,
  /^\/find$/,
  /^\/api\//,
  /^\/media\//,
  /^\/uploads\//,
  /^\/export$/,
  /^\/login$/,
  /^\/logout$/,
  /^\/healthz$/,
];

function isNetworkOnly(url) {
  const path = new URL(url).pathname;
  return NETWORK_ONLY_PATTERNS.some(p => p.test(path));
}

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  // 清理旧版本缓存
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', event => {
  // 非 GET 请求直接放行
  if (event.request.method !== 'GET') return;

  // 用户数据页面和 API：Network Only（不缓存）
  if (isNetworkOnly(event.request.url)) {
    event.respondWith(fetch(event.request));
    return;
  }

  // 静态资源：Cache First
  event.respondWith(
    caches.match(event.request).then(cached =>
      cached || fetch(event.request).then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
    )
  );
});
