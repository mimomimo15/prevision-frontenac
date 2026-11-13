// Service worker : l'enveloppe de l'app (pages, scripts, icônes) est mise en cache ; les données (data.json, API)
// passent d'abord par le réseau et retombent sur la dernière copie connue si le réseau manque.
const SHELL = 'shell-v2', DATA = 'data-v1';
const SHELL_FILES = ['./', './index.html', './journal.html', './validation.html', './validation_hist.json', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png', './icons/favicon.svg',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js',
  'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js'];
self.addEventListener('install', e => { e.waitUntil(caches.open(SHELL).then(c => Promise.all(SHELL_FILES.map(f => c.add(f).catch(() => {})))).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => ![SHELL, DATA].includes(k)).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (u.hostname === 'api.github.com') return;                       // journal privé : jamais mis en cache
  const isData = u.pathname.endsWith('data.json') || u.pathname.endsWith('validation.json') || u.hostname.includes('dfo-mpo.gc.ca') || u.hostname.includes('weather.gc.ca');
  if (isData) {                                                         // réseau d'abord, cache en secours
    e.respondWith(fetch(e.request).then(r => { if (r.ok) { const cp = r.clone(); caches.open(DATA).then(c => c.put(stripQuery(e.request), cp)); } return r; })
      .catch(() => caches.match(stripQuery(e.request))));
    return;
  }
  // enveloppe : réseau d'abord (pour avoir toujours la dernière version de la page), cache si hors ligne
  e.respondWith(fetch(e.request).then(r => { if (r.ok && (u.origin === location.origin || u.hostname === 'cdn.jsdelivr.net')) { const cp = r.clone(); caches.open(SHELL).then(c => c.put(e.request, cp)); } return r; })
    .catch(() => caches.match(e.request).then(m => m || caches.match('./index.html'))));
});
function stripQuery(req) { const u = new URL(req.url); u.search = ''; return new Request(u.toString(), { headers: req.headers }); }
