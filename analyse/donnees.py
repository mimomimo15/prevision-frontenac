"""Charge analyse/data/ en tableaux numpy. Heure locale = UTC−5 fixe (comme le site)."""
import csv, datetime as dt, json, math, os
import numpy as np
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D0 = dt.date(2019, 1, 1); ND = (dt.date.today() - D0).days + 1
DATUM = {"fr": 0.0, "pc": 20.35, "sa": 21.34, "var": 0.0}
DATES = [D0 + dt.timedelta(days=i) for i in range(ND)]

def hourly(code):
    """Tableau [jour, heure locale] (NaN si manquant)."""
    a = np.full((ND, 24), np.nan)
    with open(os.path.join(D, f"horaire_{code}.csv")) as f:
        for r in csv.DictReader(f):
            t = dt.datetime.strptime(r["time_utc"], "%Y-%m-%dT%H") - dt.timedelta(hours=5)
            i = (t.date() - D0).days
            if 0 <= i < ND: a[i, t.hour] = float(r["level"]) + DATUM[code]
    return a

def eccc(st, col):
    a = np.full(ND, np.nan)
    with open(os.path.join(D, f"eccc_{st}.csv")) as f:
        for r in csv.DictReader(f):
            i = (dt.date.fromisoformat(r["date"]) - D0).days
            if 0 <= i < ND and r[col] != "": a[i] = float(r[col])
    return a

def cmi():
    ch = []
    for line in open(os.path.join(D, "cmi.csv"), encoding="utf-8").read().splitlines()[4:]:
        p = [x.strip() for x in line.split(",")]
        if len(p) >= 3 and p[0] and p[2]:
            try:
                mo, dd, yy = p[0].split("/"); hh = int(p[1].split(":")[0]) if p[1] else 0; ch.append((dt.date(int(yy), int(mo), int(dd)), hh, int(p[2].replace(" ", ""))))
            except ValueError: pass
    ch.sort(); a = np.full(ND, np.nan); j = 0; cur = None
    for i, d in enumerate(DATES):
        while j < len(ch) and ch[j][0] < d: cur = ch[j][2]; j += 1
        if cur is None: continue
        c = cur; parts = []; h0 = 0; jj = j
        while jj < len(ch) and ch[jj][0] == d:
            parts.append((ch[jj][1] - h0) * c); c = ch[jj][2]; h0 = ch[jj][1]; jj += 1
        parts.append((24 - h0) * c); a[i] = sum(parts) / 24
    return a

def daymean(h, nmin=20):
    n = np.sum(~np.isnan(h), axis=1); m = np.nanmean(np.where(n[:, None] > 0, h, 0), axis=1) if False else np.array([np.nanmean(r) if k >= nmin else np.nan for r, k in zip(h, n)])
    return m

ICE = np.array([1.0 if d.month in (12, 1, 2, 3) else 0.0 for d in DATES])
YEAR = np.array([d.year for d in DATES])
def sh(a, k):
    """a décalé : sh(a,k)[i] = a[i-k] (k>0 = passé)."""
    out = np.full(a.shape, np.nan)
    if k > 0: out[k:] = a[:-k]
    elif k < 0: out[:k] = a[-k:]
    else: out[:] = a
    return out

def charger():
    H = {c: hourly(c) for c in ("fr", "pc", "sa", "var")}
    d = {c: daymean(H[c]) for c in H}
    d.update(br=eccc("02KF005", "discharge"), hull=eccc("02LA015", "level"), lan=eccc("02OB011", "level"), ri=eccc("02OJ007", "discharge"), las=eccc("02OA016", "discharge"), ms=cmi())
    return H, d

def v3_feats(H, d):
    """Variables v3 du jour J (toutes connues en fin de jour J)."""
    aft = lambda h: np.array([np.mean(r[12:18]) if np.sum(~np.isnan(r[12:18])) >= 5 else np.nan for r in h])
    mor = lambda h: np.array([np.mean(r[0:6]) if np.sum(~np.isnan(r[0:6])) >= 5 else np.nan for r in h])
    doy = np.array([x.timetuple().tm_yday for x in DATES])
    f = {"pc_L": d["pc"], "sa_L": d["sa"], "ice": ICE, "pcice": d["pc"] * ICE, "saice": d["sa"] * ICE, "fr_iwls": d["fr"], "dpc": d["pc"] - sh(d["pc"], 1), "dsa": d["sa"] - sh(d["sa"], 1),
         "br": d["br"] / 1000, "dbr": (d["br"] - sh(d["br"], 1)) / 1000, "dbr2": (d["br"] - sh(d["br"], 2)) / 1000,
         "dhull": d["hull"] - sh(d["hull"], 1), "dlan": d["lan"] - sh(d["lan"], 1), "dms_": (d["ms"] - sh(d["ms"], 1)) / 1000, "ri_Q_k": d["ri"] / 1000, "dvar": d["var"] - sh(d["var"], 1),
         "fr_aft": aft(H["fr"]), "fr_slope": aft(H["fr"]) - mor(H["fr"]), "pc_slope": aft(H["pc"]) - mor(H["pc"]), "fr_l2": sh(d["fr"], 2), "dfr": d["fr"] - sh(d["fr"], 1), "pc_l3": sh(d["pc"], 3)}
    f["dms_"] = np.where(np.isnan(f["dms_"]) & (YEAR < 2022), 0.0, f["dms_"])   # registre CMI absent avant 2022 : variation supposée nulle
    return f

def v3_pred(f):
    """Prévisions v3 publiées (coefs_v3.json) : P[k][i] = prévision émise avec le jour J=i pour J+k."""
    V3 = json.load(open(os.path.join(ROOT, "coefs_v3.json")))["horizons"]; P = {}
    for k in range(1, 8):
        h = V3[str(k)]; P[k] = h["coef"][0] + sum(b * f[n] for b, n in zip(h["coef"][1:], h["features"]))
    return P

def rmse(e):
    e = e[~np.isnan(e)]; return float(np.sqrt(np.mean(e ** 2))) if len(e) else float("nan")
