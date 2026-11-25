"""Prévision horaire à Frontenac (48 h) : une régression par échéance L (heures après la dernière mesure).
t0 = première heure pas encore mesurée ; cible = niveau horaire à t0 + L − 1.
Modes : eval (test 2026, ajusté 2020-2025) · export (coefs_horaire.json : coefficients 2020-2026 + quantiles d'erreur hors échantillon) · parite."""
import json, sys
import numpy as np
from donnees import *
H, d = charger(); f = v3_feats(H, d); P = v3_pred(f)
F = {c: H[c].reshape(-1) for c in H}; NT = ND * 24
DAY = np.arange(NT) // 24; HOD = np.arange(NT) % 24
def rollf(c, a, b):
    """moyenne des heures [t-a, t-b) pour chaque t (au moins 2/3 des valeurs, min 1)."""
    x = F[c]; ok = (~np.isnan(x)).astype(float); v = np.where(np.isnan(x), 0, x)
    cs = np.concatenate([[0], np.cumsum(v)]); cn = np.concatenate([[0], np.cumsum(ok)]); out = np.full(NT, np.nan)
    t = np.arange(a, NT); s = cs[t - b] - cs[t - a]; n = cn[t - b] - cn[t - a]
    good = n >= max(1, int(0.66 * (a - b))); out[t[good]] = s[good] / n[good]
    return out
R = {}
for c in ("fr", "pc", "sa", "var"):
    R[c + "_r3"] = rollf(c, 3, 0); R[c + "_r24"] = rollf(c, 24, 0); R[c + "_sl6"] = R[c + "_r3"] - rollf(c, 9, 6)
R["fr_r1"] = rollf("fr", 1, 0); R["fr_sl2"] = R["fr_r1"] - rollf("fr", 3, 2)
ICEH = ICE[DAY]; YEARH = YEAR[DAY]
P1 = sh(P[1], 1); PK = {k: sh(P[k + 1], 1) for k in range(0, 4)}       # v3 émis avec D−1 pour D+k
NAMES = ["pday", "p_today", "ice", "fr_r1", "fr_sl2", "fr_r3", "fr_r24", "fr_sl6", "pc_r3", "pc_r24", "pc_sl6", "sa_r3", "sa_r24", "sa_sl6", "var_r3", "var_sl6", "lag24", "c24", "s24", "c12", "s12"]
LEADS = range(1, 49)
def XY(L):
    t0 = np.arange(48, NT - 49); tt = t0 + L - 1            # heure visée
    dD = DAY[t0 - 1]                                          # jour D de la dernière mesure
    k = DAY[tt] - dD                                          # décalage du jour visé (0..2)
    pday = np.choose(k, [PK[0][dD], PK[1][dD], PK[2][dD], PK[3][dD]])
    lag = F["fr"][np.where(L <= 24, tt - 24, tt - 48)]
    hod = HOD[tt] * 2 * np.pi / 24
    cols = {"pday": pday, "p_today": PK[0][dD], "ice": ICE[dD], "lag24": lag, "c24": np.cos(hod), "s24": np.sin(hod), "c12": np.cos(2 * hod), "s12": np.sin(2 * hod)}
    for n in NAMES:
        if n not in cols: cols[n] = R[n][t0]
    X = np.column_stack([cols[n] for n in NAMES]); y = F["fr"][tt]
    return X, y, YEAR[dD], ICE[DAY[tt]], R["fr_r1"][t0], t0
def fit(X, y, m):
    ok = m & ~np.isnan(X).any(axis=1) & ~np.isnan(y); A = X[ok]; mu = A.mean(0); sd = A.std(0); sd[sd == 0] = 1
    b = np.linalg.lstsq(np.column_stack([np.ones(ok.sum()), (A - mu) / sd]), y[ok], rcond=None)[0]; c = b[1:] / sd
    return np.concatenate([[b[0] - np.sum(c * mu)], c])
QP = [0.01, 0.025, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.975, 0.99]
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "eval"
    if mode == "eval":
        print("échéance : RMSE cm sur 2026 (ajusté 2020-2025), hors glace | glace :  dernier niveau mesuré → modèle horaire")
        for L in (1, 2, 3, 6, 9, 12, 18, 24, 30, 36, 42, 48):
            X, y, yr, icet, last, _ = XY(L); b = fit(X, y, (yr >= 2020) & (yr <= 2025)); p = b[0] + X @ b[1:]
            te = (yr == 2026) & ~np.isnan(p) & ~np.isnan(y) & ~np.isnan(last)
            print(f"  {L:2d} h   {100 * rmse((y - last)[te & (icet == 0)]):.1f} → {100 * rmse((y - p)[te & (icet == 0)]):.1f}   |   {100 * rmse((y - last)[te & (icet == 1)]):.1f} → {100 * rmse((y - p)[te & (icet == 1)]):.1f}", flush=True)
    if mode == "export":
        out = {"note": "Prévision horaire à Frontenac : une régression par échéance L (1..48 h après la dernière mesure). Ajusté sur 2020-2026. "
                       "q = quantiles (probabilités qp) de l'erreur mesuré − prévu, hors échantillon (une année retirée à la fois), hors glace et glace : servent au pourcentage de chances d'être dans une plage.",
               "features": NAMES, "qp": QP, "leads": {}}
        for L in LEADS:
            X, y, yr, icet, last, _ = XY(L); res = np.full(len(y), np.nan)
            for Y in range(2021, 2027):
                b = fit(X, y, (yr >= 2020) & (yr != Y)); m = yr == Y; res[m] = (y - b[0] - X @ b[1:])[m]
            b = fit(X, y, yr >= 2020)
            out["leads"][str(L)] = {"coef": [round(float(x), 6) for x in b], "q_free": [round(float(x), 4) for x in np.nanquantile(res[icet == 0], QP)], "q_ice": [round(float(x), 4) for x in np.nanquantile(res[icet == 1], QP)]}
            if L in (1, 6, 12, 24, 48): print(L, "rmse hors éch. %.3f / glace %.3f" % (rmse(res[icet == 0]), rmse(res[icet == 1])), "q10..q90 hors glace", out["leads"][str(L)]["q_free"][3], out["leads"][str(L)]["q_free"][19], flush=True)
        json.dump(out, open(os.path.join(ROOT, "coefs_horaire.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    if mode == "calib":
        # Les pourcentages annoncés sont-ils justes ? Ajusté et quantiles sur 2020-2025, vérifié sur 2026 :
        # plage fictive de 15 cm placée au hasard autour du niveau ; chances annoncées contre fréquence observée.
        rng = np.random.default_rng(0); allp = []; allo = []; cov = []
        for L in (3, 6, 12, 18, 24, 30, 36, 48):
            X, y, yr, icet, last, _ = XY(L); tr = (yr >= 2020) & (yr <= 2025); b = fit(X, y, tr); p = b[0] + X @ b[1:]; r = y - p
            te = (yr == 2026) & ~np.isnan(r)
            for ice in (0, 1):
                q = np.nanquantile(r[tr & (icet == ice)], QP); m = te & (icet == ice)
                if not m.sum(): continue
                cov.append((L, ice, np.mean((r[m] >= q[3]) & (r[m] <= q[19])), np.mean((r[m] >= q[6]) & (r[m] <= q[16]))))
                lo = p[m] + rng.uniform(-0.20, 0.10, m.sum()); hi = lo + 0.15
                cdf = lambda e: np.interp(e, q, QP, left=0, right=1)
                allp.append(cdf(hi - p[m]) - cdf(lo - p[m])); allo.append((y[m] >= lo) & (y[m] <= hi))
        for L, ice, c80, c50 in cov: print(f"  {L:2d} h {'glace' if ice else 'hors glace'} : intervalle 80 % contient {100 * c80:.0f} %, intervalle 50 % contient {100 * c50:.0f} %")
        pp = np.concatenate(allp); oo = np.concatenate(allo)
        print("chances annoncées → fréquence observée (2026)")
        for a in np.arange(0, 1, 0.1):
            m = (pp >= a) & (pp < a + 0.1)
            if m.sum() > 50: print(f"  {100 * a:.0f}-{100 * a + 10:.0f} % annoncé (moy. {100 * pp[m].mean():.0f} %) → {100 * oo[m].mean():.0f} % observé   n={m.sum()}")
    if mode == "parite":
        sys.path.insert(0, ROOT); import prevision_frontenac as pf, random
        V = json.load(open(os.path.join(ROOT, "coefs_horaire.json"), encoding="utf-8")); random.seed(2); worst = 0; n = 0
        raw = {c: H[c] - DATUM[c] for c in H}; ref = {}
        for L in LEADS:
            X, y, yr, icet, last, t0s = XY(L); b = np.array(V["leads"][str(L)]["coef"]); ref[L] = dict(zip(t0s.tolist(), (b[0] + X @ b[1:]).tolist()))
        for _ in range(150):
            i = random.randrange(700, ND - 6); h = random.randrange(1, 25)
            hr = {c: {dt.datetime.combine(DATES[i - 3], dt.time()) + dt.timedelta(hours=k): float(v) for k, v in enumerate(raw[c][i - 3:i + 1].reshape(-1)) if not np.isnan(v) and k < 72 + h} for c in raw}
            base = [float(P[k][i - 1]) for k in range(1, 8)]
            if any(np.isnan(base)): continue
            got = pf.forecast_hourly(hr, DATES[i], h, base); t0 = i * 24 + h
            for L, (tt, lvl, q) in enumerate(got, 1):
                r = ref[L][t0]; assert not np.isnan(r), (DATES[i], h, L); worst = max(worst, abs(r - lvl)); n += 1
            if len(got) < 48: assert np.isnan(ref[len(got) + 1][t0]), (DATES[i], h, len(got))
        print(f"parité horaire : {n} prévisions comparées, écart maximal {1000 * worst:.4f} mm")
    if mode == "spine":
        # novembre 2026 : SPINE archivée (48 h) contre le modèle horaire émis à la même heure
        import csv
        V = json.load(open(os.path.join(ROOT, "coefs_horaire.json"), encoding="utf-8")); PT = lambda s: dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ") - dt.timedelta(hours=5)
        idx = lambda t: (t.date() - D0).days * 24 + t.hour; acc = {}; pr = {}
        for L in LEADS:
            X, y, yr, icet, last, t0s = XY(L); b = np.array(V["leads"][str(L)]["coef"]); pr[L] = dict(zip(t0s.tolist(), (b[0] + X @ b[1:]).tolist()))
        for r in csv.DictReader(open(os.path.join(ROOT, "docs", "spine_hourly_archive.csv"))):
            ti, tt = PT(r["issued_utc"]), PT(r["target_utc"]); t0 = idx(ti) + 1; L = idx(tt) - t0 + 1      # la mesure de l'heure d'émission est connue
            if not (1 <= L <= 48) or idx(tt) >= NT: continue
            o = F["fr"][idx(tt)]; m = pr[L].get(t0, np.nan); last = F["fr"][t0 - 1]
            if np.isnan(o) or np.isnan(m) or np.isnan(last): continue
            b = "1-6 h" if L <= 6 else "7-12 h" if L <= 12 else "13-24 h" if L <= 24 else "25-48 h"
            acc.setdefault(b, []).append((o - float(r["level"]), o - m, o - last))
        for b in ("1-6 h", "7-12 h", "13-24 h", "25-48 h"):
            a = np.array(acc[b]); print(f"  {b:8s} n={len(a):4d}  SPINE {100 * np.sqrt((a[:, 0] ** 2).mean()):.1f} cm   modèle horaire {100 * np.sqrt((a[:, 1] ** 2).mean()):.1f} cm   dernier niveau {100 * np.sqrt((a[:, 2] ** 2).mean()):.1f} cm")
