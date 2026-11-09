#!/usr/bin/env python3
"""
Génère docs/data.json pour le site (GitHub Pages) à partir des mêmes fonctions que
prevision_frontenac.py : télécharge les observations manquantes, met à jour docs/history.csv,
calcule la prévision J+1 → J+7 et récupère la prévision SPINE du SHC.
Lancé automatiquement par GitHub Actions (.github/workflows/update.yml).
"""
import csv, datetime as dt, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prevision_frontenac as pf

DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
HIST = os.path.join(DOCS, "history.csv")
FIELDS = ["date", "frontenac_zc", "pointeclaire_igld85", "steanne_igld85", "lasalle_q"]


def load_hist():
    rows = {}
    if os.path.exists(HIST):
        with open(HIST, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows[dt.date.fromisoformat(r["date"])] = {k: (float(r[k]) if r.get(k) not in (None, "") else None) for k in FIELDS[1:]}
    return rows


def save_hist(rows):
    with open(HIST, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(FIELDS)
        for d in sorted(rows):
            r = rows[d]; w.writerow([d.isoformat()] + ["" if r[k] is None else f"{r[k]:.3f}" if k != "lasalle_q" else f"{r[k]:.1f}" for k in FIELDS[1:]])


def main():
    now = dt.datetime.utcnow() + pf.TZ
    hist = load_hist()
    last = max(hist) if hist else now.date() - dt.timedelta(days=70)
    d0 = last - dt.timedelta(days=2)
    d1 = now.date()
    print(f"Téléchargement {d0} → {d1} ...")
    series = {k: pf.fetch_iwls_daily(k, d0, d1) for k in pf.ST}
    q_las = pf.fetch_eccc_discharge_daily()
    for d in sorted(set(series["fr"]) | set(series["pc"]) | set(series["sa"])):
        r = hist.setdefault(d, {k: None for k in FIELDS[1:]})
        if d in series["fr"]: r["frontenac_zc"] = series["fr"][d]
        if d in series["pc"]: r["pointeclaire_igld85"] = series["pc"][d] + pf.DATUM["pc"]
        if d in series["sa"]: r["steanne_igld85"] = series["sa"][d] + pf.DATUM["sa"]
        if d in q_las: r["lasalle_q"] = q_las[d]
    # jour J = dernier jour COMPLET (≥ 12 valeurs horaires = déjà filtré) avec toutes les données
    complete = [d for d in sorted(hist) if d < d1 and all(hist[d][k] is not None for k in FIELDS[1:4])]
    # garder le jour courant (partiel) hors historique officiel si trop tôt
    if d1 in hist and now.hour < 23:
        partial = hist.pop(d1)
    else:
        partial = None
    save_hist(hist)
    J = complete[-1]; J1 = J - dt.timedelta(days=1)
    if J1 not in hist: sys.exit("Données de J-1 manquantes")
    h = hist
    res, fc = pf.forecast(J, h[J]["frontenac_zc"], h[J]["pointeclaire_igld85"], h[J1]["pointeclaire_igld85"], h[J]["steanne_igld85"], h[J1]["steanne_igld85"])
    spine = {}
    try:
        spine = pf.fetch_iwls_daily("fr", J + dt.timedelta(days=1), J + dt.timedelta(days=7), series="wlf-spine")
    except Exception as e:
        print("SPINE indisponible :", e)
    # niveau « en direct » : dernière heure disponible
    live = None
    try:
        import requests
        t1 = dt.datetime.utcnow(); t0 = t1 - dt.timedelta(hours=6)
        r = requests.get(f"{pf.API}/{pf.ST['fr']}/data", timeout=30, params={"time-series-code": "wlo", "from": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": t1.strftime("%Y-%m-%dT%H:%M:%SZ"), "resolution": "FIFTEEN_MINUTES"})
        j = r.json()
        if j: live = {"time": j[-1]["eventDate"], "value": j[-1]["value"]}
    except Exception as e:
        print("niveau en direct indisponible :", e)
    # température de l'eau (capteur wt1 de la station) et débit à LaSalle (ECCC temps réel), dernière valeur
    water_temp = None; discharge = None
    try:
        import requests
        t1 = dt.datetime.utcnow(); t0 = t1 - dt.timedelta(hours=12)
        r = requests.get(f"{pf.API}/{pf.ST['fr']}/data", timeout=30, params={"time-series-code": "wt1", "from": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": t1.strftime("%Y-%m-%dT%H:%M:%SZ"), "resolution": "FIFTEEN_MINUTES"})
        j = r.json()
        if j: water_temp = {"time": j[-1]["eventDate"], "value": round(j[-1]["value"], 1)}
    except Exception as e:
        print("température de l'eau indisponible :", e)
    try:
        import requests
        r = requests.get(pf.ECCC_RT, timeout=30, params={"STATION_NUMBER": "02OA016", "f": "json", "limit": 12, "sortby": "-DATETIME", "properties": "DATETIME,DISCHARGE"})
        feats = [f["properties"] for f in r.json()["features"] if f["properties"].get("DISCHARGE") is not None]
        if feats: discharge = {"time": feats[0]["DATETIME"], "value": round(feats[0]["DISCHARGE"])}
    except Exception as e:
        print("débit LaSalle indisponible :", e)
    days60 = [d for d in sorted(hist) if d <= J][-60:]
    data = {
        "generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "station": "Montréal, rue Frontenac (SHC 15540)", "datum_note": "mètres au-dessus du zéro des cartes (IGLD85 = ZC + 5,35 m)",
        "day_J": J.isoformat(), "obs_J": round(h[J]["frontenac_zc"], 3), "pc_J": round(h[J]["pointeclaire_igld85"], 3), "sa_J": round(h[J]["steanne_igld85"], 3),
        "residual": round(res, 3), "ice": pf.is_ice(J), "live": live, "water_temp": water_temp, "discharge": discharge,
        "partial_today": (round(partial["frontenac_zc"], 3) if partial and partial["frontenac_zc"] is not None else None),
        "history": [{"date": d.isoformat(), "obs": round(hist[d]["frontenac_zc"], 3)} for d in days60],
        "forecast": [{"date": d.isoformat(), "level": round(l, 3), "margin": round(m, 3), "spine": (round(spine[d], 3) if d in spine else None)} for d, l, m in fc],
    }
    with open(os.path.join(DOCS, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"OK – J = {J}, résidu {res:+.3f} m, J+1 = {fc[0][1]:+.2f} m")


if __name__ == "__main__":
    main()
