#!/usr/bin/env python3
"""
Mise à jour automatique du classeur « Prevision_niveau_Frontenac_Montreal.xlsx »
=================================================================================
1. Télécharge les moyennes journalières manquantes (API IWLS de Pêches et Océans Canada) :
   Frontenac 15540, Pointe-Claire 15330, Sainte-Anne-de-Bellevue 16005, et le débit à LaSalle
   (ECCC, temps réel) quand il est disponible.
2. Écrit les observations du jour J dans les feuilles « Prévision précise » et « Prévision ».
3. Allonge l'historique de la feuille « Données » et des graphiques (30 / 60 derniers jours).
4. Récupère la prévision officielle SPINE du SHC (7 jours) pour la section 3.
5. Recrée les graphiques et enregistre. Les formules du classeur ne sont pas touchées :
   Excel recalcule tout à l'ouverture.

Usage :
    python prevision_frontenac.py                       # met à jour le classeur du même dossier
    python prevision_frontenac.py --jour 2026-11-08     # choisir le jour J (défaut : hier)
    python prevision_frontenac.py --ms 6600 --carillon 1300   # débits annoncés (facultatif)
    python prevision_frontenac.py --sans-excel          # affiche seulement la prévision
Dépendances :  pip install requests openpyxl
"""
import argparse, datetime as dt, json, os, sys
from collections import defaultdict

try:
    import requests
except ImportError:
    sys.exit("Installez d'abord :  pip install requests openpyxl")

API = "https://api-iwls.dfo-mpo.gc.ca/api/v1/stations"
ST = {"fr": "5cebf1e03d0f4a073c4bbdee", "pc": "5cebf1e43d0f4a073c4bc480", "sa": "5cebf1e43d0f4a073c4bc478"}
DATUM = {"fr": 0.0, "pc": 20.35, "sa": 21.34}      # zéro des cartes -> IGLD85 (Frontenac reste en ZC)
IGLD_FR = 5.35
ECCC_RT = "https://api.weather.gc.ca/collections/hydrometric-realtime/items"
XLSX_DEFAULT = "Prevision_niveau_Frontenac_Montreal.xlsx"
TZ = dt.timedelta(hours=-5)                        # heure normale de l'Est (moyennes journalières)

COEF = json.loads("""{"A": [-34.02140498166089, 1.1815640362370494, 0.43540867670912087, 0.9223549813909637, -0.1092165356844234, 0.065354810141431], "phi": 0.8431782283432117, "pc_from_q": [18.35442751323613, 0.3368457274878213, 0.3744826181272054, -0.03534126920885989], "sa_from_pr": [20.608248761605104, 1.2491763410360277, 0.6174140455714654, -0.39183778459233015], "horizon": {"1": [0.048975884777334666, 0.07722882244614851, 0.08164554084848069, 0.13660157061598413, 0.07693877356845748, 0.1001094274870779, 0.08473321853267053, 0.1331624556247117], "2": [0.06769291562832261, 0.10229389381152428, 0.10965015504049867, 0.1694679597193094, 0.13449246345535168, 0.18380012343476382, 0.1403797742704948, 0.2220346911545987], "3": [0.0794910770403157, 0.12448395255414095, 0.12312637738272503, 0.1862243913799995, 0.17861025847572876, 0.24358583104040704, 0.1829308695392494, 0.2701464151316428], "4": [0.0881828770216413, 0.14011827558604656, 0.1304721301111604, 0.19986536705873248, 0.213574365870948, 0.2961143710308839, 0.21734301185164337, 0.33404494492742687], "5": [0.09402102352941243, 0.14541924020205232, 0.1360264293103305, 0.20662118955095743, 0.24078325633951103, 0.35008836880069927, 0.24423054451318027, 0.3708479526961515], "6": [0.09697592245614263, 0.1547942515472174, 0.1397500188958708, 0.21223311176677193, 0.26136427208770385, 0.3994327354441048, 0.26664769939059857, 0.376079087618911], "7": [0.09795647931744374, 0.16087795286765127, 0.1425673522384602, 0.22485759704775168, 0.27700020504330086, 0.4292162418930707, 0.28579273249487686, 0.3942810041828834], "0": [0.048975884777334666, 0.07722882244614851, 0.08164554084848069, 0.13660157061598413, 0.048975884777334666, 0.07722882244614851, 0.08164554084848069, 0.13660157061598413]}}""")
A = COEF["A"]; PHI = COEF["phi"]; ALPHA = 0.5
PC_Q = COEF["pc_from_q"]; SA_P = COEF["sa_from_pr"]
C_LAS = [-199.4202535284995, 1.0055565291686344, 0.7176847844537333]
C_PR = [396.0550290106018, 0.38389662563345395]
P90 = COEF["horizon"]


# --------------------------------------------------------------------------- modèle
def model_amont(pc, sa, ice):
    return A[0] + A[1] * pc + A[2] * sa + ice * (A[3] + A[4] * pc + A[5] * sa)


def is_ice(d):
    return 1 if d.month in (12, 1, 2, 3) else 0


# --------------------------------------------------------------------------- téléchargements
def fetch_iwls_daily(code, d0, d1, series="wlo"):
    """Moyennes journalières (jours civils heure de l'Est) entre les dates d0 et d1 incluses."""
    acc = defaultdict(list)
    t = dt.datetime.combine(d0, dt.time()) - TZ
    end = dt.datetime.combine(d1 + dt.timedelta(days=1), dt.time()) - TZ
    while t < end:
        t2 = min(t + dt.timedelta(days=7), end)
        r = requests.get(f"{API}/{ST[code]}/data", timeout=40, params={
            "time-series-code": series, "from": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": t2.strftime("%Y-%m-%dT%H:%M:%SZ"), "resolution": "SIXTY_MINUTES"})
        r.raise_for_status()
        for p in r.json():
            d = (dt.datetime.fromisoformat(p["eventDate"].replace("Z", "+00:00")).replace(tzinfo=None) + TZ).date()
            acc[d].append(p["value"])
        t = t2
    return {d: sum(v) / len(v) for d, v in acc.items() if len(v) >= 12}


def fetch_eccc_discharge_daily(station="02OA016"):
    """Débit journalier moyen (m³/s) des ~30 derniers jours, ECCC temps réel. {} si indisponible."""
    acc = defaultdict(list)
    try:
        offset = 0
        while True:
            r = requests.get(ECCC_RT, timeout=40, params={"STATION_NUMBER": station, "f": "json", "limit": 10000,
                                                         "offset": offset, "properties": "DATETIME,DISCHARGE"})
            r.raise_for_status(); j = r.json()
            for f in j["features"]:
                p = f["properties"]
                if p.get("DISCHARGE") is None: continue
                d = (dt.datetime.fromisoformat(p["DATETIME"].replace("Z", "+00:00")).replace(tzinfo=None) + TZ).date()
                acc[d].append(p["DISCHARGE"])
            if len(j["features"]) < 10000: break
            offset += 10000
    except Exception as e:
        print("  (débit LaSalle ECCC indisponible :", e, ")")
    return {d: sum(v) / len(v) for d, v in acc.items() if len(v) >= 12}


# --------------------------------------------------------------------------- prévision
def forecast(J, fr_J, pc_J, pc_J1, sa_J, sa_J1, ms=None, carillon=None):
    ice = is_ice(J)
    res = fr_J - model_amont(pc_J, sa_J, ice)
    pc_k = pc_J + ALPHA * (pc_J - pc_J1); sa_k = sa_J + ALPHA * (sa_J - sa_J1)
    known = ms is not None and carillon is not None
    if known:
        q_las = (C_LAS[0] + C_LAS[1] * ms + C_LAS[2] * carillon) / 1000
        q_pr = (C_PR[0] + C_PR[1] * carillon) / 1000
    out = []
    for k in range(1, 8):
        d = J + dt.timedelta(days=k); ice_k = is_ice(d)
        if known:
            pc_use = PC_Q[0] + PC_Q[1] * q_las + ice_k * (PC_Q[2] + PC_Q[3] * q_las)
            sa_use = SA_P[0] + SA_P[1] * q_pr + ice_k * (SA_P[2] + SA_P[3] * q_pr)
        else:
            pc_use, sa_use = pc_k, sa_k
        lvl = model_amont(pc_use, sa_use, ice_k) + PHI ** k * res
        h = P90[str(k)]
        marge = (h[3] if ice_k else h[1]) if known else (h[7] if ice_k else h[5])
        out.append((d, lvl, marge))
    return res, out


# --------------------------------------------------------------------------- Excel
def _charts(wb):
    """Recrée les 4 graphiques (openpyxl ne conserve pas les graphiques existants)."""
    from openpyxl.chart import LineChart, ScatterChart, Reference, Series
    from openpyxl.chart.series import SeriesLabel
    from openpyxl.chart.marker import Marker

    def style_line(ch, cols, dash_from=None, marker_idx=None):
        for i, (s, col) in enumerate(zip(ch.series, cols)):
            s.graphicalProperties.line.solidFill = col; s.graphicalProperties.line.width = 20000; s.smooth = False
            if dash_from is not None and i >= dash_from:
                s.graphicalProperties.line.dashStyle = "dash"; s.graphicalProperties.line.width = 12000
            if marker_idx is not None and i == marker_idx:
                s.marker = Marker(symbol="circle", size=6); s.marker.graphicalProperties.solidFill = col
        ch.display_blanks = "gap"; ch.legend.position = "b"; ch.x_axis.delete = False; ch.y_axis.delete = False
        ch.x_axis.number_format = "d mmm"; ch.x_axis.tickLblPos = "low"; ch.y_axis.title = "m (zéro des cartes)"

    # Prévision précise : lignes 41 (en-tête) .. 78
    ws = wb["Prévision précise"]; ws._charts = []
    ch = LineChart(); ch.title = "Frontenac : 30 jours observés et prévision précise à 7 jours (m, zéro des cartes)"
    ch.height = 10; ch.width = 30
    ch.add_data(Reference(ws, min_col=3, max_col=6, min_row=41, max_row=78), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=2, min_row=42, max_row=78))
    style_line(ch, ["1F3864", "C00000", "A6A6A6", "A6A6A6"], dash_from=2, marker_idx=1)
    ch.x_axis.title = "Date (jour et mois) — à gauche : observations ; points rouges : prévision"
    ch.x_axis.tickLblSkip = 4; ch.x_axis.tickMarkSkip = 4
    ws.add_chart(ch, "P4")

    # Prévision : lignes 45 (en-tête) .. 112
    ws = wb["Prévision"]; ws._charts = []
    ch = LineChart(); ch.title = "Niveau à Frontenac (m, zéro des cartes) : observé, modèle A et prévision 7 jours"
    ch.height = 11; ch.width = 30
    ch.add_data(Reference(ws, min_col=3, max_col=7, min_row=45, max_row=112), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=2, min_row=46, max_row=112))
    style_line(ch, ["1F3864", "2E75B6", "C00000", "A6A6A6", "A6A6A6"], dash_from=3, marker_idx=2)
    ch.series[1].graphicalProperties.line.dashStyle = "sysDash"
    ch.x_axis.title = "Date (jour mois)"; ch.x_axis.tickLblSkip = 7; ch.x_axis.tickMarkSkip = 7
    ws.add_chart(ch, "K4")

    # Validation
    wv = wb["Validation"]; wv._charts = []
    start, last = 9, wv.max_row
    sub0 = next((r for r in range(start + 1, last + 1) if isinstance(wv.cell(r, 1).value, dt.datetime) and wv.cell(r, 1).value.year >= 2024), start + 1)
    ch2 = LineChart(); ch2.title = "Frontenac 2024–2025 : observé vs Modèle A (m, zéro des cartes)"; ch2.height = 9; ch2.width = 28
    ch2.add_data(Reference(wv, min_col=7, max_col=8, min_row=sub0, max_row=last), titles_from_data=False)
    ch2.series[0].tx = SeriesLabel(v="Observé"); ch2.series[1].tx = SeriesLabel(v="Modèle A")
    ch2.set_categories(Reference(wv, min_col=1, min_row=sub0, max_row=last))
    ch2.x_axis.number_format = "yyyy-mm"; ch2.x_axis.tickLblSkip = 60; ch2.x_axis.tickMarkSkip = 60
    for s in ch2.series: s.smooth = False; s.graphicalProperties.line.width = 12000
    ch2.series[1].graphicalProperties.line.dashStyle = "dash"; ch2.y_axis.title = "m"; ch2.legend.position = "b"
    ch2.x_axis.delete = False; ch2.y_axis.delete = False
    wv.add_chart(ch2, "O3")
    sc = ScatterChart(); sc.title = "Validation 2019–2025 : niveau observé vs modèle A (m, zéro des cartes)"
    sc.style = 13; sc.height = 12; sc.width = 14; sc.x_axis.title = "Observé (m)"; sc.y_axis.title = "Modèle A (m)"
    s = Series(Reference(wv, min_col=8, min_row=start + 1, max_row=last), Reference(wv, min_col=7, min_row=start + 1, max_row=last), title="Jours 2019–2025")
    s.marker = Marker(symbol="circle", size=3); s.marker.graphicalProperties.solidFill = "2E75B6"; s.marker.graphicalProperties.line.noFill = True
    s.graphicalProperties.line.noFill = True; sc.series.append(s)
    s2 = Series(Reference(wv, min_col=14, min_row=41, max_row=42), Reference(wv, min_col=13, min_row=41, max_row=42), title="Parfait (1:1)")
    s2.marker = Marker(symbol="none"); s2.graphicalProperties.line.solidFill = "C00000"; s2.graphicalProperties.line.width = 15000; sc.series.append(s2)
    for ax in (sc.x_axis, sc.y_axis): ax.scaling.min = -1; ax.scaling.max = 3.5; ax.delete = False
    sc.legend.position = "b"; wv.add_chart(sc, "O24")


def update_workbook(path, J, series, q_las, spine, ms=None, carillon=None):
    from openpyxl import load_workbook
    wb = load_workbook(path)
    f_in = None
    # ---- Données : ajouter les jours manquants
    wd = wb["Données"]
    existing = {}
    for r in range(3, wd.max_row + 1):
        v = wd.cell(r, 1).value
        if isinstance(v, dt.datetime): existing[v.date()] = r
    last_row = max(existing.values()) if existing else 2
    days = sorted(set(series["fr"]) | set(series["pc"]) | set(series["sa"]))
    added = 0
    for d in days:
        if d > J: continue
        r = existing.get(d)
        if r is None:
            last_row += 1; r = last_row; added += 1
            wd.cell(r, 1, dt.datetime.combine(d, dt.time())).number_format = "yyyy-mm-dd"
        for col, key in ((2, "fr"), (3, "pc"), (4, "sa")):
            if d in series[key] and wd.cell(r, col).value is None:
                wd.cell(r, col, round(series[key][d] + DATUM[key], 3)).number_format = "0.000"
        if d in q_las and wd.cell(r, 5).value is None:
            wd.cell(r, 5, round(q_las[d], 1)).number_format = "#,##0"
    # séries complètes (classeur + nouvelles) pour les graphiques
    hist = {}
    for r in range(3, wd.max_row + 1):
        v = wd.cell(r, 1).value
        if isinstance(v, dt.datetime) and wd.cell(r, 2).value is not None:
            hist[v.date()] = (wd.cell(r, 2).value, wd.cell(r, 3).value, wd.cell(r, 4).value)
    obs_days = sorted(d for d in hist if d <= J)

    # ---- Prévision précise : entrées + SPINE + historique 30 jours
    ws = wb["Prévision précise"]
    J1 = J - dt.timedelta(days=1)
    ws["C6"] = dt.datetime.combine(J, dt.time())
    ws["C7"] = round(hist[J][0], 3)
    ws["C8"] = round(hist[J][1], 3); ws["D8"] = round(hist[J1][1], 3)
    ws["C9"] = round(hist[J][2], 3); ws["D9"] = round(hist[J1][2], 3)
    for k in range(1, 8):
        rr = 31 + k
        for cc in (5, 6): ws.cell(18 + k, cc).value = None
        if ms is not None and carillon is not None:
            ws.cell(18 + k, 5, ms); ws.cell(18 + k, 6, carillon)
        d = J + dt.timedelta(days=k)
        ws.cell(rr, 3).value = round(spine[d], 3) if d in spine else None
    ws["F31"] = f"Prévision SPINE du SHC téléchargée le {dt.date.today().isoformat()} (moyennes journalières)."
    last30 = obs_days[-30:]
    for i in range(30):
        rr = 42 + i
        if i < len(last30):
            d = last30[i]; ws.cell(rr, 2, dt.datetime.combine(d, dt.time())).number_format = "yyyy-mm-dd"; ws.cell(rr, 3, round(hist[d][0], 3)).number_format = "0.00"
        else:
            ws.cell(rr, 2).value = None; ws.cell(rr, 3).value = None
    ws["D71"] = "=C71"

    # ---- Prévision : entrées + historique 60 jours (colonnes B,C et H,I)
    wp = wb["Prévision"]
    wp["C5"] = dt.datetime.combine(J, dt.time()); wp["C9"] = round(hist[J][1], 3); wp["C10"] = round(hist[J][2], 3)
    if J in q_las: wp["C19"] = round(q_las[J])
    last60 = [d for d in obs_days if hist[d][1] is not None and hist[d][2] is not None][-60:]
    for i in range(60):
        rr = 46 + i
        if i < len(last60):
            d = last60[i]
            wp.cell(rr, 2, dt.datetime.combine(d, dt.time())).number_format = "yyyy-mm-dd"
            wp.cell(rr, 3, round(hist[d][0], 3)).number_format = "0.00"
            wp.cell(rr, 8, round(hist[d][1], 3)).number_format = "0.000"; wp.cell(rr, 9, round(hist[d][2], 3)).number_format = "0.000"
        else:
            for cc in (2, 3, 8, 9): wp.cell(rr, cc).value = None

    _charts(wb)
    wb.calculation.fullCalcOnLoad = True
    wb.save(path)
    return added


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Mise à jour du classeur de prévision Frontenac")
    ap.add_argument("--jour", help="jour J (AAAA-MM-JJ) ; défaut : hier")
    ap.add_argument("--ms", type=float, help="débit Moses-Saunders annoncé (m³/s)")
    ap.add_argument("--carillon", type=float, help="débit Carillon annoncé (m³/s)")
    ap.add_argument("--excel", default=None, help="chemin du classeur (défaut : même dossier que le script)")
    ap.add_argument("--sans-excel", action="store_true", help="ne pas modifier le classeur")
    args = ap.parse_args()

    J = dt.date.fromisoformat(args.jour) if args.jour else ((dt.datetime.utcnow() + TZ).date() - dt.timedelta(days=1))
    path = args.excel or os.path.join(os.path.dirname(os.path.abspath(__file__)), XLSX_DEFAULT)

    # période à télécharger : depuis la dernière date du classeur (ou 70 jours)
    d0 = J - dt.timedelta(days=70)
    if not args.sans_excel and os.path.exists(path):
        from openpyxl import load_workbook
        wd = load_workbook(path, read_only=True)["Données"]
        dates = [r[0] for r in wd.iter_rows(min_row=3, max_col=1, values_only=True) if isinstance(r[0], dt.datetime)]
        if dates: d0 = max(d0, max(dates).date() - dt.timedelta(days=2))
    print(f"Téléchargement des observations du {d0} au {J} ...")
    series = {k: fetch_iwls_daily(k, d0, J) for k in ST}
    q_las = fetch_eccc_discharge_daily()
    spine = {}
    try:
        spine = fetch_iwls_daily("fr", J + dt.timedelta(days=1), J + dt.timedelta(days=7), series="wlf-spine")
    except Exception as e:
        print("  (prévision SPINE indisponible :", e, ")")

    J1 = J - dt.timedelta(days=1)
    try:
        fr_J = series["fr"][J]
        pc_J, pc_J1 = series["pc"][J] + DATUM["pc"], series["pc"][J1] + DATUM["pc"]
        sa_J, sa_J1 = series["sa"][J] + DATUM["sa"], series["sa"][J1] + DATUM["sa"]
    except KeyError as e:
        sys.exit(f"Observations incomplètes pour {e} (journée pas encore terminée ?). Réessayez plus tard ou utilisez --jour.")

    res, fc = forecast(J, fr_J, pc_J, pc_J1, sa_J, sa_J1, args.ms, args.carillon)
    print(f"\nJour J = {J} : Frontenac {fr_J:+.3f} m ZC | Pointe-Claire {pc_J:.3f} | Sainte-Anne {sa_J:.3f} m IGLD85 | résidu aval {res:+.3f} m"
          + ("  ⚠ inhabituel" if abs(res) > 0.4 else ""))
    print(f"\n{'Jour':<12}{'Prévu (ZC)':>12}{'± 90 %':>9}{'IGLD85':>9}{'SPINE SHC':>11}")
    for d, lvl, marge in fc:
        sp = spine.get(d)
        print(f"{d.isoformat():<12}{lvl:>+12.2f}{marge:>9.2f}{lvl + IGLD_FR:>9.2f}{(f'{sp:+.2f}' if sp is not None else '-'):>11}")

    if not args.sans_excel:
        if not os.path.exists(path):
            sys.exit(f"\nClasseur introuvable : {path}")
        n = update_workbook(path, J, series, q_las, spine, args.ms, args.carillon)
        print(f"\nClasseur mis à jour : {path}  ({n} jour(s) ajouté(s) à la feuille Données). Ouvrez-le dans Excel : les formules se recalculent automatiquement.")


if __name__ == "__main__":
    main()
