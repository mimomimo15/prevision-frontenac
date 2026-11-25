"""Novembre 2026, aux instants réels d'émission : prévision publiée (archive) contre v4 rejoué au même instant."""
import csv, json, numpy as np
import fit_v4 as Fv
from donnees import *
V = json.load(open(os.path.join(ROOT, "coefs_v4.json"))); d = Fv.d
acc = {}; det = []
for r in csv.DictReader(open(os.path.join(ROOT, "docs", "forecast_archive_v3.csv" if os.path.exists(os.path.join(ROOT, "docs", "forecast_archive_v3.csv")) else "forecast_archive.csv"))):
    t = dt.datetime.strptime(r["issued_utc"], "%Y-%m-%dT%H:%MZ") - dt.timedelta(hours=5)
    if t.date() < dt.date(2026, 11, 11): continue
    i = (t.date() - D0).days; td = dt.date.fromisoformat(r["target_date"]); tgt = (td - t.date()).days; h = t.hour + 1; j = (td - D0).days
    if td >= dt.date.today() or str(tgt) not in V["h"][str(h)] or tgt == 0 or np.isnan(d["fr"][j]): continue
    p = Fv.pred(h, tgt, np.array(V["h"][str(h)][str(tgt)]["coef"]))[i]
    if np.isnan(p): continue
    g = (tgt, "avant 18 h" if t.hour < 18 else "après 18 h"); acc.setdefault(g, []).append((d["fr"][j] - float(r["level_zc"]), d["fr"][j] - p))
    if tgt == 1 and t.hour >= 18: det.append((t, d["fr"][j], float(r["level_zc"]), p))
for g, L in sorted(acc.items()):
    a = np.array(L); print(f"D+{g[0]} {g[1]} n={len(a)}  publié RMSE {100 * np.sqrt((a[:, 0] ** 2).mean()):.1f} cm (biais {100 * a[:, 0].mean():+.1f})   v4 {100 * np.sqrt((a[:, 1] ** 2).mean()):.1f} cm (biais {100 * a[:, 1].mean():+.1f})")
print("détail demain, soir :"); [print("  ", t.strftime("%m-%d %H:%M"), "obs %+.3f publié %+.3f v4 %+.3f" % (o, a, b)) for t, o, a, b in det]
