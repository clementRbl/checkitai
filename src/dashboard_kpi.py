"""
Tableau de bord KPI du pipeline ETL CheckItAI (etape 5).

Visualise les indicateurs de performance du pipeline, lisibles par un public
non technique :
    - Precision : taux d'entrees valides (texte + image)
    - Rapidite  : duree d'execution par tache et duree totale du dernier run
    - Volume    : nombre d'articles recuperes (proxy du cout / appels API)

Sources de donnees :
    - base PostgreSQL "checkit" (donnees chargees par le DAG)
    - base de metadonnees d'Airflow (durees d'execution des taches)
    - fichiers JSON brut/propre (calcul du taux de validite)

Lancement :
    uv run streamlit run src/dashboard_kpi.py
"""

import glob
import json
import os

import altair as alt
import pandas as pd
import psycopg2
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Configuration des connexions (valeurs par defaut = setup local)

CHECKIT_DB = {
    "host": os.getenv("CHECKIT_DB_HOST", "localhost"),
    "port": os.getenv("CHECKIT_DB_PORT", "5433"),
    "dbname": os.getenv("CHECKIT_DB_NAME", "checkit"),
    "user": os.getenv("CHECKIT_DB_USER", "checkit"),
    "password": os.getenv("CHECKIT_DB_PASSWORD", "checkit"),
}

AIRFLOW_DB = {
    "host": os.getenv("AIRFLOW_DB_HOST", "localhost"),
    "port": os.getenv("AIRFLOW_DB_PORT", "5434"),
    "dbname": "airflow",
    "user": "airflow",
    "password": "airflow",
}

# Dossier des fichiers JSON produits par le DAG (volume monte par Airflow).
DATA_DIR = os.getenv("CHECKIT_DATA_DIR", "airflow/data")


# Acces aux donnees


@st.cache_data(ttl=60)
def load_publications():
    """Charge la table des publications depuis la base metier."""
    connexion = psycopg2.connect(**CHECKIT_DB)
    try:
        return pd.read_sql("SELECT * FROM publications", connexion)
    finally:
        connexion.close()


@st.cache_data(ttl=60)
def load_task_durations():
    """Recupere la duree de chaque tache pour le dernier run du DAG checkit_etl."""
    connexion = psycopg2.connect(**AIRFLOW_DB)
    requete = """
        SELECT task_id, duration
        FROM task_instance
        WHERE dag_id = 'checkit_etl'
          AND run_id = (
              SELECT run_id FROM dag_run
              WHERE dag_id = 'checkit_etl'
              ORDER BY start_date DESC LIMIT 1
          )
        ORDER BY start_date;
    """
    try:
        return pd.read_sql(requete, connexion)
    finally:
        connexion.close()


def compute_validity_rate():
    """Calcule le taux de validite = entrees propres / entrees brutes du dernier run.

    On compare le dernier fichier brut (newsdata_*.json) au dernier fichier propre
    (clean_*.json). Renvoie (nb_brut, nb_propre, taux) ou None si fichiers absents.
    """
    bruts = sorted(glob.glob(os.path.join(DATA_DIR, "newsdata_*.json")))
    propres = sorted(glob.glob(os.path.join(DATA_DIR, "clean_*.json")))
    if not bruts or not propres:
        return None
    nb_brut = len(json.load(open(bruts[-1], encoding="utf-8")))
    nb_propre = len(json.load(open(propres[-1], encoding="utf-8")))
    taux = (nb_propre / nb_brut * 100) if nb_brut else 0
    return nb_brut, nb_propre, taux


# Construction des graphiques


def bar_chart(data, x_field, x_title, y_field, y_title):
    """Construit un graphique en barres Altair avec des polices d'axes agrandies.

    On passe par Altair (et non st.bar_chart) car lui seul permet de regler la taille
    des libelles d'axes, trop petits par defaut.
    """
    return (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X(
                x_field,
                title=x_title,
                axis=alt.Axis(labelFontSize=14, titleFontSize=16),
            ),
            y=alt.Y(
                y_field,
                title=y_title,
                axis=alt.Axis(labelFontSize=14, titleFontSize=16),
            ),
        )
        .properties(height=350)
    )


def counts_dataframe(series, label):
    """Transforme un value_counts() en DataFrame a deux colonnes pour Altair."""
    return series.rename_axis(label).reset_index(name="nombre")


# Interface
# Note : les explications sont fournies via le parametre `help` de Streamlit, qui
# affiche une petite icone d'aide "?" au survol. L'interface reste ainsi epuree,
# tout en restant comprehensible par un public non technique.

st.set_page_config(page_title="KPI Pipeline CheckItAI", layout="wide")
st.title(
    "Tableau de bord du pipeline CheckItAI",
    help="Suivi de santé du pipeline qui collecte des publications (texte + image) pour "
    "entraîner un détecteur de fausses informations. Il répond à trois questions : les "
    "données sont-elles fiables, le pipeline est-il rapide, et combien produit-il de données ?",
)

publications = load_publications()
validite = compute_validity_rate()

# Bloc 1 : qualite des donnees (precision)

st.header(
    "Qualité des données",
    help="Une publication n'est utile que si elle contient à la fois un texte et une image "
    "exploitables. Voici combien de publications ont passé ce contrôle.",
)
col1, col2, col3 = st.columns(3)

col1.metric(
    "Publications retenues",
    len(publications),
    help="Nombre de publications valides enregistrées dans la base de données.",
)

if validite:
    nb_brut, nb_propre, taux = validite
    col2.metric(
        "Taux de validité",
        f"{taux:.0f} %",
        help=f"{nb_propre} publications valides sur {nb_brut} collectées. Plus ce taux est "
        "élevé, moins on perd de données. Un taux faible signale un problème côté source "
        "(image ou texte manquant).",
    )
else:
    col2.metric("Taux de validité", "N/A")

longueur_moyenne = (
    int(publications["text_length"].mean()) if not publications.empty else 0
)
col3.metric(
    "Longueur moyenne du texte",
    f"{longueur_moyenne} caractères",
    help="Taille moyenne des textes. Un texte trop court est souvent peu informatif.",
)

# Bloc 2 : rapidite

st.header(
    "Rapidité du pipeline",
    help="Le pipeline enchaîne trois étapes : collecte (extract), nettoyage (transform) et "
    "enregistrement (load). On mesure le temps de la dernière exécution, étape par étape, "
    "pour repérer une étape qui ralentit l'ensemble.",
)
durees = load_task_durations()

if not durees.empty:
    duree_totale = durees["duration"].sum()
    st.metric("Durée totale de la dernière exécution", f"{duree_totale:.2f} secondes")

    st.subheader(
        "Durée par étape",
        help="Chaque barre représente une étape du pipeline ; plus la barre est haute, "
        "plus l'étape a pris de temps.",
    )
    chart_durees = bar_chart(
        durees, "task_id:N", "Étape", "duration:Q", "Durée (secondes)"
    )
    st.altair_chart(chart_durees, use_container_width=True)
else:
    st.info("Aucune exécution du pipeline n'a encore été trouvée.")

# Bloc 3 : volume / cout

st.header(
    "Volume et coût",
    help="Quantité de données produite et consommation de l'API d'actualités. Chaque article "
    "collecté correspond à un appel, et l'API impose un quota quotidien à ne pas dépasser.",
)
col4, col5 = st.columns(2)
if validite:
    col4.metric(
        "Articles collectés",
        validite[0],
        help="Nombre d'articles récupérés via l'API lors de la dernière collecte (≈ appels consommés).",
    )
col5.metric(
    "Publications en base",
    len(publications),
    help="Total des publications valides stockées et prêtes à être exploitées.",
)

# Bloc 4 : repartitions

if not publications.empty:
    st.header(
        "Répartition des publications",
        help="D'où viennent les données : langues et sites d'actualité. Une trop forte "
        "concentration sur une seule langue ou une seule source peut biaiser le modèle.",
    )
    col6, col7 = st.columns(2)

    with col6:
        st.subheader(
            "Par langue",
            help="Chaque barre correspond à une langue ; sa hauteur indique le nombre de publications.",
        )
        langues = counts_dataframe(publications["langue"].value_counts(), "langue")
        st.altair_chart(
            bar_chart(
                langues, "langue:N", "Langue", "nombre:Q", "Nombre de publications"
            ),
            use_container_width=True,
        )

    with col7:
        st.subheader(
            "Par source",
            help="Chaque barre correspond à un site d'actualité (domaine) ayant publié les articles.",
        )
        sources = counts_dataframe(publications["domaine"].value_counts(), "domaine")
        st.altair_chart(
            bar_chart(
                sources, "domaine:N", "Source", "nombre:Q", "Nombre de publications"
            ),
            use_container_width=True,
        )
