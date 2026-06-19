"""
Extraction automatisee de publications multimodales (texte + image) depuis l'API NewsData.io.

Etape 2 du projet CheckItAI. Le script est decoupe en fonctions independantes
(connexion, parsing, nettoyage, sauvegarde) et s'execute sans intervention manuelle :

    python src/extraction_newsdata.py --query "climat" --langue fr --pages 1

La cle API est lue depuis le fichier .env (variable NEWS_DATA_API_KEY).
La sortie est un fichier JSON ecrit dans le dossier data/.
"""

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

# Configuration generale

# Endpoint "latest" de NewsData.io : renvoie les actualites recentes.
API_URL = "https://newsdata.io/api/1/latest"

# Dossier de sortie (gitignore : les donnees ne sont pas poussees sur GitHub).
DATA_DIR = Path("data")

# Logging : on trace chaque etape plutot que d'utiliser des print.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# 1. Connexion


def load_api_key():
    """Lit la cle API NewsData.io depuis le fichier .env.

    On centralise la lecture de la cle ici pour ne jamais l'ecrire en dur
    dans le code (bonne pratique de securite). Leve une erreur explicite
    si la cle est absente, pour eviter un appel API qui echouerait sans raison claire.
    """
    load_dotenv()
    api_key = os.getenv("NEWS_DATA_API_KEY")
    if not api_key:
        raise ValueError(
            "Cle API absente. Renseignez NEWS_DATA_API_KEY dans le fichier .env."
        )
    return api_key


def call_api(api_key, query, language, page=None):
    """Appelle l'API NewsData.io et renvoie la reponse JSON brute.

    Parametres :
        api_key  : cle API
        query    : mot-cle de recherche
        language : code langue (ex. "fr", "en")
        page     : jeton de pagination renvoye par l'appel precedent (None au 1er appel)

    On gere les erreurs reseau et les codes d'erreur HTTP (dont le 429 = quota depasse)
    pour que le script ne plante pas brutalement.
    """
    params = {"apikey": api_key, "q": query, "language": language, "image": 1}
    if page:
        params["page"] = page

    try:
        response = requests.get(API_URL, params=params, timeout=15)
        response.raise_for_status()
    except requests.exceptions.HTTPError as error:
        if response.status_code == 429:
            logger.error("Quota API depasse (HTTP 429). Reessayez plus tard.")
        else:
            logger.error("Erreur HTTP lors de l'appel API : %s", error)
        raise
    except requests.exceptions.RequestException as error:
        logger.error("Erreur reseau lors de l'appel API : %s", error)
        raise

    return response.json()


# 2. Parsing


def parse_articles(response_json):
    """Transforme la reponse brute en liste de publications au format de notre contrat de donnees.

    On mappe uniquement les champs definis. Le label reste vide :
    NewsData.io ne fournit pas de verite terrain vrai/faux.
    """
    articles = []
    for item in response_json.get("results", []):
        articles.append(
            {
                "id": item.get("article_id"),
                "texte": item.get("description") or item.get("content"),
                "url_image": item.get("image_url"),
                "date": item.get("pubDate"),
                "source": "newsdata.io",
                "label": None,  # pas de label vrai/faux sur cette source
                "url_article": item.get("link"),
                "domaine": item.get("source_id"),
                "langue": item.get("language"),
                "auteur": item.get("creator"),
            }
        )
    return articles


# 3. Nettoyage


def filter_multimodal(articles):
    """Ne garde que les entrees reellement multimodales : texte ET image presents.

    C'est la regle du projet : une publication sans texte ou sans image
    n'a pas d'interet pour un detecteur multimodal, on l'ecarte.
    """
    kept = [a for a in articles if a["texte"] and a["url_image"]]
    logger.info(
        "Filtrage multimodal : %d retenus sur %d articles.",
        len(kept),
        len(articles),
    )
    return kept


# 4. Sauvegarde


def save_json(articles, folder=DATA_DIR):
    """Ecrit la liste des articles dans un fichier JSON horodate.

    L'horodatage dans le nom de fichier evite d'ecraser une extraction precedente.
    """
    folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = folder / f"newsdata_{timestamp}.json"

    try:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(articles, file, ensure_ascii=False, indent=2)
    except OSError as error:
        logger.error("Echec de l'ecriture du fichier %s : %s", path, error)
        raise

    logger.info("%d articles sauvegardes dans %s", len(articles), path)
    return path


# Orchestration


def main():
    """Enchaine les etapes : connexion, appel, parsing, filtrage, sauvegarde.

    Les parametres sont configurables en ligne de commande pour que le script
    tourne sans modifier le code.
    """
    parser = argparse.ArgumentParser(
        description="Extraction NewsData.io (texte + image)."
    )
    parser.add_argument("--query", default="fake news", help="Mot-cle de recherche.")
    parser.add_argument("--langue", default="en", help="Code langue (ex. fr, en).")
    parser.add_argument(
        "--pages", type=int, default=1, help="Nombre de pages a recuperer."
    )
    args = parser.parse_args()

    api_key = load_api_key()
    logger.info(
        "Demarrage extraction : query=%r langue=%r pages=%d",
        args.query,
        args.langue,
        args.pages,
    )

    all_articles = []
    page = None
    for page_number in range(args.pages):
        response = call_api(api_key, args.query, args.langue, page)
        articles = parse_articles(response)
        all_articles.extend(filter_multimodal(articles))
        logger.info("Page %d traitee.", page_number + 1)

        # Jeton de pagination pour l'appel suivant ; on s'arrete s'il n'y en a plus.
        page = response.get("nextPage")
        if not page:
            break

    save_json(all_articles)
    logger.info(
        "Extraction terminee : %d articles multimodaux au total.",
        len(all_articles),
    )


if __name__ == "__main__":
    main()
