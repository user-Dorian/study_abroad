/**
 * Service Worker - 缓存核心静态资源
 * 提升二次访问加载速度，支持离线访问
 */

const CACHE_NAME = 'rag-frontend-v1';

// 需要缓存的核心资源
const CORE_ASSETS = [
  // CSS资源
  '/frontend/static/css/app.min.css',

  // 共享CSS资源
  '/frontend/shared/css/base.css',
  '/frontend/shared/css/components.css',
  '/frontend/shared/css/layout.css',

  // 共享JS资源
  '/frontend/shared/js/api-client.js',
  '/frontend/shared/js/ui-utils.js',

  // 客户端页面
  '/client/static/index.html',

  // 顾问端页面
  '/consultant/static/index.html'
];

/**
 * Service Worker安装事件
 * 缓存核心静态资源
 */
self.addEventListener('install', event => {
  console.log('[Service Worker] 安装中...');
  
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[Service Worker] 缓存核心资源');
        return cache.addAll(CORE_ASSETS);
      })
      .then(() => {
        console.log('[Service Worker] 核心资源缓存完成');
        // 立即激活
        return self.skipWaiting();
      })
      .catch(error => {
        console.error('[Service Worker] 缓存失败:', error);
      })
  );
});

/**
 * Service Worker激活事件
 * 清理旧缓存
 */
self.addEventListener('activate', event => {
  console.log('[Service Worker] 激活中...');
  
  event.waitUntil(
    caches.keys()
      .then(cacheNames => {
        return Promise.all(
          cacheNames
            .filter(cacheName => cacheName !== CACHE_NAME)
            .map(cacheName => {
              console.log('[Service Worker] 删除旧缓存:', cacheName);
              return caches.delete(cacheName);
            })
        );
      })
      .then(() => {
        console.log('[Service Worker] 激活完成');
        // 立即控制所有页面
        return self.clients.claim();
      })
  );
});

/**
 * Service Worker请求拦截
 * 缓存优先策略（Cache First）
 */
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);
  
  // 只缓存同源请求
  if (url.origin !== location.origin) {
    return;
  }
  
  // 只缓存GET请求
  if (request.method !== 'GET') {
    return;
  }
  
  // 排除API请求（动态内容不应缓存）
  if (url.pathname.startsWith('/api/') || 
      url.pathname.startsWith('/auth/') ||
      url.pathname.startsWith('/conversation/')) {
    return;
  }
  
  event.respondWith(
    caches.match(request)
      .then(cachedResponse => {
        // 如果缓存命中，直接返回
        if (cachedResponse) {
          console.log('[Service Worker] 缓存命中:', request.url);
          return cachedResponse;
        }
        
        // 否则从网络获取
        console.log('[Service Worker] 网络请求:', request.url);
        return fetch(request)
          .then(networkResponse => {
            // 检查响应是否有效
            if (!networkResponse || networkResponse.status !== 200) {
              return networkResponse;
            }
            
            // 克隆响应（因为响应流只能使用一次）
            const responseToCache = networkResponse.clone();
            
            // 将响应添加到缓存
            caches.open(CACHE_NAME)
              .then(cache => {
                cache.put(request, responseToCache);
              });
            
            return networkResponse;
          })
          .catch(error => {
            console.error('[Service Worker] 网络请求失败:', error);

            // 如果是HTML请求，返回离线页面
            if (request.headers.get('accept').includes('text/html')) {
              return caches.match('/client/static/index.html');
            }

            return new Response('Network Error', {
              status: 408,
              statusText: 'Request Timeout'
            });
          });
      })
  );
});

/**
 * 监听消息事件
 * 支持手动更新缓存
 */
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  
  if (event.data && event.data.type === 'CLEAR_CACHE') {
    caches.delete(CACHE_NAME)
      .then(() => {
        console.log('[Service Worker] 缓存已清除');
      });
  }
});

console.log('[Service Worker] 已加载');