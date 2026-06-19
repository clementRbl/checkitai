"""
DAG ETL CheckItAI (etape 4).

Automatise les trois etapes du pipeline d'acquisition de donnees multimodales :
    extract  -> transform -> load

Chaque etape est une tache PythonOperator distincte. Les fonctions de traitement
sont reprises des etapes 2 et 3 et incluses directement dans le DAG (recommandation
du cahier des charges). Les donnees transitent d'une tache a l'autre via XCom
(on se passe le chemin du fichier JSON produit).

Cible du chargement : base PostgreSQL dediee (service checkit-postgres).
"""

import json
import logging
import os
import re
from datetime import datetime
from urllib.parse import urlparse

import psycopg2
import requests
from airflow.operators.python import PythonOperator

from airflow import DAG

logger = logging.getLogger(__name__)

# Configuration (lue depuis l'environnement du conteneur)

API_URL = "https://newsdata.io/api/1/latest"
DATA_DIR = "/opt/airflow/data"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

# Parametres d'extraction par defaut (modifiables ici sans toucher au reste du code).
QUERY = "fake news"
LANGUAGE = "en"


# Tache 1 : EXTRACT


def extract(**context):
    """Appelle l'API NewsData.io, garde les entrees multimodales, ecrit un JSON brut.

    Renvoie le chemin du fichier produit (transmis a la tache suivante via XCom).
    """
    api_key = os.getenv("NEWS_DATA_API_KEY")
    if not api_key:
        raise ValueError("NEWS_DATA_API_KEY absente de l'environnement.")

    params = {"apikey": api_key, "q": QUERY, "language": LANGUAGE, "image": 1}
    response = requests.get(API_URL, params=params, timeout=15)
    response.raise_for_status()

    articles = []
    for item in response.json().get("results", []):
        article = {
            "id": item.get("article_id"),
            "texte": item.get("description") or item.get("content"),
            "url_image": item.get("image_url"),
            "date": item.get("pubDate"),
            "source": "newsdata.io",
            "label": None,
            "url_article": item.get("link"),
            "domaine": item.get("source_id"),
            "langue": item.get("language"),
            "auteur": item.get("creator"),
        }
        # On ne garde que les entrees ayant texte ET image.
        if article["texte"] and article["url_image"]:
            articles.append(article)

    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"newsdata_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as file:
        json.dump(articles, file, ensure_ascii=False, indent=2)

    logger.info("EXTRACT : %d articles multimodaux ecrits dans %s", len(articles), path)
    return path


# Tache 2 : TRANSFORM


def clean_text(text):
    """Retire les balises HTML et reduit les espaces multiples. None si vide."""
    if not text:
        return None
    propre = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    return propre or None


def validate_image(url):
    """Vrai si l'URL est en http(s) et son chemin se termine par une extension d'image."""
    if (
        not url
        or not isinstance(url, str)
        or not url.startswith(("http://", "https://"))
    ):
        return False
    return urlparse(url).path.lower().endswith(IMAGE_EXTENSIONS)


def normalize_date(date):
    """Convertit 'AAAA-MM-JJ HH:MM:SS' en ISO 8601. Conserve la valeur si format inattendu."""
    if not date:
        return None
    try:
        return datetime.strptime(date, "%Y-%m-%d %H:%M:%S").isoformat()
    except (ValueError, TypeError):
        return date


def transform(**context):
    """Lit le JSON brut, nettoie/valide/normalise, deduplique, ecrit un JSON propre.

    Recupere le chemin d'entree via XCom et renvoie le chemin de sortie.
    """
    raw_path = context["ti"].xcom_pull(task_ids="extract")
    with open(raw_path, "r", encoding="utf-8") as file:
        articles = json.load(file)

    transformes = []
    for a in articles:
        texte = clean_text(a.get("texte"))
        transformes.append(
            {
                **a,
                "texte": texte,
                "date": normalize_date(a.get("date")),
                "text_length": len(texte) if texte else 0,
                "has_image": validate_image(a.get("url_image")),
            }
        )

    # Validation multimodale apres nettoyage + deduplication sur l'id.
    valides = [a for a in transformes if a["texte"] and a["has_image"]]
    vus, uniques = set(), []
    for a in valides:
        if a["id"] not in vus:
            vus.add(a["id"])
            uniques.append(a)

    clean_path = raw_path.replace("newsdata_", "clean_")
    with open(clean_path, "w", encoding="utf-8") as file:
        json.dump(uniques, file, ensure_ascii=False, indent=2)

    logger.info(
        "TRANSFORM : %d articles valides/uniques ecrits dans %s",
        len(uniques),
        clean_path,
    )
    return clean_path


# Tache 3 : LOAD

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS publications (
    id           TEXT PRIMARY KEY,
    texte        TEXT,
    url_image    TEXT,
    date         TIMESTAMP,
    source       TEXT,
    label        TEXT,
    url_article  TEXT,
    domaine      TEXT,
    langue       TEXT,
    auteur       TEXT,
    text_length  INTEGER,
    has_image    BOOLEAN
);
"""

INSERT_ROW = """
INSERT INTO publications (
    id, texte, url_image, date, source, label,
    url_article, domaine, langue, auteur, text_length, has_image
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO NOTHING;
"""


def load(**context):
    """Charge les donnees transformees dans PostgreSQL.

    Cree la table si besoin et insere chaque publication. ON CONFLICT garantit
    l'idempotence : relancer le DAG ne cree pas de doublons.
    """
    clean_path = context["ti"].xcom_pull(task_ids="transform")
    with open(clean_path, "r", encoding="utf-8") as file:
        articles = json.load(file)

    connexion = psycopg2.connect(
        host=os.getenv("CHECKIT_DB_HOST"),
        dbname=os.getenv("CHECKIT_DB_NAME"),
        user=os.getenv("CHECKIT_DB_USER"),
        password=os.getenv("CHECKIT_DB_PASSWORD"),
    )
    try:
        with connexion, connexion.cursor() as curseur:
            curseur.execute(CREATE_TABLE)
            for a in articles:
                # auteur est une liste cote API : on la met a plat en texte.
                auteur = (
                    ", ".join(a["auteur"])
                    if isinstance(a.get("auteur"), list)
                    else a.get("auteur")
                )
                curseur.execute(
                    INSERT_ROW,
                    (
                        a["id"],
                        a["texte"],
                        a["url_image"],
                        a["date"],
                        a["source"],
                        a["label"],
                        a["url_article"],
                        a["domaine"],
                        a["langue"],
                        auteur,
                        a["text_length"],
                        a["has_image"],
                    ),
                )
    finally:
        connexion.close()

    logger.info("LOAD : %d publications inserees dans PostgreSQL.", len(articles))


# Definition du DAG

with DAG(
    dag_id="checkit_etl",
    description="Pipeline ETL multimodal CheckItAI : extract -> transform -> load",
    start_date=datetime(2024, 1, 1),
    schedule=None,  # declenchement manuel pour la demo
    catchup=False,
    tags=["checkitai", "etl"],
) as dag:
    extract_task = PythonOperator(task_id="extract", python_callable=extract)
    transform_task = PythonOperator(task_id="transform", python_callable=transform)
    load_task = PythonOperator(task_id="load", python_callable=load)

    # Enchainement des trois etapes.
    extract_task >> transform_task >> load_task
