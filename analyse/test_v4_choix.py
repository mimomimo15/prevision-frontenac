"""Choix des variables du modèle v4 : RMSE test 2024-2025 (ajusté 2020-2023), moyenne sur les heures d'émission."""
import numpy as np, functools
import test_v4 as T
from donnees import *
T.roll = functools.lru_cache(None)(T.roll); T.part = functools.lru_cache(None)(T.part)
d, P, f = T.d, T.P, T.f
def feats(h, tgt, sets):
    X = {"pbase": sh(P[tgt + 1], 1), "p_today": sh(P[1], 1), "ice": ICE}
    for c in ("fr", "pc", "sa", "var"):
        X[c + "_r3"] = T.roll(c, h, 3, 0); X[c + "_r24"] = T.roll(c, h, 24, 0); X[c + "_sl6"] = X[c + "_r3"] - T.roll(c, h, 9, 6); X[c + "_r1"] = T.roll(c, h, 1, 0)
        X[c + "_i"] = X[c + "_r3"] * ICE
    X["fr_part"] = T.part("fr", h) if h >= 2 else X["fr_r3"]
    return np.column_stack([X[n] for n in sets])
S1 = ["pbase", "p_today", "ice", "fr_r3", "fr_r24", "fr_sl6", "fr_part"]
S2 = S1 + ["pc_r3", "pc_r24", "sa_r3", "sa_r24"]
S3 = S2 + ["pc_sl6", "sa_sl6", "var_r3", "var_sl6"]
S4 = S3 + ["fr_i", "pc_i", "sa_i"]
S5 = ["pbase", "p_today", "ice", "fr_r3", "fr_r24", "fr_part", "pc_r3", "pc_r24", "sa_r3", "sa_r24", "pc_i", "sa_i", "fr_i"]
SETS = {"S1": S1, "S2": S2, "S3": S3, "S4": S4, "S5": S5}
GROUPS = {"0-5 h": range(0, 6), "6-11 h": range(6, 12), "12-17 h": range(12, 18), "18-23 h": range(18, 24)}
for tgt in (0, 1, 2, 3):
    y = sh(d["fr"], -tgt); yr = sh(YEAR.astype(float), -tgt); icet = sh(ICE, -tgt)
    tr = (yr >= 2020) & (yr <= 2023); te = (yr >= 2024) & (yr <= 2025)
    print(f"\n== cible D+{tgt} (hors glace/glace, cm)")
    for gname, hs in GROUPS.items():
        acc = {}
        for h in hs:
            if tgt == 0 and h < 3: continue
            if tgt == 0 and h >= 18: s = np.full(ND, np.nan)
            elif tgt == 0:
                hb = T.INTRA[str(h)]; p1 = sh(P[1], 1); pa = T.part("fr", h); s = np.full(ND, np.nan); icJ = sh(ICE, 1)
                for ice, key in ((0, "free"), (1, "ice")):
                    c = hb[key if key in hb else "free"]["today"]["coef"]; v = c[0] + c[1] * pa + c[2] * p1; s[icJ == ice] = v[icJ == ice]
            else: s = T.site(h, tgt) if h >= 3 else sh(P[tgt + 1], 1)
            preds = {"site": s}
            for name, cols in SETS.items():
                for lam in (0.0, 0.01):
                    preds[f"{name}{'r' if lam else ''}"] = T.ols(feats(h, tgt, cols), y, tr, lam)[0]
            base = [v for k, v in preds.items() if k != "site" or not (tgt == 0 and h >= 18)]
            common = ~np.isnan(y) & np.all([~np.isnan(v) for v in base], axis=0) & te
            for k, v in preds.items():
                for ice in (0, 1):
                    e = (y - v)[common & (icet == ice)]; acc.setdefault((k, ice), []).append(np.mean(e ** 2) if len(e) and not np.isnan(e).any() else np.nan)
        if acc: print(f"{gname:8s}", "  ".join(f"{k} {100 * np.sqrt(np.mean(acc[(k, 0)])):.1f}/{100 * np.sqrt(np.mean(acc[(k, 1)])):.1f}" for k in preds), flush=True)
