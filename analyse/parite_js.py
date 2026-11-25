"""Le calcul du navigateur (docs/modele.js) donne-t-il les mêmes valeurs que le code du site (prevision_frontenac.py) ?
Tire des instants au hasard dans l'historique, calcule v4 et l'horaire en Python, puis les fait recalculer par Node."""
import json, random, subprocess, sys, tempfile
import numpy as np
from donnees import *
sys.path.insert(0, ROOT); import prevision_frontenac as pf
H, d = charger(); P = v3_pred(v3_feats(H, d)); raw = {c: H[c] - DATUM[c] for c in H}
EPOCH = dt.date(1970, 1, 1); random.seed(3); cases = []
while len(cases) < 300:
    i = random.randrange(700, ND - 6); h = random.randrange(1, 25); base = [float(P[k][i - 1]) for k in range(1, 8)]
    if any(np.isnan(base)): continue
    t00 = dt.datetime.combine(DATES[i - 3], dt.time()); D = (DATES[i] - EPOCH).days
    hr = {c: {t00 + dt.timedelta(hours=k): float(v) for k, v in enumerate(raw[c][i - 3:i + 1].reshape(-1)) if not np.isnan(v) and k < 72 + h} for c in raw}
    v4 = pf.forecast_v4(hr, DATES[i], h, base); hf = pf.forecast_hourly(hr, DATES[i], h, base)
    num = lambda t: (t.date() - EPOCH).days * 24 + t.hour
    cases.append({"D": D, "h": h, "base": base, "hr": {c: [[num(t), v] for t, v in hr[c].items()] for c in hr},
                  "v4": {str(k): list(v) for k, v in v4.items()}, "hf": [[num(t), lvl, q[0]] for t, lvl, q in hf]})
tmp = os.path.join(tempfile.gettempdir(), "parite_js_cases.json"); json.dump(cases, open(tmp, "w"))
js = r"""
const M = require(process.argv[2]), fs = require('fs');
const V4 = JSON.parse(fs.readFileSync(process.argv[3])), VH = JSON.parse(fs.readFileSync(process.argv[4])), cases = JSON.parse(fs.readFileSync(process.argv[5]));
let worst = 0, n = 0;
for (const c of cases) {
  const hr = {}; for (const k of Object.keys(c.hr)) hr[k] = new Map(c.hr[k]);
  const v4 = M.forecastV4(V4, hr, c.D, c.h, c.base), hf = M.forecastHourly(VH, hr, c.D, c.h, c.base);
  if (Object.keys(v4).length !== Object.keys(c.v4).length || hf.length !== c.hf.length) throw new Error('longueurs différentes ' + c.D + ' ' + c.h);
  for (const k of Object.keys(c.v4)) { worst = Math.max(worst, Math.abs(v4[k].level - c.v4[k][0])); if (v4[k].margin !== c.v4[k][1]) throw new Error('marge'); n++; }
  c.hf.forEach((r, i) => { if (hf[i].t !== (r[0] + 5) * 3600e3 || hf[i].q[0] !== r[2]) throw new Error('heure ou quantiles'); worst = Math.max(worst, Math.abs(hf[i].v - r[1])); n++; });
}
console.log('parité navigateur : ' + n + ' valeurs comparées, écart maximal ' + (1000 * worst).toExponential(2) + ' mm');
"""
jsf = os.path.join(tempfile.gettempdir(), "parite_js.js"); open(jsf, "w").write(js)
subprocess.run(["node", jsf, os.path.join(ROOT, "docs", "modele.js"), os.path.join(ROOT, "coefs_v4.json"), os.path.join(ROOT, "coefs_horaire.json"), tmp], check=True)
