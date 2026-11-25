# Prévision du niveau du Saint-Laurent à Montréal (rue Frontenac)

Site statique (GitHub Pages) mis à jour automatiquement deux fois par jour par GitHub Actions.

- `build_site.py` – télécharge les observations (API IWLS du SHC, ECCC), met à jour `docs/history.csv`,
  calcule la prévision J+1 → J+7 et écrit `docs/data.json`.
- `prevision_frontenac.py` – modèle et fonctions de téléchargement (sert aussi à mettre à jour le classeur Excel).
- `docs/index.html` – la page web (lit `data.json`).
- `coefs_v3.json`, `coefs_intraday.json`, `coefs_v4.json` – coefficients des modèles. v4 (depuis le 25 nov. 2026) recale la
  prévision v3 du dernier jour complet sur les dernières heures mesurées ; v3 + ajustement intrajournalier reste le repli.
- `analyse/` – reconstitution des données 2019-2026 et tests des modèles :
  `python analyse/telecharger.py` (données publiques, dans `analyse/data/`, non versionné ; besoin de `requests` et `numpy`),
  puis depuis `analyse/` : `python fit_v4.py eval` (site actuel contre v4, par année), `python fit_v4.py export`
  (réécrit `coefs_v4.json`), `python fit_v4.py parite` (le code du site donne la même valeur que l'analyse),
  `python test_emulation.py` (l'émulation du site reproduit l'archive publiée).
- `.github/workflows/update.yml` – l'automatisation (06:40 et 12:40, heure de Montréal, + bouton « Run workflow »).

## Mise en route (une seule fois)

1. Créer un dépôt GitHub et y déposer tous ces fichiers (en gardant les dossiers `docs/` et `.github/workflows/`).
2. **Settings → Pages → Build and deployment** : *Source = Deploy from a branch*, *Branch = main*, dossier **/docs** → Save.
3. **Settings → Actions → General → Workflow permissions** : cocher *Read and write permissions* → Save.
4. Onglet **Actions** → « Mise à jour de la prévision » → **Run workflow** pour la première exécution.

Le site est ensuite accessible à `https://<ton-pseudo>.github.io/<nom-du-depot>/`.

Données : Service hydrographique du Canada (licence ouverte) et Environnement et Changement climatique Canada. Outil indicatif, non officiel.
