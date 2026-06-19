"""
Pipeline de transformation des donnees multimodales extraites (etape 3 du projet).

Le pipeline est reproductible et journalise. Il suit trois phases :
    1. Lecture   : on lit le JSON brut produit par l'extraction (etape 2).
    2. Traitement : nettoyage du texte, validation des images, normalisation des dates,
                    generation de colonnes derivees, deduplication.
    3. Export    : on ecrit le JSON nettoye dans data/processed/.

Execution sans intervention manuelle :

    python src/transformation.py --input data/newsdata_XXXX.json

Si --input n'est pas fourni, on prend automatiquement le dernier fichier brut de data/.
Les fonctions de traitement sont volontairement isolees pour etre reutilisees
directement dans le DAG Airflow de l'etape 4.
"""

import argparse
import glob
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Configuration generale

# Dossier des donnees brutes (entree) et des donnees transformees (sortie).
DATA_DIR = Path("data")
PROCESSED_DIR = DATA_DIR / "processed"

# Extensions d'image considerees comme exploitables.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# 1. Lecture


def read_raw_data(path=None):
    """Lit un fichier JSON brut produit par l'extraction.

    Si aucun chemin n'est donne, on prend le fichier d'extraction le plus recent
    dans data/ : le pipeline reste ainsi executable sans saisie manuelle.
    """
    if path is None:
        fichiers = sorted(glob.glob(str(DATA_DIR / "newsdata_*.json")))
        if not fichiers:
            raise FileNotFoundError("Aucun fichier brut newsdata_*.json dans data/.")
        path = fichiers[-1]

    with open(path, "r", encoding="utf-8") as file:
        articles = json.load(file)

    logger.info("Lecture : %d articles charges depuis %s", len(articles), path)
    return articles


# 2. Traitement


def clean_text(text):
    """Nettoie un champ texte : retire les balises HTML residuelles et les espaces multiples.

    On renvoie None si le texte est vide, pour que la validation en aval le detecte.
    """
    if not text:
        return None
    # Suppression des balises HTML eventuelles.
    sans_html = re.sub(r"<[^>]+>", " ", text)
    # Reduction des espaces multiples (espaces, tabulations, retours ligne) en un seul.
    propre = re.sub(r"\s+", " ", sans_html).strip()
    return propre or None


def validate_image(url):
    """Verifie qu'une URL d'image est exploitable.

    Regle simple et robuste : l'URL doit etre en http(s) et son chemin doit se
    terminer par une extension d'image connue. On isole le chemin avec urlparse
    pour ignorer la query string (ex. ".png?width=1200"), sinon on rejetterait
    a tort des images valides servies par un CDN par exemple.
    """
    if not url or not isinstance(url, str):
        return False
    if not url.startswith(("http://", "https://")):
        return False
    chemin = urlparse(url).path  # partie avant le "?", sans les parametres
    return chemin.lower().endswith(IMAGE_EXTENSIONS)


def normalize_date(date):
    """Convertit la date au format ISO 8601 (AAAA-MM-JJTHH:MM:SS).

    NewsData.io renvoie un format "AAAA-MM-JJ HH:MM:SS". On standardise pour
    faciliter les tris en aval.
    """
    if not date:
        return None
    try:
        dt = datetime.strptime(date, "%Y-%m-%d %H:%M:%S")
        return dt.isoformat()
    except (ValueError, TypeError):
        # Si le format est inattendu, on garde la valeur d'origine plutot que de la perdre.
        logger.warning("Date au format inattendu, conservee telle quelle : %r", date)
        return date


def transform_article(article):
    """Applique toutes les transformations a une publication et ajoute les colonnes derivees.

    Colonnes generees :
        - text_length : longueur du texte nettoye (utile pour filtrer le NLP)
        - has_image   : booleen, image validee ou non
    """
    texte = clean_text(article.get("texte"))
    image_valide = validate_image(article.get("url_image"))

    return {
        **article,
        "texte": texte,
        "date": normalize_date(article.get("date")),
        "text_length": len(texte) if texte else 0,
        "has_image": image_valide,
    }


def filter_valid(articles):
    """Ne conserve que les publications reellement multimodales apres nettoyage.

    Apres transformation, on re-verifie que texte ET image sont valides :
    le nettoyage a pu vider un texte ou la validation invalider une image.
    """
    valides = [a for a in articles if a["texte"] and a["has_image"]]
    logger.info("Validation : %d articles valides sur %d.", len(valides), len(articles))
    return valides


def deduplicate(articles):
    """Supprime les doublons sur le champ id (meme publication recuperee deux fois)."""
    vus = set()
    uniques = []
    for a in articles:
        if a["id"] not in vus:
            vus.add(a["id"])
            uniques.append(a)
    logger.info(
        "Deduplication : %d articles uniques sur %d.", len(uniques), len(articles)
    )
    return uniques


#  3. Export


def export_data(articles, folder=PROCESSED_DIR):
    """Ecrit les donnees transformees dans un fichier JSON horodate."""
    folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = folder / f"clean_{timestamp}.json"

    with open(path, "w", encoding="utf-8") as file:
        json.dump(articles, file, ensure_ascii=False, indent=2)

    logger.info("Export : %d articles ecrits dans %s", len(articles), path)
    return path


# Orchestration


def run_pipeline(input_path=None):
    """Enchaine les trois phases du pipeline et renvoie le chemin du fichier exporte."""
    articles = read_raw_data(input_path)
    transformes = [transform_article(a) for a in articles]
    valides = filter_valid(transformes)
    uniques = deduplicate(valides)
    return export_data(uniques)


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline de transformation (etape 3)."
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Chemin du JSON brut a transformer. Par defaut : le plus recent de data/.",
    )
    args = parser.parse_args()

    logger.info("Demarrage du pipeline de transformation.")
    run_pipeline(args.input)
    logger.info("Pipeline termine.")


if __name__ == "__main__":
    main()
