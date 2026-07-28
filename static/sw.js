// 简化版 Service Worker - 离线缓存支持
const CACHE_NAME = 'wardrobe-v1';
const URLS_TO_CACHE = [
  '/',
  '/static/manifest.json',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(URLS_TO_CACHE))
  );
  self.skipWaiting();
});

self.addEventListener('fetch', event => {
  // 对上传的图片使用 network-first 策略
  if (event.request.url.includes('/uploads/')) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          const cloned = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, cloned));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }
  
  // 其他请求 network-first
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
