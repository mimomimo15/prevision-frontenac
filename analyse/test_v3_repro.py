"""Vérifie la reconstitution : le v3 publié (coefs_v3.json) rejoué sur les données rebâties."""
import numpy as np
from donnees import *
H, d = charger(); f = v3_feats(H, d); P = v3_pred(f)
for c in ("fr", "pc", "sa", "var", "br", "hull", "lan", "ri", "ms"): print(c, "jours valides", int(np.sum(~np.isnan(d[c]))), "premier", DATES[int(np.argmax(~np.isnan(d[c])))])
print("k : RMSE cm hors glace (date cible)  2020-23 | 2024-25 | 2026     persistance 2024-25")
for k in (1, 2, 3):
    y = sh(d["fr"], -k); e = y - P[k]; icet = sh(ICE, -k); yr = sh(YEAR.astype(float), -k)
    m = lambda a, b: (icet == 0) & (yr >= a) & (yr <= b)
    print(k, "%.1f | %.1f | %.1f    %.1f   n24-25=%d" % (100 * rmse(e[m(2020, 2023)]), 100 * rmse(e[m(2024, 2025)]), 100 * rmse(e[m(2026, 2026)]), 100 * rmse((y - d["fr"])[m(2024, 2025)]), int(np.sum(~np.isnan(e[m(2024, 2025)])))))
