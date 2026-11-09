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
ST_VAR = "5cebf1e03d0f4a073c4bbe04"   # Varennes (15660), utilisé pour la prévision de débit
Q_COEF = [7310.79, 5972.9, 1842.5, -184.23]   # débit LaSalle ≈ c0 + c1·(Frontenac − Varennes) + c2·Frontenac + c3·Glace
Q_P90_PERSIST = {1: 270, 2: 400, 3: 500, 4: 600, 5: 650, 6: 720, 7: 790}


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
    # jour J = dernier jour avec toutes les données ; la journée en cours compte à partir de 18 h
    # (≥ 18 lectures horaires) et sera remplacée par la moyenne complète à la prochaine exécution
    if d1 in hist and now.hour < 18:
        partial = hist.pop(d1)
    else:
        partial = None
    complete = [d for d in sorted(hist) if all(hist[d][k] is not None for k in FIELDS[1:4])]
    save_hist(hist)
    J = complete[-1]; J1 = J - dt.timedelta(days=1)
    if J1 not in hist: sys.exit("Données de J-1 manquantes")
    h = hist
    res, fc = pf.forecast(J, h[J]["frontenac_zc"], h[J]["pointeclaire_igld85"], h[J1]["pointeclaire_igld85"], h[J]["steanne_igld85"], h[J1]["steanne_igld85"])
    model_used = "v1"
    # ---- modèle v2 : rivière des Outaouais à Ottawa (Britannia), archive glissante locale
    BR = os.path.join(DOCS, "britannia.csv"); br = {}
    if os.path.exists(BR):
        with open(BR, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f): br[dt.date.fromisoformat(r["date"])] = float(r["q"])
    for d, v in pf.fetch_eccc_discharge_daily("02KF005").items(): br[d] = v
    br = {d: v for d, v in br.items() if d >= J - dt.timedelta(days=400)}
    with open(BR, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["date", "q"]); [w.writerow([d.isoformat(), f"{br[d]:.1f}"]) for d in sorted(br)]
    J2 = J - dt.timedelta(days=2)
    if all(d in br for d in (J, J1, J2)):
        fc = pf.forecast_v2(J, h[J]["frontenac_zc"], h[J]["pointeclaire_igld85"], h[J1]["pointeclaire_igld85"], h[J]["steanne_igld85"], h[J1]["steanne_igld85"], br[J], br[J1], br[J2])
        model_used = "v2"
    print("modèle utilisé :", model_used)
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
    def latest_discharge(station):
        try:
            import requests
            r = requests.get(pf.ECCC_RT, timeout=30, params={"STATION_NUMBER": station, "f": "json", "limit": 12, "sortby": "-DATETIME", "properties": "DATETIME,DISCHARGE"})
            feats = [f["properties"] for f in r.json()["features"] if f["properties"].get("DISCHARGE") is not None]
            if feats: return {"time": feats[0]["DATETIME"], "value": round(feats[0]["DISCHARGE"])}
        except Exception as e:
            print(f"débit {station} indisponible :", e)
        return None
    discharge = latest_discharge("02OA016")                 # Saint-Laurent à LaSalle
    discharge_bdf = latest_discharge("02OA003")             # Rivière des Mille Îles à Bois-des-Filion
    hourly = []
    try:
        import requests
        t1 = dt.datetime.utcnow(); t0 = t1 - dt.timedelta(hours=72)
        r = requests.get(f"{pf.API}/{pf.ST['fr']}/data", timeout=40, params={"time-series-code": "wlo", "from": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": t1.strftime("%Y-%m-%dT%H:%M:%SZ"), "resolution": "SIXTY_MINUTES"})
        hourly = [{"t": p["eventDate"], "v": round(p["value"], 3)} for p in r.json()]
    except Exception as e:
        print("série horaire indisponible :", e)
    spine_hourly = []
    try:
        import requests
        t1 = dt.datetime.utcnow(); t2 = t1 + dt.timedelta(hours=49)
        r = requests.get(f"{pf.API}/{pf.ST['fr']}/data", timeout=40, params={"time-series-code": "wlf-spine", "from": t1.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": t2.strftime("%Y-%m-%dT%H:%M:%SZ"), "resolution": "SIXTY_MINUTES"})
        spine_hourly = [{"t": p["eventDate"], "v": round(p["value"], 3)} for p in r.json()]
    except Exception as e:
        print("SPINE horaire indisponible :", e)
    # archives (pour évaluer plus tard la précision de SPINE et du modèle) : 7 lignes par exécution chacune
    issued = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    for name, rows in (("spine_archive.csv", [(d.isoformat(), spine[d]) for d in sorted(spine)]),
                       ("forecast_archive.csv", [(d.isoformat(), l) for d, l, m in fc])):
        p = os.path.join(DOCS, name); new = not os.path.exists(p)
        with open(p, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new: w.writerow(["issued_utc", "target_date", "level_zc"])
            for tdate, v in rows: w.writerow([issued, tdate, f"{v:.3f}"])
    # ------------------------------------------------------------------ auto-apprentissage
    # Archives horaires : observations (120 j) et prévisions SPINE 48 h (90 j), puis correction de SPINE
    # par horizon : erreur(h) ≈ a(h) + b(h) × erreur_actuelle, estimée sur les archives (≥ 10 jours).
    OBS_H = os.path.join(DOCS, "obs_hourly.csv"); SP_H = os.path.join(DOCS, "spine_hourly_archive.csv")
    now_utc = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    obs_h = {}
    if os.path.exists(OBS_H):
        with open(OBS_H, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f): obs_h[r["time_utc"]] = float(r["level"])
    for p in hourly: obs_h[p["t"][:13] + ":00:00Z"] = p["v"]
    cutoff_obs = (now_utc - dt.timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    obs_h = {k: v for k, v in obs_h.items() if k >= cutoff_obs}
    with open(OBS_H, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["time_utc", "level"])
        for k in sorted(obs_h): w.writerow([k, f"{obs_h[k]:.3f}"])
    sp_rows = []
    if os.path.exists(SP_H):
        with open(SP_H, newline="", encoding="utf-8") as f:
            sp_rows = [(r["issued_utc"], r["target_utc"], float(r["level"])) for r in csv.DictReader(f)]
    issued_h = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    sp_rows += [(issued_h, p["t"][:13] + ":00:00Z", p["v"]) for p in spine_hourly]
    cutoff_sp = (now_utc - dt.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sp_rows = [r for r in sp_rows if r[0] >= cutoff_sp]
    with open(SP_H, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["issued_utc", "target_utc", "level"])
        for r in sp_rows: w.writerow([r[0], r[1], f"{r[2]:.3f}"])
    # erreurs passées par horizon
    def hours_between(a, b):
        return int((dt.datetime.strptime(b, "%Y-%m-%dT%H:%M:%SZ") - dt.datetime.strptime(a, "%Y-%m-%dT%H:%M:%SZ")).total_seconds() // 3600)
    by_issue = {}
    for iss, tgt, v in sp_rows: by_issue.setdefault(iss, {})[tgt] = v
    buckets = [(1, 3), (4, 6), (7, 12), (13, 24), (25, 48)]
    samples = {b: [] for b in buckets}
    for iss, fc_map in by_issue.items():
        e0 = None
        if iss in fc_map and iss in obs_h: e0 = obs_h[iss] - fc_map[iss]
        for tgt, v in fc_map.items():
            if tgt not in obs_h or e0 is None: continue
            lead = hours_between(iss, tgt)
            for b in buckets:
                if b[0] <= lead <= b[1]: samples[b].append((e0, obs_h[tgt] - v))
    def fit(pairs):
        n = len(pairs); mx = sum(p[0] for p in pairs) / n; my = sum(p[1] for p in pairs) / n
        sxx = sum((p[0] - mx) ** 2 for p in pairs); sxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
        b = sxy / sxx if sxx > 1e-9 else 0.0; a = my - b * mx
        rmse_raw = (sum(p[1] ** 2 for p in pairs) / n) ** 0.5
        rmse_adj = (sum((p[1] - a - b * p[0]) ** 2 for p in pairs) / n) ** 0.5
        return a, b, rmse_raw, rmse_adj, n
    skill = {}; coef = {}
    for b in buckets:
        if len(samples[b]) >= 200:
            a, bb, r_raw, r_adj, n = fit(samples[b]); coef[b] = (a, bb)
            skill[f"{b[0]}-{b[1]} h"] = {"rmse_spine": round(r_raw, 3), "rmse_adj": round(r_adj, 3), "n": n}
    spine_adj = []
    e0_now = None
    if spine_hourly and coef:
        k0 = spine_hourly[0]["t"][:13] + ":00:00Z"
        if k0 in obs_h: e0_now = obs_h[k0] - spine_hourly[0]["v"]
        elif live: e0_now = live["value"] - spine_hourly[0]["v"]
    if e0_now is not None:
        for p in spine_hourly:
            lead = hours_between(issued_h, p["t"][:13] + ":00:00Z")
            c = next((coef[b] for b in buckets if b[0] <= lead <= b[1] and b in coef), None)
            if c: spine_adj.append({"t": p["t"], "v": round(p["v"] + c[0] + c[1] * e0_now, 3)})
    # précision du modèle statistique à J+1 d'après son archive
    stat_skill = None
    try:
        with open(os.path.join(DOCS, "forecast_archive.csv"), newline="", encoding="utf-8") as f:
            errs = {}
            for r in csv.DictReader(f):
                td = dt.date.fromisoformat(r["target_date"]); idate = dt.date.fromisoformat(r["issued_utc"][:10])
                if (td - idate).days == 1 and td in hist and hist[td]["frontenac_zc"] is not None:
                    errs[idate] = hist[td]["frontenac_zc"] - float(r["level_zc"])   # une par jour d'émission (dernière)
            if len(errs) >= 10:
                v = list(errs.values()); stat_skill = {"rmse_J1": round((sum(x * x for x in v) / len(v)) ** 0.5, 3), "n": len(v)}
    except FileNotFoundError:
        pass
    # ------------------------------------------------------------------ prévision de débit (LaSalle)
    # Q(J+k) = Q(J) + [q(niveaux SPINE J+k) − q(niveaux observés J)], q = relation pente Frontenac–Varennes
    def q_from(fr_, var_, ice_):
        return Q_COEF[0] + Q_COEF[1] * (fr_ - var_) + Q_COEF[2] * fr_ + Q_COEF[3] * ice_
    q_fc = []
    try:
        pf.ST["var"] = ST_VAR
        var_obs = pf.fetch_iwls_daily("var", J - dt.timedelta(days=1), J)
        var_sp = pf.fetch_iwls_daily("var", J + dt.timedelta(days=1), J + dt.timedelta(days=7), series="wlf-spine")
        q_anchor = q_las.get(J) or (discharge["value"] if discharge else None)
        if q_anchor and J in var_obs:
            base = q_from(h[J]["frontenac_zc"], var_obs[J], pf.is_ice(J))
            for d, l, m in fc:
                if d in spine and d in var_sp:
                    q_fc.append({"date": d.isoformat(), "q": int(round(q_anchor + q_from(spine[d], var_sp[d], pf.is_ice(d)) - base, -1)), "src": "spine"})
                else:
                    q_fc.append({"date": d.isoformat(), "q": int(round(q_anchor, -1)), "src": "persistance"})
        elif q_anchor:
            q_fc = [{"date": d.isoformat(), "q": int(round(q_anchor, -1)), "src": "persistance"} for d, l, m in fc]
        for i, row in enumerate(q_fc, 1): row["p90"] = Q_P90_PERSIST[i]
    except Exception as e:
        print("prévision de débit indisponible :", e)
    # débit sortant du lac Ontario (barrage Moses-Saunders) – registre des changements de la CMI (CSV, licence ouverte)
    ms_flow = None
    try:
        import requests
        t = requests.get("https://ijc.org/sites/default/files/ChangementDebit_FlowChanges.csv", timeout=30).text
        rows = []
        for line in t.splitlines()[4:]:
            p = [x.strip() for x in line.split(",")]
            if len(p) >= 3 and p[0] and p[2]:
                try:
                    m, dd, y = p[0].split("/"); rows.append((dt.date(int(y), int(m), int(dd)), p[1], int(p[2].replace(" ", ""))))
                except ValueError:
                    pass
        if rows:
            rows.sort(); last = rows[-1]; prev = rows[-2] if len(rows) > 1 else None
            ms_flow = {"date": last[0].isoformat(), "hour": last[1], "value": last[2], "previous": (prev[2] if prev else None)}
    except Exception as e:
        print("débit lac Ontario (CMI) indisponible :", e)
    # météo en direct à Montréal (Open-Meteo, licence CC BY 4.0) : température de l'air, ressenti, vent
    air = None
    try:
        import requests
        j = requests.get("https://api.open-meteo.com/v1/forecast", timeout=30, params={"latitude": 45.529, "longitude": -73.543, "current": "temperature_2m,apparent_temperature,wind_speed_10m,wind_gusts_10m,wind_direction_10m", "timezone": "America/Toronto"}).json()["current"]
        air = {"time": j["time"], "temp": j["temperature_2m"], "feels": j["apparent_temperature"], "wind": j["wind_speed_10m"], "gust": j["wind_gusts_10m"], "dir": j["wind_direction_10m"]}
    except Exception as e:
        print("météo indisponible :", e)
    days60 = [d for d in sorted(hist) if d <= J][-60:]
    data = {
        "generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "station": "Montréal, rue Frontenac (SHC 15540)", "datum_note": "mètres au-dessus du zéro des cartes (IGLD85 = ZC + 5,35 m)",
        "day_J": J.isoformat(), "obs_J": round(h[J]["frontenac_zc"], 3), "pc_J": round(h[J]["pointeclaire_igld85"], 3), "sa_J": round(h[J]["steanne_igld85"], 3),
        "residual": round(res, 3), "ice": pf.is_ice(J), "model": model_used, "britannia_q": (round(br[J]) if J in br else None), "live": live, "water_temp": water_temp, "discharge": discharge,
        "partial_today": (round(partial["frontenac_zc"], 3) if partial and partial["frontenac_zc"] is not None else None),
        "history": [{"date": d.isoformat(), "obs": round(hist[d]["frontenac_zc"], 3)} for d in days60], "hourly": hourly, "spine_hourly": spine_hourly, "spine_adj": spine_adj, "skill": skill, "stat_skill": stat_skill, "q_forecast": q_fc, "discharge_bdf": discharge_bdf, "air": air, "ms_flow": ms_flow, "q_anchor_day": (round(q_las[J]) if J in q_las else None),
        "forecast": [{"date": d.isoformat(), "level": round(l, 3), "margin": round(m, 3), "spine": (round(spine[d], 3) if d in spine else None)} for d, l, m in fc],
    }
    with open(os.path.join(DOCS, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"OK – J = {J}, résidu {res:+.3f} m, J+1 = {fc[0][1]:+.2f} m")


if __name__ == "__main__":
    main()
