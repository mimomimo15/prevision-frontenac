// Recalcul dans le navigateur des modèles v4 (journalier recalé) et horaire (48 h), avec les mesures en direct du SHC.
// Copie fidèle de prevision_frontenac.py (v4_features, forecast_v4, forecast_hourly) : analyse/parite_js.py vérifie
// que les deux donnent les mêmes valeurs. Heures « locales » = UTC−5 fixe, comme dans tout le site.
// hr = { fr, pc, sa, var } : Map(numéro d'heure locale → niveau au zéro des cartes), numéro = floor(ms UTC / 3 600 000) − 5.
// D = numéro du jour local de la dernière mesure (floor(numéro d'heure / 24)), h = heures de ce jour déjà mesurées (1..24).
// base = niveaux v3 émis avec le jour D−1 pour D, D+1, ... (fournis par data.json : v4_base).
(function (root) {
  const TZ = -5, DATUM = { fr: 0, pc: 20.35, sa: 21.34, var: 0 }, CODES = ['fr', 'pc', 'sa', 'var'];
  const STATIONS = { fr: '5cebf1e03d0f4a073c4bbdee', pc: '5cebf1e43d0f4a073c4bc480', sa: '5cebf1e43d0f4a073c4bc478', var: '5cebf1e03d0f4a073c4bbe04' };
  const isIce = day => { const m = new Date(day * 864e5).getUTCMonth() + 1; return (m === 12 || m <= 3) ? 1 : 0; };
  const dayStr = day => new Date(day * 864e5).toISOString().slice(0, 10);
  const dayNum = str => Math.round(Date.parse(str + 'T00:00:00Z') / 864e5);

  function features(hr, D, h, pbase, pToday) {
    const t = D * 24 + h;                                             // première heure pas encore mesurée
    const win = (c, a, b) => { let s = 0, n = 0; for (let i = b + 1; i <= a; i++) { const v = hr[c].get(t - i); if (v != null) { s += v; n++; } }
      return n >= Math.max(1, Math.floor(0.66 * (a - b))) ? s / n + DATUM[c] : null; };
    const f = { pbase: pbase, p_today: pToday, ice: isIce(D) };
    for (const c of CODES) {
      const r3 = win(c, 3, 0), r24 = win(c, 24, 0), old = win(c, 9, 6);
      if (r3 == null || r24 == null || old == null) return null;
      f[c + '_r3'] = r3; f[c + '_r24'] = r24; f[c + '_sl6'] = r3 - old;
    }
    if (h >= 2) { let s = 0, n = 0; for (let i = 0; i < h; i++) { const v = hr.fr.get(D * 24 + i); if (v != null) { s += v; n++; } }
      if (n < h - 1) return null; f.fr_part = s / n; }
    else f.fr_part = f.fr_r3;
    return f;
  }
  const dot = (coef, names, f) => { let s = coef[0]; for (let i = 0; i < names.length; i++) s += coef[i + 1] * f[names[i]]; return s; };

  // { décalage du jour visé: { level, margin } }
  function forecastV4(V4, hr, D, h, base) {
    const out = {}, set = V4 && V4.h[String(h)];
    if (!set || !base || !base.length) return out;
    for (const tg of Object.keys(set)) {
      const k = +tg; if (k >= base.length) continue;
      const f = features(hr, D, h, base[k], base[0]); if (!f) continue;
      out[k] = { level: dot(set[tg].coef, V4.features, f), margin: isIce(D + k) ? set[tg].p90_ice : set[tg].p90_free };
    }
    return out;
  }

  // [{ t: ms UTC de l'heure visée, v: niveau, q: quantiles de l'erreur }] pour L = 1..48
  function forecastHourly(VH, hr, D, h, base) {
    const out = []; if (!VH || !base || base.length < 3) return out;
    const f0 = features(hr, D, h, base[0], base[0]), t0 = D * 24 + h, g = i => hr.fr.get(t0 - i);
    if (!f0 || g(1) == null || g(3) == null) return out;
    f0.fr_r1 = g(1); f0.fr_sl2 = g(1) - g(3);
    for (let L = 1; L <= 48; L++) {
      const c = VH.leads[String(L)], tt = t0 + L - 1, k = Math.floor(tt / 24) - D, lag = hr.fr.get(tt - (L <= 24 ? 24 : 48));
      if (!c || k >= base.length || lag == null) break;
      const a = (tt % 24) * 2 * Math.PI / 24;
      const f = Object.assign({}, f0, { pday: base[k], p_today: base[0], lag24: lag, c24: Math.cos(a), s24: Math.sin(a), c12: Math.cos(2 * a), s12: Math.sin(2 * a) });
      out.push({ t: (tt - TZ) * 3600e3, v: dot(c.coef, VH.features, f), q: isIce(Math.floor(tt / 24)) ? c.q_ice : c.q_free });
    }
    return out;
  }

  // Séries horaires IWLS (points { eventDate, value }) → Map(numéro d'heure locale → niveau)
  const toMap = pts => { const m = new Map(); for (const p of pts) m.set(Math.floor(Date.parse(p.eventDate) / 3600e3) + TZ, p.value); return m; };

  // Met à jour l'objet data.json `d` avec les mesures en direct. Renvoie true si la prévision a été recalculée.
  // Ne fait rien si le robot a déjà utilisé la dernière heure mesurée, si la dernière mesure a plus de 3 heures,
  // ou si la base v3 fournie n'est pas celle du bon jour (dans ce cas la prévision du robot reste affichée).
  async function refresh(d, opts) {
    opts = opts || {};
    if (!d || !d.v4_base || !d.v4_base.levels || !d.forecast) return false;
    const now = opts.now || Date.now(), fetchJson = opts.fetchJson || (async (u, signal) => (await fetch(u, { signal })).json());
    const robotLast = d.v4 && d.v4.last_obs ? Math.floor(Date.parse(d.v4.last_obs + ':00Z') / 3600e3) : -Infinity;     // déjà en heure locale
    if (Math.floor(now / 3600e3) + TZ <= robotLast) return false;                                                      // rien de plus récent à attendre
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null, iso = t => new Date(t).toISOString().slice(0, 19) + 'Z';
    const url = c => `https://api-iwls.dfo-mpo.gc.ca/api/v1/stations/${STATIONS[c]}/data?time-series-code=wlo&from=${iso(now - 60 * 3600e3)}&to=${iso(now)}&resolution=SIXTY_MINUTES`;
    const timer = setTimeout(() => ctrl && ctrl.abort(), opts.timeout || 6000);
    let series, V4, VH;
    try {
      [series, V4, VH] = await Promise.all([Promise.all(CODES.map(c => fetchJson(url(c), ctrl && ctrl.signal))),
        fetchJson('coefs_v4.json', ctrl && ctrl.signal), fetchJson('coefs_horaire.json', ctrl && ctrl.signal)]);
    } finally { clearTimeout(timer); }
    const hr = {}; CODES.forEach((c, i) => { hr[c] = toMap(series[i]); });
    if (!hr.fr.size) return false;
    const tl = Math.max(...hr.fr.keys()), D = Math.floor(tl / 24), h = tl % 24 + 1;
    if (tl <= robotLast || Math.floor(now / 3600e3) + TZ - tl > 3) return false;
    if (dayNum(d.v4_base.day) !== D) return false;
    const base = d.v4_base.levels, v4 = forecastV4(V4, hr, D, h, base), clock = (Math.floor(now / 3600e3) + TZ) % 24, done = [];
    for (const f of d.forecast) {
      const k = dayNum(f.date) - D;
      if (v4[k] && !(k === 3 && clock >= 18)) { f.level = Math.round(v4[k].level * 1000) / 1000; f.margin = v4[k].margin; done.push(k); }
    }
    if (!done.length) return false;
    const hf = forecastHourly(VH, hr, D, h, base);
    if (hf.length) { d.hourly_fc = hf.map(p => ({ t: iso(p.t), v: Math.round(p.v * 1000) / 1000, q: p.q })); d.hourly_qp = VH.qp; }
    d.v4 = { day: dayStr(D), hours: h, last_obs: dayStr(D) + 'T' + String(tl % 24).padStart(2, '0') + ':00', targets: done, live: true };
    return true;
  }

  const api = { features, forecastV4, forecastHourly, toMap, refresh, isIce, dayNum, dayStr };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Modele = api;
})(typeof self !== 'undefined' ? self : this);
