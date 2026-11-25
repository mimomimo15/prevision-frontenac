"""L'émulation du site (test_v4.site) reproduit-elle les prévisions réellement publiées (docs/forecast_archive.csv) ?"""
import csv, numpy as np, functools
import test_v4 as T
from donnees import *
T.part = functools.lru_cache(None)(T.part)
rows = {}
for r in csv.DictReader(open(os.path.join(ROOT, "docs", "forecast_archive.csv"))):
    t = dt.datetime.strptime(r["issued_utc"], "%Y-%m-%dT%H:%MZ") - dt.timedelta(hours=5)
    rows[(t, r["target_date"])] = float(r["level_zc"])
cache = {}
out = {}
for (t, td), v in sorted(rows.items()):
    i = (t.date() - D0).days; tgt = (dt.date.fromisoformat(td) - t.date()).days
    if tgt not in (1, 2) or t.hour < 3 or t.date() < dt.date(2026, 11, 11): continue
    key = (t.hour, tgt)
    if key not in cache: cache[key] = T.site(t.hour, tgt)
    e = cache[key][i]
    if not np.isnan(e): out.setdefault(("avant 18 h" if t.hour < 18 else "après 18 h", tgt), []).append((t, v, e))
for k, L in sorted(out.items()):
    dif = np.array([a - b for _, a, b in L]); print(k, "n=%d  écart moyen %+.1f mm, RMS %.1f mm, max %.1f mm" % (len(L), 1000 * dif.mean(), 1000 * np.sqrt((dif ** 2).mean()), 1000 * np.abs(dif).max()))
    worst = sorted(L, key=lambda x: -abs(x[1] - x[2]))[:3]; print("   pires :", [(t.strftime("%m-%d %Hh%M"), round(a, 3), round(float(b), 3)) for t, a, b in worst])
