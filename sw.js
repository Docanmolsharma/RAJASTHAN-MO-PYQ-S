const CACHE='cortex-v13';
const ASSETS=['./','./index.html','./manifest.webmanifest','./cortex-icon.svg','./cortex-emblem.svg'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET') return;
  const isPage=e.request.mode==='navigate'||new URL(e.request.url).pathname.endsWith('/index.html')||new URL(e.request.url).pathname.endsWith('/');
  if(isPage){
    e.respondWith(fetch(e.request).then(response=>{
      if(response&&response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(e.request,copy));}
      return response;
    }).catch(()=>caches.match(e.request).then(cached=>cached||caches.match('./index.html'))));
    return;
  }
  e.respondWith(caches.match(e.request).then(cached=>cached||fetch(e.request).then(response=>{
    if(response&&response.ok){const copy=response.clone();caches.open(CACHE).then(cache=>cache.put(e.request,copy));}
    return response;
  })));
});
