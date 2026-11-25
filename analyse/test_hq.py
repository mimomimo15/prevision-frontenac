"""Les débits horaires aux centrales d'Hydro-Québec (docs/hq_hourly.csv, depuis le 2 nov. 2026) expliquent-ils une partie des
erreurs du modèle horaire et de v4 ? Régression des erreurs sur les variations récentes de débit connues à l'émission
(avec le délai de publication), jugée en validation croisée par blocs de 4 jours."""
import csv, json, sys
import numpy as np
import fit_horaire as FH
import fit_v4 as Fv
from donnees import *
NT = FH.NT
hq = {}
for r in csv.DictReader(open(os.path.join(ROOT, "docs", "hq_hourly.csv"), encoding="utf-8")):
    t = dt.datetime.strptime(r["time_utc"], "%Y-%m-%dT%H:%MZ") - dt.timedelta(hours=5); i = (t.date() - D0).days * 24 + t.hour
    for c, v in r.items():
        if c != "time_utc" and v != "" and 0 <= i < NT: hq.setdefault(c, np.full(NT, np.nan))[i] = float(v)
S = {"TOT (Beauharnois + Coteau)": hq["Beauharnois"] + hq["Coteau 1, 2, 3"], "Beauharnois": hq["Beauharnois"], "Carillon": hq["Carillon"], "Rivière-des-Prairies": hq["Rivière-des-Prairies"]}
def mean_before(x, t, a, b):
    """moyenne de x sur [t-a, t-b) pour chaque t."""
    out = np.full(NT, np.nan)
    for tt in t:
        w = x[tt - a:tt - b]
        if np.sum(~np.isnan(w)) >= max(1, (a - b) // 2): out[tt] = np.nanmean(w)
    return out
T0 = np.arange(int(np.nanargmax(~np.isnan(hq["Beauharnois"]))) + 40, NT - 1)
def feats(lag):
    F = {}
    for n, x in S.items():
        a3 = mean_before(x, T0, lag + 3, lag); a24 = mean_before(x, T0, lag + 24, lag); a9 = mean_before(x, T0, lag + 9, lag + 6)
        F[n + " : 3 h − 24 h"] = (a3 - a24) / 1000; F[n + " : 3 h − (6 à 9 h avant)"] = (a3 - a9) / 1000
    return F
def cv(X, e):
    """RMSE de e, puis de e corrigée par régression sur X (blocs de 4 jours laissés de côté)."""
    ok = ~np.isnan(X).any(axis=1) & ~np.isnan(e); idx = np.where(ok)[0]; blk = (idx // 96); out = np.full(len(e), np.nan)
    for b in np.unique(blk):
        tr = idx[blk != b]; te = idx[blk == b]; A = np.column_stack([np.ones(len(tr)), X[tr]]); co = np.linalg.lstsq(A, e[tr], rcond=None)[0]
        out[te] = e[te] - np.column_stack([np.ones(len(te)), X[te]]) @ co
    A = np.column_stack([np.ones(len(idx)), X[idx]]); co = np.linalg.lstsq(A, e[idx], rcond=None)[0]
    return rmse(e[idx]), rmse(out[idx]), rmse(e[idx] - A @ co), len(idx), co
# erreurs du modèle horaire par échéance, indexées par t0
VH = json.load(open(os.path.join(ROOT, "coefs_horaire.json"), encoding="utf-8")); E = {}
for L in (3, 6, 12, 18, 24, 36):
    X, y, yr, icet, last, t0s = FH.XY(L); b = np.array(VH["leads"][str(L)]["coef"]); e = np.full(NT, np.nan); e[t0s] = y - b[0] - X @ b[1:]; E[f"horaire, échéance {L} h"] = e
# erreurs de v4 (demain, après-demain), indexées par t0 = jour*24 + h
V4 = json.load(open(os.path.join(ROOT, "coefs_v4.json")))
for tgt in (1, 2):
    e = np.full(NT, np.nan); y = sh(Fv.d["fr"], -tgt)
    for h in range(1, 25):
        p = Fv.pred(h, tgt, np.array(V4["h"][str(h)][str(tgt)]["coef"])); ii = np.arange(ND - 1) * 24 + h; e[ii] = (y - p)[:ND - 1]
    E["v4, " + ("demain" if tgt == 1 else "après-demain")] = e
for lag, lab in ((4, "délai de publication réel (≈ 4 h)"), (0, "débits connus sans délai (cas idéal, non réalisable)")):
    F = feats(lag); names = list(F)
    print(f"\n===== {lab}")
    for en, e in E.items():
        # corrélation simple de chaque variable avec l'erreur
        cors = []
        for n in names:
            m = ~np.isnan(F[n]) & ~np.isnan(e)
            cors.append((abs(np.corrcoef(F[n][m], e[m])[0, 1]), np.corrcoef(F[n][m], e[m])[0, 1], n))
        best = max(cors)
        pair = np.column_stack([F["TOT (Beauharnois + Coteau) : 3 h − 24 h"], F["Carillon : 3 h − 24 h"]])
        r0, rcv, rin, n, co = cv(pair, e)
        allX = np.column_stack([F[n] for n in names]); r0b, rcvb, rinb, nb, _ = cv(allX, e)
        print(f"{en:26s} n={n:3d} h  erreur {100 * r0:.2f} cm → avec 2 variables : {100 * rcv:.2f} (validation) / {100 * rin:.2f} (ajusté) ; avec les 8 : {100 * rcvb:.2f} / {100 * rinb:.2f}   | meilleure corrélation r={best[1]:+.2f} ({best[2]})")

# Plafond théorique : si on connaissait d'avance les débits des 24 prochaines heures (impossible), quelle part de l'erreur disparaîtrait ?
print("\n===== débits FUTURS supposés connus (plafond théorique, impossible en pratique)")
fut = {}
for n in ("TOT (Beauharnois + Coteau)", "Carillon", "Rivière-des-Prairies"):
    x = S[n]; f = np.full(NT, np.nan)
    for tt in T0:
        w = x[tt:tt + 24]; p = x[tt - 24:tt]
        if tt + 24 <= NT and np.sum(~np.isnan(w)) >= 18 and np.sum(~np.isnan(p)) >= 18: f[tt] = (np.nanmean(w) - np.nanmean(p)) / 1000
    fut[n] = f
Xf = np.column_stack([fut[n] for n in fut])
for en in ("horaire, échéance 12 h", "horaire, échéance 24 h", "horaire, échéance 36 h", "v4, demain", "v4, après-demain"):
    r0, rcv, rin, n, co = cv(Xf, E[en]); cs = [np.corrcoef(fut[k][~np.isnan(fut[k]) & ~np.isnan(E[en])], E[en][~np.isnan(fut[k]) & ~np.isnan(E[en])])[0, 1] for k in fut]
    print(f"{en:26s} n={n:3d} h  erreur {100 * r0:.2f} cm → {100 * rcv:.2f} (validation)   corrélations : TOT {cs[0]:+.2f}, Carillon {cs[1]:+.2f}, Prairies {cs[2]:+.2f}")
