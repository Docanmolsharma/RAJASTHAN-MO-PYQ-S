const CACHE='cortex-v17';
const ASSETS=['./','./index.html','./manifest.webmanifest','./cortex-icon.svg','./cortex-emblem.svg','./cortex-splash.svg'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('cortex-')&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url);
  if(url.origin!==self.location.origin)return;
  const isAppPage=event.request.mode==='navigate'||url.pathname.endsWith('/index.html')||url.pathname.endsWith('/');
  const isAppAsset=isAppPage||/\.(css|js|svg|webmanifest|png|jpg|jpeg|webp|ico)$/.test(url.pathname);
  if(!isAppAsset)return;
  event.respondWith((async()=>{
    const cache=await caches.open(CACHE);
    try{
      const response=await fetch(event.request,{cache:'no-cache'});
      if(response&&response.ok)cache.put(event.request,response.clone()).catch(()=>{});
      return response;
    }catch(error){
      const cached=await cache.match(event.request)||await cache.match('./index.html');
      if(cached)return cached;
      throw error;
    }
  })());
});