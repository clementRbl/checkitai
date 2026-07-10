# CheckItAI — Pipeline d'acquisition de données multimodales

Pipeline ETL d'acquisition de données multimodales (texte + image) destiné à entraîner
un détecteur de fake news, de l'exploration des sources jusqu'au monitoring en production.

## Livrables

| # | Livrable | Fichier | Étape |
|---|----------|---------|-------|
| 1 | Rapport d'exploration de sources | [docs/rapport_exploration_sources.md](docs/rapport_exploration_sources.md) | 1 |
| 2 | Script d'extraction automatisée | [src/extraction_newsdata.py](src/extraction_newsdata.py) | 2 |
| 3 | Pipeline de transformation reproductible | [src/transformation.py](src/transformation.py) | 3 |
| 4 | Schéma de données (Mermaid) | [docs/schema_donnees.md](docs/schema_donnees.md) | 3 |
| 5 | Flux ETL Airflow | [airflow/dags/checkit_etl_dag.py](airflow/dags/checkit_etl_dag.py) | 4 |
| 6 | Tableau de bord KPI | [src/dashboard_kpi.py](src/dashboard_kpi.py) | 5 |
| 7 | Plan de monitoring | [docs/plan_monitoring.md](docs/plan_monitoring.md) | 5 |

Les quatre sources retenues (FakeNewsNet, NewsData.io, Reddit, flux RSS) sont détaillées
dans le [rapport d'exploration](docs/rapport_exploration_sources.md). L'extraction automatisée
cible NewsData.io.

## Parcours d'exécution

Toutes les étapes ci-dessous, dans l'ordre. Les sections 3 et 4 (scripts autonomes)
et la section 5 (flux Airflow) sont deux façons de faire tourner le même pipeline :

1. **Installation** des dépendances (§1)
2. **Configuration** des fichiers `.env` (§2)
3. **Extraction** → écrit un JSON brut dans `data/` (§3)
4. **Transformation** → écrit un JSON nettoyé dans `data/processed/` (§4)
5. **Flux ETL Airflow** → automatise extract → transform → load en base PostgreSQL,
   avec ses propres données dans `airflow/data/` (§5)
6. **Tableau de bord KPI** → lit la base et les fichiers d'`airflow/data/` produits par le DAG (§6)

Le schéma de données ([docs/schema_donnees.md](docs/schema_donnees.md)) et le plan de
monitoring ([docs/plan_monitoring.md](docs/plan_monitoring.md)) sont des livrables
documentaires : ils se consultent directement (le schéma Mermaid s'affiche sur GitHub).

## Prérequis

- **Python 3.12** (installé automatiquement par `uv` si absent).
- **[uv](https://docs.astral.sh/uv/)** — gestion des dépendances et de l'environnement Python.
- **Docker** (avec `docker compose`) — pour la stack Airflow de l'étape 4.
- Une **clé API [NewsData.io](https://newsdata.io/)** (offre gratuite suffisante pour la démo).

## 1. Installation

```bash
# Installer les dépendances Python dans un environnement isolé
uv sync
```

## 2. Configuration

Deux fichiers d'environnement sont nécessaires. Aucun n'est versionné (ils sont dans
`.gitignore`) ; des modèles `.env.example` sont fournis.

### `.env` à la racine (étapes 2, 3 et 5)

```bash
cp .env.example .env
```

Renseignez :

- `NEWS_DATA_API_KEY` — votre clé NewsData.io.
- `CHECKIT_DB_PASSWORD` — mot de passe de la base métier, **identique** à celui d'`airflow/.env`
  (utilisé par le tableau de bord KPI pour lire la base).

### `airflow/.env` (étape 4)

```bash
cp airflow/.env.example airflow/.env
```

Renseignez :

- `AIRFLOW_UID` — votre UID (obtenu avec `id -u`, souvent `1000` sous Linux).
- `NEWS_DATA_API_KEY` — la même clé que ci-dessus.
- `CHECKIT_DB_PASSWORD` — un mot de passe fort pour la base métier (le même que le `.env` racine).
- `AIRFLOW_FERNET_KEY` — clé de chiffrement des secrets Airflow, à générer **une seule fois** :

```bash
uv run python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

## 3. Extraction (étape 2)

Récupère des publications multimodales (texte + image) depuis NewsData.io et les enregistre
en JSON dans `data/`.

```bash
uv run python src/extraction_newsdata.py --query "fake news" --langue en --pages 1
```

Options : `--query` (mot-clé), `--langue` (code langue, ex. `fr`/`en`), `--pages` (nombre de pages).

## 4. Transformation (étape 3)

Nettoie, valide, normalise et déduplique les données extraites, puis exporte le résultat
dans `data/processed/`.

```bash
uv run python src/transformation.py
```

Par défaut, le pipeline transforme le dernier fichier brut de `data/`. On peut cibler un
fichier précis avec `--input chemin/vers/fichier.json`.

## 5. Flux ETL Airflow (étape 4)

Le DAG `checkit_etl` automatise les trois étapes (`extract` → `transform` → `load`) et charge
les données dans une base PostgreSQL dédiée. La stack tourne en local via Docker.

```bash
# Démarrer la stack (Airflow + 2 bases PostgreSQL)
docker compose --project-directory airflow -f airflow/docker-compose.yaml --env-file airflow/.env up -d
```

Une fois les conteneurs *healthy* :

- Interface web : http://localhost:8080 (identifiants par défaut `airflow` / `airflow`).
- Activer le DAG `checkit_etl` puis le déclencher depuis l'UI (bouton ▶), ou en ligne de commande :

```bash
docker exec airflow-airflow-scheduler-1 airflow dags trigger checkit_etl
```

Les publications chargées sont disponibles dans la base PostgreSQL `checkit` (port hôte `5433`).

Pour arrêter la stack :

```bash
docker compose --project-directory airflow -f airflow/docker-compose.yaml down
```

## 6. Tableau de bord KPI (étape 5)

Visualise les indicateurs du pipeline (qualité des données, rapidité, volume / coût).
Nécessite que la stack Airflow tourne et que le DAG ait été exécuté au moins une fois.

```bash
uv run streamlit run src/dashboard_kpi.py
```

Le tableau de bord s'ouvre sur http://localhost:8501. Le plan de monitoring associé est
décrit dans [docs/plan_monitoring.md](docs/plan_monitoring.md).

## Structure du projet

```
.
├── airflow/                  # Étape 4 : flux ETL Airflow
│   ├── dags/                 # DAG checkit_etl (extract → transform → load)
│   ├── docker-compose.yaml   # Stack locale (Airflow + PostgreSQL métier)
│   └── .env.example          # Modèle de configuration Airflow
├── docs/                     # Livrables documentaires (rapports, schéma, monitoring)
│   ├── pdf/                  # Versions PDF des documents
│   └── captures/             # Captures d'écran (Airflow, tableau de bord KPI)
├── src/                      # Scripts Python (extraction, transformation, dashboard)
├── data/                     # Données brutes et transformées (non versionnées)
├── .env.example              # Modèle de configuration racine
├── pyproject.toml            # Dépendances (uv)
└── README.md
```

## Format des données

Les données sont stockées en JSON, un objet par publication. Chaque entrée associe
**obligatoirement un texte et une image valides** (aucune entrée orpheline). Le schéma
conceptuel complet (champs, types, rôle dans le cas d'usage) est décrit dans
[docs/schema_donnees.md](docs/schema_donnees.md).

## Les 7 livrables

- [1. Rapport d'exploration de sources](docs/rapport_exploration_sources.md) — Markdown ([PDF](docs/pdf/rapport_exploration_sources.pdf))
- [2. Script d'extraction automatisée](src/extraction_newsdata.py) — Python
- [3. Pipeline de transformation reproductible](src/transformation.py) — Python
- [4. Schéma de données](docs/schema_donnees.md) — Mermaid ([PDF](docs/pdf/schema_donnees.pdf))
- [5. Flux ETL Airflow](airflow/dags/checkit_etl_dag.py) — Python
- [6. Tableau de bord KPI](src/dashboard_kpi.py) — Python
- [7. Plan de monitoring](docs/plan_monitoring.md) — Markdown ([PDF](docs/pdf/plan_monitoring.pdf))

Les versions PDF des trois livrables documentaires sont regroupées dans `docs/pdf/`.

## Captures d'écran

Le dossier [docs/captures/](docs/captures/) rassemble les preuves d'exécution du pipeline.

**Flux ETL Airflow (étape 4)** — le DAG `checkit_etl` et ses trois exécutions réussies :

| Capture | Contenu |
|---------|---------|
| [Liste des DAGs](docs/captures/01_airflow_liste_dags.png) | Le DAG `checkit_etl` actif, 3 exécutions |
| [Détails du DAG](docs/captures/02_airflow_dag_details.png) | 3 exécutions, 3 succès, durée moyenne 3 s |
| [Graphe du DAG](docs/captures/05_airflow_graphe_dag.png) | Enchaînement `extract → transform → load` |
| [Durée de `extract`](docs/captures/03_airflow_tache_extract_duree.png) | Durée de la tâche d'extraction par exécution |
| [Durée de `transform`](docs/captures/04_airflow_tache_transform_duree.png) | Durée de la tâche de transformation par exécution |
| [Journal d'événements](docs/captures/06_airflow_journal_evenements.png) | Historique des exécutions et de leurs états |

**Tableau de bord KPI (étape 5)** :

| Capture | Contenu |
|---------|---------|
| [Qualité et rapidité](docs/captures/07_dashboard_qualite_rapidite.png) | Publications retenues, taux de validité, durée par étape |
| [Volume et répartition](docs/captures/08_dashboard_volume_repartition.png) | Articles collectés, répartition par langue et par source |
