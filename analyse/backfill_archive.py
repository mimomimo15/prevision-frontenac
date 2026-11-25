"""Une seule fois (25 nov. 2026) : garde l'archive publiée jusqu'ici dans docs/forecast_archive_v3.csv, puis remplace dans
docs/forecast_archive.csv les prévisions d'aujourd'hui à J+3 par le rejeu v4 au même instant d'émission (depuis le 11 nov.),
pour que la combinaison modèle + SPINE soit pondérée sur le modèle réellement en ligne."""
import csv, json, shutil, numpy as np
import fit_v4 as Fv
from donnees import *
A = os.path.join(ROOT, "docs", "forecast_archive.csv"); B = os.path.join(ROOT, "docs", "forecast_archive_v3.csv")
assert not os.path.exists(B), "déjà fait"
shutil.copyfile(A, B)
V = json.load(open(os.path.join(ROOT, "coefs_v4.json"))); rows = list(csv.reader(open(A, newline="", encoding="utf-8"))); n = 0
for r in rows[1:]:
    t = dt.datetime.strptime(r[0], "%Y-%m-%dT%H:%MZ") - dt.timedelta(hours=5)
    if t.date() < dt.date(2026, 11, 11): continue
    tgt = (dt.date.fromisoformat(r[1]) - t.date()).days; h = t.hour + 1
    if str(tgt) not in V["h"][str(h)] or (tgt == 3 and t.hour >= 18): continue
    p = Fv.pred(h, tgt, np.array(V["h"][str(h)][str(tgt)]["coef"]))[(t.date() - D0).days]
    if not np.isnan(p): r[2] = f"{p:.3f}"; n += 1
with open(A, "w", newline="", encoding="utf-8") as f: csv.writer(f).writerows(rows)
print(n, "lignes remplacées sur", len(rows) - 1)
