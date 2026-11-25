#!/usr/bin/env python3
"""Reconstitue les données d'analyse dans analyse/data/ (sources publiques, voir README du dépôt).
  horaire_<code>.csv : niveaux horaires IWLS (UTC) Frontenac, Pointe-Claire, Sainte-Anne, Varennes, depuis 2019
  eccc_<station>.csv : moyennes journalières ECCC (HYDAT puis wateroffice) : Britannia, Hull, Lanoraie, Richelieu, LaSalle
  cmi.csv            : registre des changements de débit du lac Ontario (CMI)
Usage : python analyse/telecharger.py   (reprend là où il s'est arrêté)"""
import csv, datetime as dt, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import requests
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"); os.makedirs(D, exist_ok=True)
API = "https://api-iwls.dfo-mpo.gc.ca/api/v1/stations"
ST = {"fr": "5cebf1e03d0f4a073c4bbdee", "pc": "5cebf1e43d0f4a073c4bc480", "sa": "5cebf1e43d0f4a073c4bc478", "var": "5cebf1e03d0f4a073c4bbe04"}
START = dt.datetime(2019, 1, 1)

def get(url, params, tries=5):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code == 200: return r
        except Exception as e:
            pass
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"échec {url} {params}")

def iwls(code):
    p = os.path.join(D, f"horaire_{code}.csv"); have = {}
    if os.path.exists(p):
        with open(p, newline="") as f: have = {r["time_utc"]: r["level"] for r in csv.DictReader(f)}
    t0 = max((dt.datetime.strptime(max(have), "%Y-%m-%dT%H") - dt.timedelta(days=2)) if have else START, START)
    end = dt.datetime.utcnow(); chunks = []
    while t0 < end: chunks.append((t0, min(t0 + dt.timedelta(days=7), end))); t0 += dt.timedelta(days=7)
    def one(c):
        r = get(f"{API}/{ST[code]}/data", {"time-series-code": "wlo", "from": c[0].strftime("%Y-%m-%dT%H:%M:%SZ"), "to": c[1].strftime("%Y-%m-%dT%H:%M:%SZ"), "resolution": "SIXTY_MINUTES"})
        return [(x["eventDate"][:13], x["value"]) for x in r.json()]
    with ThreadPoolExecutor(3) as ex:
        for res in ex.map(one, chunks):
            for t, v in res: have[t] = f"{float(v):.3f}"
    with open(p, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time_utc", "level"]); [w.writerow([t, have[t]]) for t in sorted(have)]
    print(code, len(have), "heures", min(have), "→", max(have), flush=True)

def eccc(st):
    out = {}
    off = 0
    while True:
        j = get("https://api.weather.gc.ca/collections/hydrometric-daily-mean/items", {"STATION_NUMBER": st, "f": "json", "limit": 5000, "offset": off, "datetime": "2019-01-01/..", "properties": "DATE,LEVEL,DISCHARGE"}).json()
        for f in j["features"]:
            q = f["properties"]; out[q["DATE"]] = [q.get("LEVEL"), q.get("DISCHARGE")]
        if len(j["features"]) < 5000: break
        off += 5000
    # complément (années récentes) : service de données journalières du Bureau de l'eau
    for i, par in ((0, "level"), (1, "flow")):
        try:
            t = get("https://wateroffice.ec.gc.ca/services/daily_data/csv/inline", {"stations[]": st, "parameters[]": par, "start_date": "2019-01-01", "end_date": dt.date.today().isoformat()}).text
            for line in t.splitlines()[1:]:
                q = line.split(",")
                if len(q) >= 4 and q[3]:
                    row = out.setdefault(q[1], [None, None])
                    if row[i] is None: row[i] = float(q[3])
        except Exception as e:
            print("wateroffice", st, par, e)
    with open(os.path.join(D, f"eccc_{st}.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "level", "discharge"]); [w.writerow([d] + ["" if v is None else v for v in out[d]]) for d in sorted(out)]
    print(st, len(out), "jours", min(out), "→", max(out), flush=True)


def eccc_recent(st, year0=2026):
    """Complète eccc_<st>.csv après la fin de HYDAT avec les données provisoires (5 min) du Bureau de l'eau,
    moyennées par jour civil en heure normale de l'Est (comme le site)."""
    p = os.path.join(D, f"eccc_{st}.csv")
    with open(p, newline="") as f: out = {r["date"]: [r["level"], r["discharge"]] for r in csv.DictReader(f)}
    acc = {}
    t0 = dt.date(year0, 1, 1); today = dt.date.today()
    while t0 <= today:
        t1 = min(t0 + dt.timedelta(days=31), today + dt.timedelta(days=1))
        t = get("https://wateroffice.ec.gc.ca/services/real_time_data/csv/inline", {"stations[]": st, "parameters[]": ["46", "47"], "start_date": f"{t0} 00:00:00", "end_date": f"{t1} 00:00:00"}).text
        for line in t.splitlines()[1:]:
            q = line.split(",")
            if len(q) < 4 or not q[3]: continue
            tl = dt.datetime.strptime(q[1][:19], "%Y-%m-%dT%H:%M:%S") - dt.timedelta(hours=5)
            acc.setdefault((tl.date().isoformat(), 0 if q[2] == "46" else 1), []).append(float(q[3]))
        t0 = t1
    n = 0
    for (day, i), v in acc.items():
        if len(v) >= 200:   # jour presque complet (288 lectures de 5 min)
            row = out.setdefault(day, ["", ""])
            if row[i] == "": row[i] = round(sum(v) / len(v), 3); n += 1
    with open(p, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "level", "discharge"]); [w.writerow([d] + out[d]) for d in sorted(out)]
    print(st, "complété :", n, "valeurs ; dernier jour", max(out), flush=True)


if __name__ == "__main__":
    open(os.path.join(D, "cmi.csv"), "w", encoding="utf-8").write(get("https://ijc.org/sites/default/files/ChangementDebit_FlowChanges.csv", {}).text)
    for st in ("02KF005", "02LA015", "02OB011", "02OJ007", "02OA016"): eccc(st)
    for st in ("02KF005", "02LA015", "02OB011", "02OJ007"): eccc_recent(st)
    for code in ST: iwls(code)
