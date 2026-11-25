"""Modèle ancré sur l'heure d'émission (v4) contre le site actuel (v3 + ajustement intrajournalier), rejoué heure par heure.
Cible : moyenne journalière de demain (D+1) et d'après-demain (D+2), prévision émise le jour D à l'heure locale h."""
import json, sys
import numpy as np
from donnees import *
H, d = charger(); f = v3_feats(H, d); P = v3_pred(f)
INTRA = json.load(open(os.path.join(ROOT, "coefs_intraday.json")))["hours"]
V3 = json.load(open(os.path.join(ROOT, "coefs_v3.json")))["horizons"]
F = {c: H[c].reshape(-1) for c in H}
def roll(c, h, a, b):
    """moyenne des heures [t-a, t-b) avant l'émission t = (jour, h) ; au moins 2/3 des valeurs."""
    x = F[c]; out = np.full(ND, np.nan)
    for i in range(2, ND):
        t = i * 24 + h; w = x[t - a:t - b]; n = np.sum(~np.isnan(w))
        if n >= max(1, int(0.66 * (a - b))): out[i] = np.nanmean(w)
    return out
def part(c, h):
    out = np.full(ND, np.nan)
    for i in range(ND):
        w = H[c][i, :h]; n = np.sum(~np.isnan(w))
        if n >= max(h - 1, 1): out[i] = np.nanmean(w)
    return out

def site(h, tgt):
    """prévision du site actuel émise à l'heure h du jour D pour D+tgt (tgt = 1 ou 2), indexée par D."""
    if h < 18:
        p1 = sh(P[1], 1); x = part("fr", h) - p1; out = np.full(ND, np.nan); icJ = sh(ICE, 1)
        hb = INTRA[str(min(max(h, 3), 17))]
        for ice, key in ((0, "free"), (1, "ice")):
            cc = hb[key if key in hb else "free"][f"k{tgt + 1}"]["coef"]
            v = sh(P[tgt + 1], 1) + cc[0] + cc[1] * x; out[icJ == ice] = v[icJ == ice]
        return out
    # soir : le jour D partiel sert de jour J
    dd = dict(d); 
    for c in ("fr", "pc", "sa", "var"): dd[c] = np.where(np.isnan(part(c, h)), np.nan, part(c, h))
    for c in ("fr", "pc", "sa", "var"):   # les jours passés restent complets
        pass
    g = {}
    pfr, ppc, psa, pvar = dd["fr"], dd["pc"], dd["sa"], dd["var"]
    g.update(f)
    g.update({"pc_L": ppc, "sa_L": psa, "pcice": ppc * ICE, "saice": psa * ICE, "fr_iwls": pfr, "dpc": ppc - sh(d["pc"], 1), "dsa": psa - sh(d["sa"], 1), "dvar": pvar - sh(d["var"], 1), "dfr": pfr - sh(d["fr"], 1)})
    hh = V3[str(tgt)]
    return hh["coef"][0] + sum(b * g[n] for b, n in zip(hh["coef"][1:], hh["features"]))

def ols(X, y, mtr, lam=0.0):
    ok = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
    A = np.column_stack([np.ones(len(y)), X]); tr = ok & mtr
    mu = A[tr].mean(0); mu[0] = 0; sd = A[tr].std(0); sd[0] = 1; Z = (A - mu) / sd
    R = lam * np.eye(Z.shape[1]); R[0, 0] = 0
    b = np.linalg.lstsq(Z[tr].T @ Z[tr] + R * tr.sum(), Z[tr].T @ y[tr], rcond=None)[0]
    pred = np.full(len(y), np.nan); pred[ok] = Z[ok] @ b
    return pred, b / sd, ok

def feats(h, tgt, sets):
    X = {}
    X["pbase"] = sh(P[tgt + 1], 1)                      # v3 du dernier jour complet (D−1) pour la cible
    X["p_today"] = sh(P[1], 1)
    X["ice"] = ICE
    for c in ("fr", "pc", "sa", "var"):
        X[c + "_r3"] = roll(c, h, 3, 0); X[c + "_r24"] = roll(c, h, 24, 0); X[c + "_sl6"] = roll(c, h, 3, 0) - roll(c, h, 9, 6)
        X[c + "_sl12"] = roll(c, h, 3, 0) - roll(c, h, 15, 12); X[c + "_y"] = sh(d[c], 1)
    X["fr_part"] = part("fr", h) if h >= 2 else X["fr_r3"]
    X["dbr"] = sh(f["dbr"], 1); X["br"] = sh(f["br"], 1); X["dhull"] = sh(f["dhull"], 1); X["dlan"] = sh(f["dlan"], 1); X["dms_"] = sh(f["dms_"], 1)
    return np.column_stack([X[n] for n in sets]), sets

SETS = {
 "A fr seul": ["pbase", "p_today", "ice", "fr_r3", "fr_r24", "fr_sl6"],
 "B +pc,sa": ["pbase", "p_today", "ice", "fr_r3", "fr_r24", "fr_sl6", "pc_r3", "pc_r24", "pc_sl6", "sa_r3", "sa_r24", "sa_sl6"],
 "C +var,sl12": ["pbase", "p_today", "ice", "fr_r3", "fr_r24", "fr_sl6", "fr_sl12", "pc_r3", "pc_r24", "pc_sl6", "pc_sl12", "sa_r3", "sa_r24", "sa_sl6", "sa_sl12", "var_r3", "var_sl6", "fr_y", "pc_y", "sa_y"],
}
if __name__ == "__main__":
    for tgt in (1, 2):
        y = sh(d["fr"], -tgt); yr = sh(YEAR.astype(float), -tgt); icet = sh(ICE, -tgt)
        tr = (yr >= 2020) & (yr <= 2023); te = (yr >= 2024) & (yr <= 2025)
        print(f"\n===== cible D+{tgt} : RMSE cm, test 2024-2025 (ajusté 2020-2023) ; hors glace / glace")
        for h in (0, 3, 6, 9, 12, 15, 17, 18, 20, 22):
            s = site(h, tgt) if h >= 3 else sh(P[tgt + 1], 1)
            res = {}
            for name, cols in SETS.items():
                X, _ = feats(h, tgt, cols); pred, b, ok = ols(X, y, tr); res[name] = pred
            common = ~np.isnan(s) & ~np.isnan(y) & np.all([~np.isnan(v) for v in res.values()], axis=0) & te
            line = f"h={h:2d} n={int((common & (icet == 0)).sum())}/{int((common & (icet == 1)).sum())}  site {100 * rmse((y - s)[common & (icet == 0)]):.1f}/{100 * rmse((y - s)[common & (icet == 1)]):.1f}"
            for name, pred in res.items(): line += f" | {name} {100 * rmse((y - pred)[common & (icet == 0)]):.1f}/{100 * rmse((y - pred)[common & (icet == 1)]):.1f}"
            print(line, flush=True)
