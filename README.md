# CheckItAI — Pipeline d'acquisition de données multimodales

Pipeline ETL d'acquisition de données multimodales (texte + image) destiné à entraîner
un détecteur de fake news, de l'extraction jusqu'au monitoring.

## Livrables

| # | Livrable | Fichier | Étape | Statut |
|---|----------|---------|-------|--------|
| 1 | Rapport d'exploration de sources | [docs/rapport_exploration_sources.md](docs/rapport_exploration_sources.md) | 1 | ✅ |
| 2 | Script d'extraction automatisée | [src/extraction_newsdata.py](src/extraction_newsdata.py) | 2 | ✅ |
| 3 | Pipeline de transformation reproductible | [src/transformation.py](src/transformation.py) | 3 | ✅ |
| 4 | Schéma de données (Mermaid) | [docs/schema_donnees.md](docs/schema_donnees.md) | 3 | ✅ |
| 5 | Flux ETL Airflow | _à venir_ | 4 | ⏳ |
| 6 | Tableau de bord KPI | _à venir_ | 5 | ⏳ |
| 7 | Plan de monitoring | _à venir_ | 5 | ⏳ |

## Prérequis

- [uv](https://docs.astral.sh/uv/) pour la gestion des dépendances et de l'environnement Python.
- Une clé API [NewsData.io](https://newsdata.io/) renseignée dans un fichier `.env` :

```
NEWS_DATA_API_KEY=votre_cle
```

Un modèle est fourni dans [.env.example](.env.example). Le fichier `.env` n'est jamais versionné.

## Installation

```bash
uv sync
```

## Utilisation

### Extraction (étape 2)

Récupère des publications multimodales depuis NewsData.io et les enregistre en JSON dans `data/`.

```bash
uv run python src/extraction_newsdata.py --query "fake news" --langue en --pages 1
```

Options : `--query` (mot-clé), `--langue` (code langue, ex. `fr`/`en`), `--pages` (nombre de pages).

### Transformation (étape 3)

Nettoie, valide et normalise les données extraites, puis exporte le résultat dans `data/processed/`.

```bash
uv run python src/transformation.py
```

Par défaut, le pipeline transforme le dernier fichier brut de `data/`. On peut cibler un
fichier précis avec `--input chemin/vers/fichier.json`.

## Structure du projet

```
.
├── docs/                  # Rapports et schémas (livrables documentaires)
├── src/                   # Scripts Python (extraction, transformation)
├── data/                  # Données brutes et transformées (non versionnées)
├── .env.example           # Modèle de configuration
├── pyproject.toml         # Dépendances (uv)
└── README.md
```

## Format des données

Les données sont stockées en JSON. Chaque publication associe obligatoirement un texte et
une image valides. Le schéma conceptuel complet est décrit dans
[docs/schema_donnees.md](docs/schema_donnees.md).
