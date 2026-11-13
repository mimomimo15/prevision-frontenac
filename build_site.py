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


AIR_KEEP_H = 3   # au-delà de 3 heures, une vieille météo ne vaut plus rien pour la wetsuit : le site affiche « indisponible »


def fetch_air(tries=3):
    """Météo en direct à Montréal (Open-Meteo, licence CC BY 4.0) : température de l'air, ressenti, vent.
    L'appel échoue parfois depuis les serveurs de GitHub : on réessaie, puis on reprend la dernière météo connue
    de docs/data.json tant qu'elle a moins de AIR_KEEP_H heures (son heure de mesure reste affichée sur le site)."""
    import time
    err = None
    for i in range(tries):
        try:
            import requests
            r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=30, params={"latitude": 45.529, "longitude": -73.543, "current": "temperature_2m,apparent_temperature,wind_speed_10m,wind_gusts_10m,wind_direction_10m", "timezone": "America/Toronto"})
            j = r.json()
            if "current" not in j:   # refus de la source (trop de requêtes, etc.) : le motif va dans le journal
                raise RuntimeError(f"HTTP {r.status_code} : {str(j.get('reason', j))[:160]}")
            j = j["current"]
            return {"time": j["time"], "temp": j["temperature_2m"], "feels": j["apparent_temperature"], "wind": j["wind_speed_10m"], "gust": j["wind_gusts_10m"], "dir": j["wind_direction_10m"],
                    "fetched": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
        except Exception as e:
            err = e
            print(f"météo : essai {i + 1}/{tries} manqué :", e)
            if i < tries - 1:
                time.sleep(5 * 4 ** i)   # 5 s, puis 20 s
    try:
        with open(os.path.join(DOCS, "data.json"), encoding="utf-8") as f:
            prev = json.load(f).get("air")
        if prev and prev.get("fetched"):
            age = dt.datetime.utcnow() - dt.datetime.strptime(prev["fetched"], "%Y-%m-%dT%H:%M:%SZ")
            if dt.timedelta(0) <= age <= dt.timedelta(hours=AIR_KEEP_H):
                print(f"météo indisponible : dernière valeur connue conservée (mesure de {prev['time']})")
                return prev
    except Exception as e:
        print("météo : dernière valeur connue illisible :", e)
    print("météo indisponible :", err)
    return None


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
    # ---- modèle v3 : variables supplémentaires (Hull, Lanoraie, Richelieu, Varennes, CMI, heures 12-18 h), archivées dans aux_daily.csv
    v3_used = []; aux_today = {}
    if model_used == "v2" and pf.V3:
        try:
            import requests
            AUX = os.path.join(DOCS, "aux_daily.csv"); aux = {}
            if os.path.exists(AUX):
                with open(AUX, newline="", encoding="utf-8") as f:
                    for r in csv.DictReader(f): aux[dt.date.fromisoformat(r["date"])] = {k: (float(v) if v not in ("", None) else None) for k, v in r.items() if k != "date"}
            COLS = ["hull", "lan", "ri", "var", "ms", "fr_aft", "fr_slope", "pc_aft", "pc_slope"]
            def put(d, k, v):
                if v is None: return
                aux.setdefault(d, {c: None for c in COLS})[k] = v
            for d, v in pf.fetch_eccc_daily("02LA015", "LEVEL").items(): put(d, "hull", v)        # Outaouais à Hull
            for d, v in pf.fetch_eccc_daily("02OB011", "LEVEL").items(): put(d, "lan", v)         # Saint-Laurent à Lanoraie
            for d, v in pf.fetch_eccc_daily("02OJ007", "DISCHARGE").items(): put(d, "ri", v)      # Richelieu aux rapides Fryers
            pf.ST["var"] = ST_VAR
            for d, v in pf.fetch_iwls_daily("var", J - dt.timedelta(days=3), J).items(): put(d, "var", v)   # Varennes (ZC)
            # débit sortant du lac Ontario : série journalière à partir du registre des changements de la CMI (pondérée par l'heure du changement)
            try:
                t = requests.get("https://ijc.org/sites/default/files/ChangementDebit_FlowChanges.csv", timeout=30).text; ch = []
                for line in t.splitlines()[4:]:
                    p = [x.strip() for x in line.split(",")]
                    if len(p) >= 3 and p[0] and p[2]:
                        try:
                            mo, dd, yy = p[0].split("/"); hh = int(p[1].split(":")[0]) if p[1] else 0; ch.append((dt.date(int(yy), int(mo), int(dd)), hh, int(p[2].replace(" ", ""))))
                        except ValueError: pass
                ch.sort()
                if ch:
                    for d in [J - dt.timedelta(days=i) for i in range(0, 4)]:
                        before = [c for c in ch if c[0] < d]
                        if not before: continue
                        cur = before[-1][2]; parts = []; h0 = 0
                        for c in [c for c in ch if c[0] == d]:
                            parts.append((c[1] - h0) * cur); cur = c[2]; h0 = c[1]
                        parts.append((24 - h0) * cur); put(d, "ms", sum(parts) / 24)
            except Exception as e:
                print("CMI indisponible :", e)
            # heures 12-18 h et pente du jour (Frontenac, Pointe-Claire) à partir des séries horaires IWLS
            def day_stats(series_hourly, d):
                vals = {}
                for p in series_hourly:
                    tl = dt.datetime.strptime(p["t"][:19], "%Y-%m-%dT%H:%M:%S") + pf.TZ
                    if tl.date() == d: vals[tl.hour] = p["v"]
                aft = [vals[hh] for hh in range(12, 18) if hh in vals]; mor = [vals[hh] for hh in range(0, 6) if hh in vals]
                if len(aft) >= 5 and len(mor) >= 5: return sum(aft) / len(aft), sum(aft) / len(aft) - sum(mor) / len(mor)
                return None, None
            t1 = dt.datetime.utcnow(); t0 = t1 - dt.timedelta(hours=96)
            hourly_fr, hourly_pc = [], []
            for code, store in (("fr", hourly_fr), ("pc", hourly_pc)):
                try:
                    r = requests.get(f"{pf.API}/{pf.ST[code]}/data", timeout=40, params={"time-series-code": "wlo", "from": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": t1.strftime("%Y-%m-%dT%H:%M:%SZ"), "resolution": "SIXTY_MINUTES"})
                    store.extend({"t": p["eventDate"], "v": p["value"]} for p in r.json())
                except Exception as e:
                    print("horaire", code, "indisponible :", e)
            for d in (J, J1):
                a, sl = day_stats(hourly_fr, d); put(d, "fr_aft", a); put(d, "fr_slope", sl)
                a, sl = day_stats(hourly_pc, d); put(d, "pc_aft", a); put(d, "pc_slope", sl)
            aux = {d: v for d, v in aux.items() if d >= J - dt.timedelta(days=400)}
            with open(AUX, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["date"] + COLS); [w.writerow([d.isoformat()] + [("" if aux[d].get(c) is None else f"{aux[d][c]:.4f}") for c in COLS]) for d in sorted(aux)]
            g = lambda d, k: aux.get(d, {}).get(k)
            J3 = J - dt.timedelta(days=3)
            extra = {
                "dhull": (g(J, "hull") - g(J1, "hull")) if g(J, "hull") is not None and g(J1, "hull") is not None else None,
                "dlan": (g(J, "lan") - g(J1, "lan")) if g(J, "lan") is not None and g(J1, "lan") is not None else None,
                "dms_": ((g(J, "ms") - g(J1, "ms")) / 1000) if g(J, "ms") is not None and g(J1, "ms") is not None else None,
                "ri_Q_k": (g(J, "ri") / 1000) if g(J, "ri") is not None else None,
                "dvar": (g(J, "var") - g(J1, "var")) if g(J, "var") is not None and g(J1, "var") is not None else None,
                "fr_aft": g(J, "fr_aft"), "fr_slope": g(J, "fr_slope"), "pc_slope": g(J, "pc_slope"),
                "fr_l2": h[J2]["frontenac_zc"] if J2 in h else None, "dfr": h[J]["frontenac_zc"] - h[J1]["frontenac_zc"],
                "pc_l3": h[J3]["pointeclaire_igld85"] if J3 in h else None,
            }
            aux_today = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in extra.items()}
            feats = pf.v3_features(J, h[J]["frontenac_zc"], h[J]["pointeclaire_igld85"], h[J1]["pointeclaire_igld85"], h[J]["steanne_igld85"], h[J1]["steanne_igld85"], br[J], br[J1], br[J2], extra)
            fc, v3_used = pf.forecast_v3(J, feats, fc)
            if v3_used: model_used = "v3" if len(v3_used) == 7 else "v3 partiel"
            print("v3 : horizons", v3_used, "· manquants :", [k for k, v in extra.items() if v is None])
        except Exception as e:
            print("v3 impossible :", e)
    print("modèle utilisé :", model_used)
    AUXD = {}
    try:
        with open(os.path.join(DOCS, "aux_daily.csv"), newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f): AUXD[dt.date.fromisoformat(r["date"])] = {k: (float(v) if v not in ("", None) else None) for k, v in r.items() if k != "date"}
    except FileNotFoundError:
        pass
    def replay(Jp):
        """Prévision 7 jours telle que le site l'aurait émise le jour Jp avec les seules données de ce jour-là (sans ajustement intrajournalier)."""
        Jp1 = Jp - dt.timedelta(days=1); Jp2 = Jp - dt.timedelta(days=2); Jp3 = Jp - dt.timedelta(days=3)
        if Jp not in hist or Jp1 not in hist or any(hist[x][k] is None for x in (Jp, Jp1) for k in ("frontenac_zc", "pointeclaire_igld85", "steanne_igld85")): return None
        hp, hp1 = hist[Jp], hist[Jp1]; args = (Jp, hp["frontenac_zc"], hp["pointeclaire_igld85"], hp1["pointeclaire_igld85"], hp["steanne_igld85"], hp1["steanne_igld85"])
        if not all(x in br for x in (Jp, Jp1, Jp2)): return pf.forecast(*args)[1]
        f2 = pf.forecast_v2(*args, br[Jp], br[Jp1], br[Jp2])
        if not pf.V3: return f2
        g = lambda d, k: AUXD.get(d, {}).get(k)
        dif = lambda k, d0, d1, sc=1: ((g(d0, k) - g(d1, k)) / sc) if g(d0, k) is not None and g(d1, k) is not None else None
        extra = {"dhull": dif("hull", Jp, Jp1), "dlan": dif("lan", Jp, Jp1), "dms_": dif("ms", Jp, Jp1, 1000), "dvar": dif("var", Jp, Jp1),
                 "ri_Q_k": (g(Jp, "ri") / 1000) if g(Jp, "ri") is not None else None, "fr_aft": g(Jp, "fr_aft"), "fr_slope": g(Jp, "fr_slope"), "pc_slope": g(Jp, "pc_slope"),
                 "fr_l2": hist[Jp2]["frontenac_zc"] if Jp2 in hist else None, "dfr": hp["frontenac_zc"] - hp1["frontenac_zc"], "pc_l3": hist[Jp3]["pointeclaire_igld85"] if Jp3 in hist else None}
        return pf.forecast_v3(Jp, pf.v3_features(*args, br[Jp], br[Jp1], br[Jp2], extra), f2)[0]
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
    # ---- ajustement intrajournalier : avant 18 h, les heures déjà mesurées aujourd'hui corrigent la prévision
    # d'aujourd'hui et des jours suivants (coefficients par heure, coefs_intraday.json, validés 2020-2025)
    intraday = None; fc_raw = list(fc)
    try:
        INTRA = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "coefs_intraday.json")))["hours"]
        today = d1; hnow = now.hour
        if fc and fc[0][0] == today and 3 <= hnow < 18:
            vals = [p["v"] for p in hourly if (dt.datetime.strptime(p["t"][:19], "%Y-%m-%dT%H:%M:%S") + pf.TZ).date() == today]
            if len(vals) >= hnow - 1:
                part = sum(vals) / len(vals); hb = INTRA[str(min(max(hnow, 3), 17))]
                cc = hb["ice"] if (pf.is_ice(J) and "ice" in hb) else hb["free"]
                p1 = fc[0][1]; x = part - p1; new = []
                t = cc["today"]; new.append((fc[0][0], t["coef"][0] + t["coef"][1] * part + t["coef"][2] * p1, t["p90"]))
                for k in range(2, 8):
                    e = cc[f"k{k}"]; new.append((fc[k - 1][0], fc[k - 1][1] + e["coef"][0] + e["coef"][1] * x, e["p90"]))
                intraday = {"hour": hnow, "n": len(vals), "partial": round(part, 3), "model_today": round(p1, 3), "x": round(x, 3)}
                fc = new
                print(f"ajustement intrajournalier à {hnow} h : moyenne partielle {part:+.3f}, modèle {p1:+.3f}, écart {x:+.3f}")
    except Exception as e:
        print("ajustement intrajournalier impossible :", e)
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
    # ------------------------------------------------------------------ validation.json : rejeu complet sur l'historique du site
    # pour chaque jour observé et chaque échéance k, la prévision que le modèle émettait k jours plus tôt (données de ce
    # jour-là seulement) et, quand elle existe, la prévision SPINE archivée le même jour ; alimente la page Validation.
    try:
        sp_runs = {}
        try:
            with open(os.path.join(DOCS, "spine_archive.csv"), newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    iloc = (dt.datetime.strptime(r["issued_utc"], "%Y-%m-%dT%H:%MZ") + pf.TZ).date()
                    sp_runs[(iloc, dt.date.fromisoformat(r["target_date"]))] = float(r["level_zc"])
        except FileNotFoundError:
            pass
        vrows = {}
        for Jp in sorted(hist):
            if Jp < d1 - dt.timedelta(days=400): continue      # le rejeu plus ancien est dans validation_hist.json (statique)
            try:
                fcp = replay(Jp)
            except Exception:
                fcp = None
            if not fcp: continue
            for k, (d, l, mg) in enumerate(fcp, 1):
                r = vrows.setdefault(d, {"m": [None] * 7, "s": [None] * 7}); r["m"][k - 1] = round(l, 3)
                if (Jp + dt.timedelta(days=1), d) in sp_runs: r["s"][k - 1] = round(sp_runs[(Jp + dt.timedelta(days=1), d)], 3)   # SPINE archivée le lendemain de J (jour d'émission réel)
        vdays = [{"date": d.isoformat(), "obs": round(hist[d]["frontenac_zc"], 3), "ice": int(pf.is_ice(d)), **vrows[d]} for d in sorted(vrows) if d in hist and hist[d]["frontenac_zc"] is not None]
        with open(os.path.join(DOCS, "validation.json"), "w", encoding="utf-8") as f:
            json.dump({"generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "days": vdays}, f, separators=(",", ":"))
    except Exception as e:
        print("validation.json impossible :", e)
    # ------------------------------------------------------------------ archive des débits aux centrales d'Hydro-Québec
    # Débit total horaire (turbiné + déversé) à Carillon, Beauharnois, Les Cèdres, etc. Données ouvertes d'Hydro-Québec
    # (CC BY-NC 4.0), historique offert : 10 jours seulement → on archive pour pouvoir tester plus tard si ces débits,
    # mesurés à la source 3 à 6 h avant que les niveaux amont ne réagissent, améliorent J+1 et J+2. Non utilisé par le modèle.
    try:
        import requests
        HQ = os.path.join(DOCS, "hq_hourly.csv")
        url = "https://donnees.hydroquebec.com/api/explore/v2.1/catalog/datasets/donnees-hydrometriques/exports/json"
        rows = requests.get(url, timeout=60, params={"where": 'depil_json_type_point_donnee="Débit total" and depil_json_pas_temps="Horaire" and ycoord<46.6 and xcoord<-73.3 and xcoord>-78',
                                                     "select": "nom,split_date,split_value"}).json()
        arch = {}
        if os.path.exists(HQ):
            with open(HQ, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f): arch[r["time_utc"]] = {k: v for k, v in r.items() if k != "time_utc"}
        for r in rows:
            try:
                t = r["split_date"].replace("/", "-")[:13] + ":00Z"; arch.setdefault(t, {})[r["nom"]] = f"{float(r['split_value']):.1f}"
            except (KeyError, TypeError, ValueError):
                pass
        lim = (dt.datetime.utcnow() - dt.timedelta(days=400)).strftime("%Y-%m-%dT%H:00Z")
        arch = {t: v for t, v in arch.items() if t >= lim}; cols = sorted({k for v in arch.values() for k in v})
        with open(HQ, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["time_utc"] + cols); [w.writerow([t] + [arch[t].get(c, "") for c in cols]) for t in sorted(arch)]
        print("archive Hydro-Québec :", len(arch), "heures,", len(cols), "installations")
    except Exception as e:
        print("archive Hydro-Québec impossible :", e)
    # ------------------------------------------------------------------ combinaison automatique modèle + SPINE
    # Pour chaque échéance k (jours entre l'émission, en heure locale, et la date visée), on relit les archives et on
    # ajuste obs ≈ a + w·modèle + (1−w)·SPINE sur les couples où le niveau réel est connu. Dès 30 couples, la prévision
    # affichée devient ce mélange, avec une marge mesurée sur ses propres erreurs. Les poids se recalculent à chaque exécution.
    combo = {}
    try:
        def last_runs(name):
            out = {}
            with open(os.path.join(DOCS, name), newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    iloc = (dt.datetime.strptime(r["issued_utc"], "%Y-%m-%dT%H:%MZ") + pf.TZ).date()
                    out[(iloc, dt.date.fromisoformat(r["target_date"]))] = float(r["level_zc"])     # dernière exécution du jour
            return out
        fa, sp_a = last_runs("forecast_archive.csv"), last_runs("spine_archive.csv")
        pairs = {}
        for (iloc, td), mval in fa.items():
            if (iloc, td) in sp_a and td in hist and hist[td]["frontenac_zc"] is not None:
                pairs.setdefault((td - iloc).days, []).append((mval, sp_a[(iloc, td)], hist[td]["frontenac_zc"]))
        for k, P in pairs.items():
            if len(P) < 30 or not (0 <= k <= 7): continue
            x = [mv - sv for mv, sv, o in P]; y = [o - sv for mv, sv, o in P]; n = len(P)
            mx, my = sum(x) / n, sum(y) / n; sxx = sum((xi - mx) ** 2 for xi in x)
            w = (sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / sxx) if sxx > 1e-9 else 1.0
            w = min(max(w, 0.0), 1.0); a = my - w * mx
            ec = [o - (a + w * mv + (1 - w) * sv) for mv, sv, o in P]; em = [o - mv for mv, sv, o in P]; es = [o - sv for mv, sv, o in P]
            rm = lambda v: round((sum(t * t for t in v) / len(v)) ** 0.5, 3)
            p90 = round(sorted(abs(t) for t in ec)[int(0.9 * (len(ec) - 1))], 3)
            combo[str(k)] = {"w_model": round(w, 2), "a": round(a, 3), "n": n, "rmse_model": rm(em), "rmse_spine": rm(es), "rmse_combo": rm(ec), "p90": p90}
        if combo:
            new = []
            for d, l, m in fc:
                k = str((d - d1).days); c = combo.get(k)
                if c and d in spine: new.append((d, c["a"] + c["w_model"] * l + (1 - c["w_model"]) * spine[d], c["p90"]))
                else: new.append((d, l, m))
            fc = new
            print("combinaison modèle+SPINE active :", {k: (v["w_model"], v["n"]) for k, v in combo.items()})
    except FileNotFoundError:
        pass
    except Exception as e:
        print("combinaison impossible :", e)
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
    air = fetch_air()
    # niveau des 24 dernières heures au pas de 5 minutes (graphique « aujourd'hui »)
    fine = []
    try:
        import requests
        t1 = dt.datetime.utcnow(); t0 = t1 - dt.timedelta(hours=24)
        r = requests.get(f"{pf.API}/{pf.ST['fr']}/data", timeout=40, params={"time-series-code": "wlo", "from": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "to": t1.strftime("%Y-%m-%dT%H:%M:%SZ"), "resolution": "FIVE_MINUTES"})
        fine = [{"t": p["eventDate"], "v": round(p["value"], 3)} for p in r.json()]
    except Exception as e:
        print("série 5 min indisponible :", e)
    # ------------------------------------------------------------------ auto-évaluation de la tendance du débit
    # archive : (date d'émission J, jour cible, variation prévue vs débit du jour J) ; évaluation : variation observée
    # (débit journalier LaSalle, hist) -> fiabilité du sens de la flèche par horizon, et seuil "stable" (±150 m³/s)
    QA = os.path.join(DOCS, "qtrend_archive.csv")
    q_rows = []
    if os.path.exists(QA):
        with open(QA, newline="", encoding="utf-8") as f:
            q_rows = [(r["issued_day"], r["target_date"], float(r["dq_forecast"])) for r in csv.DictReader(f)]
    if q_fc and J in q_las:
        issued_day = J.isoformat()
        q_rows = [r for r in q_rows if r[0] != issued_day]           # une seule émission par jour J (la dernière)
        q_rows += [(issued_day, row["date"], float(row["q"] - q_las[J])) for row in q_fc]
    with open(QA, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["issued_day", "target_date", "dq_forecast"])
        for r in q_rows: w.writerow([r[0], r[1], f"{r[2]:.0f}"])
    def sign(x): return 0 if abs(x) < 150 else (1 if x > 0 else -1)
    qskill = {}
    stats = {}
    for iss, tgt, dqf in q_rows:
        di, dtg = dt.date.fromisoformat(iss), dt.date.fromisoformat(tgt)
        if di in hist and dtg in hist and hist[di]["lasalle_q"] is not None and hist[dtg]["lasalle_q"] is not None:
            k = (dtg - di).days; dqo = hist[dtg]["lasalle_q"] - hist[di]["lasalle_q"]
            st = stats.setdefault(k, {"n": 0, "ok": 0, "abs_err": 0.0})
            st["n"] += 1; st["ok"] += int(sign(dqf) == sign(dqo)); st["abs_err"] += abs(dqf - dqo)
    for k, st in stats.items():
        if st["n"] >= 10:
            qskill[str(k)] = {"n": st["n"], "hit": round(st["ok"] / st["n"], 2), "mae": round(st["abs_err"] / st["n"])}
    days60 = [d for d in sorted(hist) if d <= J][-60:]
    # ------------------------------------------------------------------ comparaison mesuré / prévu (14 derniers jours)
    # modèle : prévision J+1 rejouée avec les seules données disponibles la veille (identique à ce qui a été publié) ;
    # SPINE : prévision J+1 archivée la veille (se remplit au fil des jours)
    spine_j1 = {}
    try:
        with open(os.path.join(DOCS, "spine_archive.csv"), newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                td = dt.date.fromisoformat(r["target_date"]); idate = dt.date.fromisoformat(r["issued_utc"][:10])
                if (td - idate).days == 1: spine_j1[td] = float(r["level_zc"])
    except FileNotFoundError:
        pass
    compare = []
    for d in days60[-14:]:
        Jp = d - dt.timedelta(days=1); m = None
        try:
            fcp = replay(Jp)
            if fcp: m = round(fcp[0][1], 3)
        except Exception as e:
            print("rejeu J+1 impossible pour", d, ":", e)
        compare.append({"date": d.isoformat(), "obs": round(hist[d]["frontenac_zc"], 3) if hist[d]["frontenac_zc"] is not None else None, "model": m, "spine": (round(spine_j1[d], 3) if d in spine_j1 else None)})
    # prévisions pour demain (modèle et SPINE) pour prolonger la comparaison d'un jour
    if fc_raw:
        compare.append({"date": fc_raw[0][0].isoformat(), "obs": None, "model": round(fc_raw[0][1], 3), "spine": (round(spine[fc_raw[0][0]], 3) if fc_raw[0][0] in spine else None)})
    data = {
        "generated": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "station": "Montréal, rue Frontenac (SHC 15540)", "datum_note": "mètres au-dessus du zéro des cartes (IGLD85 = ZC + 5,35 m)",
        "day_J": J.isoformat(), "obs_J": round(h[J]["frontenac_zc"], 3), "pc_J": round(h[J]["pointeclaire_igld85"], 3), "sa_J": round(h[J]["steanne_igld85"], 3),
        "residual": round(res, 3), "ice": pf.is_ice(J), "model": model_used, "britannia_q": (round(br[J]) if J in br else None), "live": live, "water_temp": water_temp, "discharge": discharge,
        "partial_today": (round(partial["frontenac_zc"], 3) if partial and partial["frontenac_zc"] is not None else None),
        "history": [{"date": d.isoformat(), "obs": round(hist[d]["frontenac_zc"], 3)} for d in days60], "compare": compare, "hourly": hourly, "fine": fine, "spine_hourly": spine_hourly, "spine_adj": spine_adj, "skill": skill, "stat_skill": stat_skill, "q_forecast": q_fc, "qskill": qskill, "discharge_bdf": discharge_bdf, "air": air, "ms_flow": ms_flow, "q_anchor_day": (round(q_las[J]) if J in q_las else None),
        "forecast": [{"date": d.isoformat(), "level": round(l, 3), "margin": round(m, 3), "spine": (round(spine[d], 3) if d in spine else None)} for d, l, m in fc], "intraday": intraday, "combo": combo, "v3_horizons": v3_used, "v3_inputs": aux_today,
    }
    with open(os.path.join(DOCS, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"OK – J = {J}, résidu {res:+.3f} m, J+1 = {fc[0][1]:+.2f} m")


if __name__ == "__main__":
    main()
