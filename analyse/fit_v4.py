"""Modèle v4 (ancré sur les dernières heures mesurées) : évaluation par année, puis coefficients (coefs_v4.json).
h = nombre d'heures du jour D déjà mesurées (1..24) ; cible = moyenne journalière du jour D+tgt.
Le site, à l'heure d'horloge c, dispose de h = c+1 heures (vérifié sur l'archive : test_emulation.py)."""
import json, sys, functools
import numpy as np
import test_v4 as T
from donnees import *
T.roll = functools.lru_cache(None)(T.roll); T.part = functools.lru_cache(None)(T.part)
d, P = T.d, T.P
NAMES = ["pbase", "p_today", "ice", "fr_r3", "fr_r24", "fr_sl6", "fr_part", "pc_r3", "pc_r24", "sa_r3", "sa_r24", "pc_sl6", "sa_sl6", "var_r3", "var_sl6"]
@functools.lru_cache(None)
def X_(h, tgt):
    X = {"pbase": sh(P[tgt + 1], 1), "p_today": sh(P[1], 1), "ice": ICE}
    for c in ("fr", "pc", "sa", "var"):
        X[c + "_r3"] = T.roll(c, h, 3, 0); X[c + "_r24"] = T.roll(c, h, 24, 0); X[c + "_sl6"] = X[c + "_r3"] - T.roll(c, h, 9, 6)
    X["fr_part"] = T.part("fr", h) if h >= 2 else X["fr_r3"]
    return np.column_stack([X[n] for n in NAMES])

def fit(h, tgt, mtr, pool=1):
    """coefficients [b0, b...] ajustés sur les jours mtr, en regroupant les heures h−pool..h+pool."""
    y = sh(d["fr"], -tgt); A = []; Y = []
    for hh in range(max(1, h - pool), min(24, h + pool) + 1):
        X = X_(hh, tgt); ok = ~np.isnan(X).any(axis=1) & ~np.isnan(y) & mtr; A.append(X[ok]); Y.append(y[ok])
    A = np.vstack(A); Y = np.concatenate(Y); mu = A.mean(0); sd = A.std(0); sd[sd == 0] = 1
    Z = np.column_stack([np.ones(len(Y)), (A - mu) / sd]); b = np.linalg.lstsq(Z, Y, rcond=None)[0]
    coef = b[1:] / sd; return np.concatenate([[b[0] - np.sum(coef * mu)], coef])

def pred(h, tgt, b): return b[0] + X_(h, tgt) @ b[1:]

def site_pred(h, tgt):
    c = h - 1   # heure d'horloge correspondante
    if tgt == 0:
        if not (3 <= c < 18): return np.full(ND, np.nan)
        hb = T.INTRA[str(c)]; p1 = sh(P[1], 1); pa = T.part("fr", h); s = np.full(ND, np.nan); icJ = sh(ICE, 1)
        for ice, key in ((0, "free"), (1, "ice")):
            cc = hb[key if key in hb else "free"]["today"]["coef"]; v = cc[0] + cc[1] * pa + cc[2] * p1; s[icJ == ice] = v[icJ == ice]
        return s
    if c < 3: return sh(P[tgt + 1], 1)
    return site_h(h, tgt)

@functools.lru_cache(None)
def site_h(h, tgt):
    """T.site avec h heures disponibles (au lieu de h−1)."""
    c = h - 1
    if c < 18:
        p1 = sh(P[1], 1); x = T.part("fr", h) - p1; out = np.full(ND, np.nan); icJ = sh(ICE, 1); hb = T.INTRA[str(min(max(c, 3), 17))]
        for ice, key in ((0, "free"), (1, "ice")):
            cc = hb[key if key in hb else "free"][f"k{tgt + 1}"]["coef"]; v = sh(P[tgt + 1], 1) + cc[0] + cc[1] * x; out[icJ == ice] = v[icJ == ice]
        return out
    return T.site(h, tgt)     # T.site(h) utilise les heures [0, h)

GROUPS = {"horloge 0-5 h": range(1, 7), "6-11 h": range(7, 13), "12-17 h": range(13, 19), "18-23 h": range(19, 25)}
def evalue(train_max, test_years, pool):
    for tgt in (0, 1, 2, 3):
        y = sh(d["fr"], -tgt); yr = sh(YEAR.astype(float), -tgt); icet = sh(ICE, -tgt); tr = (yr >= 2020) & (yr <= train_max)
        print(f"-- cible D+{tgt} : site → v4 (cm ; hors glace | glace)")
        for g, hs in GROUPS.items():
            line = f"   {g:14s}"
            for Y in test_years:
                acc = {}
                for h in hs:
                    s = site_pred(h, tgt); v = pred(h, tgt, fit(h, tgt, tr, pool)); ok = ~np.isnan(s) & ~np.isnan(v) & ~np.isnan(y) & (yr == Y)
                    for ice in (0, 1):
                        m = ok & (icet == ice)
                        if m.sum(): acc.setdefault(ice, []).append((np.mean((y - s)[m] ** 2), np.mean((y - v)[m] ** 2), m.sum()))
                cell = []
                for ice in (0, 1):
                    if ice in acc: a = np.array(acc[ice]); cell.append(f"{100 * np.sqrt(a[:, 0].mean()):.1f}→{100 * np.sqrt(a[:, 1].mean()):.1f}")
                    else: cell.append("–")
                line += f"  {Y}: {cell[0]:>10s} | {cell[1]:>10s}"
            print(line, flush=True)

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "eval"
    if mode == "eval":
        for pool in (0, 1):
            print(f"\n===== ajusté 2020-2023, regroupement ±{pool} h"); evalue(2023, (2024, 2025, 2026), pool)
        print("\n===== ajusté 2020-2025, regroupement ±1 h"); evalue(2025, (2026,), 1)
    if mode == "export":
        TG = lambda h: [t for t in (0, 1, 2, 3) if not (t == 0 and h == 24) and not (t == 3 and h > 18)]
        out = {"note": "v4 : prévision v3 du dernier jour complet (D−1) recalée sur les dernières heures mesurées. h = nombre d'heures du jour D mesurées ; clés = jour visé D+k. "
                       "Ajusté sur 2020-2026 (heures h−1..h+1 regroupées) ; marges p90 = erreurs hors échantillon (une année retirée à la fois). Niveaux en m ; Pointe-Claire et Sainte-Anne en IGLD85.",
               "features": NAMES, "h": {}}
        for h in range(1, 25):
            out["h"][str(h)] = {}
            for tgt in TG(h):
                y = sh(d["fr"], -tgt); yr = sh(YEAR.astype(float), -tgt); icet = sh(ICE, -tgt)
                res = np.full(ND, np.nan)
                for Y in range(2021, 2027):
                    b = fit(h, tgt, (yr >= 2020) & (yr != Y)); m = yr == Y; res[m] = (y - pred(h, tgt, b))[m]
                b = fit(h, tgt, yr >= 2020)
                q = lambda ice: round(float(np.nanquantile(np.abs(res[icet == ice]), 0.9)), 3)
                out["h"][str(h)][str(tgt)] = {"coef": [round(float(x), 6) for x in b], "p90_free": q(0), "p90_ice": q(1), "rmse_free": round(rmse(res[icet == 0]), 4), "rmse_ice": round(rmse(res[icet == 1]), 4)}
            print(h, {t: (v["rmse_free"], v["p90_free"]) for t, v in out["h"][str(h)].items()}, flush=True)
        json.dump(out, open(os.path.join(ROOT, "coefs_v4.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    if mode == "parite":
        # le code du site (prevision_frontenac.forecast_v4, Python pur) donne-t-il la même valeur que l'analyse (numpy) ?
        sys.path.insert(0, ROOT); import prevision_frontenac as pf, random
        V = json.load(open(os.path.join(ROOT, "coefs_v4.json"))); random.seed(1); worst = 0; n = 0
        raw = {c: T.H[c] - DATUM[c] for c in T.H}
        for _ in range(400):
            i = random.randrange(600, ND - 5); h = random.randrange(1, 25)
            hr = {c: {dt.datetime.combine(DATES[i - 2], dt.time()) + dt.timedelta(hours=k): float(v) for k, v in enumerate(raw[c][i - 2:i + 1].reshape(-1)) if not np.isnan(v) and k < 48 + h} for c in raw}
            base = [P[k][i - 1] for k in range(1, 8)]
            if any(np.isnan(base)): continue
            got = pf.forecast_v4(hr, DATES[i], h, [float(x) for x in base])
            for tg, c in V["h"][str(h)].items():
                ref = pred(h, int(tg), np.array(c["coef"]))[i]
                if np.isnan(ref): assert int(tg) not in got, (i, h, tg); continue
                assert int(tg) in got, (DATES[i], h, tg); worst = max(worst, abs(got[int(tg)][0] - ref)); n += 1
        print(f"parité : {n} prévisions comparées, écart maximal {1000 * worst:.4f} mm")
    if mode == "saut":
        # stabilité d'une exécution à la suivante : variation moyenne de la prévision de demain entre deux heures consécutives (2026)
        V = json.load(open(os.path.join(ROOT, "coefs_v4.json"))); m = YEAR == 2026
        for tgt in (1, 2):
            a = [np.nanmean(np.abs(pred(h + 1, tgt, np.array(V["h"][str(h + 1)][str(tgt)]["coef"])) - pred(h, tgt, np.array(V["h"][str(h)][str(tgt)]["coef"])))[m]) for h in range(1, 24)]
            s = [np.nanmean(np.abs(site_pred(h + 1, tgt) - site_pred(h, tgt))[m]) for h in range(1, 24)]
            print(f"D+{tgt} : variation moyenne d'une heure à l'autre  v4 {1000 * np.mean(a):.1f} mm (max {1000 * np.max(a):.1f})   site {1000 * np.mean(s):.1f} mm (max {1000 * np.max(s):.1f}, passage de 18 h)")
