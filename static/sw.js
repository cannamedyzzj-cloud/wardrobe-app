// Samantha的衣橱 v1.2.1 — Service Worker
// 只缓存公共静态资源，不缓存任何用户私有数据
const CACHE_NAME = 'samantha-static-v1.2.1';

const STATIC_ASSETS = [
  '/static/manifest.json',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
];

// 所有登录后的页面、API、照片 — Network Only（绝不缓存）
const NETWORK_ONLY_PATTERNS = [
  /^\/$/,
  /^\/garments/,
  /^\/manage/,
  /^\/admin/,
  /^\/find/,
  /^\/account/,
  /^\/wardrobes/,
  /^\/locations/,
  /^\/api\//,
  /^\/media\//,
  /^\/uploads\//,
  /^\/export/,
  /^\/login/,
  /^\/logout/,
  /^\/healthz/,
  /^\/smart/,
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
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const request = event.request;

  // 非 GET 请求直接放行
  if (request.method !== 'GET') return;

  // 用户数据页面、API、重定向响应：Network Only
  if (isNetworkOnly(request.url)) {
    event.respondWith(fetch(request));
    return;
  }

  // 只缓存明确列出的静态资源
  event.respondWith(
    caches.match(request).then(cached => {
      if (cached) return cached;
      return fetch(request).then(response => {
        // 只缓存成功且非重定向的响应
        if (response.ok && response.type === 'basic' && !response.redirected) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
        }
        return response;
      });
    })
  );
});
