# Rapport d'exploration de sources — Pipeline multimodal CheckItAI

**Étape 1 : acquisition de données multimodales (texte + image)**
Auteur : Ingénieur Data Junior, CheckItAI

---

## 1. Ce que je cherche

On veut alimenter le moteur de détection de fake news avec des publications qui contiennent **à la fois du texte et au moins une image**. Pas l'un ou l'autre mais les deux, dans la même entrée. C'est la contrainte qui élimine la plupart des sources classiques d'articles texte seul.

J'ai cherché des sources accessibles et licites. Je me suis fixé une règle simple : commencer par les canaux officiels (API, RSS) avant d'envisager le scraping. Le scraping marche mais c'est fragile et mal vu par les éditeurs. J'y reviens plus bas.

Un point que je veux poser tout de suite parce qu'il a guidé mes choix : on cible la **désinformation** (une info objectivement fausse, diffusée pour tromper) et pas les **opinions controversées** (un avis subjectif qui dérange). Concrètement un bon label doit dire « ce contenu est faux » et non « ce contenu choque ». Ça change tout pour juger la qualité des sources.

## 2. Comment j'ai jugé les sources

Pour repérer les sources je me suis appuyé sur les moteurs de recherche de jeux de données et d'API : **Google Dataset Search** et **Hugging Face Datasets** pour les datasets labellisés, **Kaggle** pour les jeux prêts à l'emploi, et **public-apis.io** pour les API ouvertes. J'ai croisé ça avec les médias que je lis au quotidien, ce qui m'a amené à la piste des flux RSS.

Pour chaque source je regarde six choses :

- est-ce qu'on a vraiment **texte + image associés** dans la même entrée ;
- le **format** (CSV, JSON, API) et s'il est exploitable sans bidouille ;
- la **langue** ;
- la **qualité des labels** vrai/faux et surtout d'où ils viennent ;
- les **droits d'usage** ;
- la **méthode d'extraction**, en privilégiant l'officiel.

Mon ordre de préférence pour l'extraction : **API officielle > flux RSS > scraping**. Le scraping reste le dernier recours. Un site qui change son HTML du jour au lendemain casse le collecteur et il faut le maintenir.

## 3. Les champs que je veux récupérer

Peu importe la source, je veux ramener tout le monde vers une structure commune. Voici ce qui est indispensable et ce qui est juste utile.

| Champ | Indispensable ? | À quoi il sert |
|-------|-----------------|----------------|
| `id` | oui | identifiant unique, pour dédupliquer |
| `texte` | oui | entrée du modèle NLP |
| `url_image` | oui | entrée du modèle vision |
| `date` | oui | fraîcheur et traçabilité |
| `source` | oui | d'où ça vient |
| `label` | ça dépend | vrai/faux **quand la source en fournit un fiable** |
| `url_article` | utile | lien vers l'original |
| `domaine` | utile | nom de domaine émetteur, bon signal de fiabilité |
| `langue` | utile | filtrage |
| `auteur` | utile | compte ou auteur émetteur |
| `fiabilite_declaree` | utile | score ou flair fourni par la source |

Le champ `label` n'est pas toujours rempli et c'est assumé. Seules les sources labellisées (FakeNewsNet) le remplissent vraiment. Pour les autres il reste vide.

Même logique pour `fiabilite_declaree` : c'est un champ transverse qui dépend de la source. Reddit expose un flair et un score, un flux RSS peut porter une catégorie ; NewsData.io n'expose rien de tel, donc ce champ reste vide pour cette source — c'est pourquoi il n'apparaît pas dans le schéma des données NewsData.io de l'étape 3.

Règle non négociable au moment de l'extraction : si une entrée n'a pas **et** un texte **et** une image, je la jette. Sinon je me retrouve avec des paires bancales en aval.

## 4. Les sources que je retiens

### 4.1 FakeNewsNet : le dataset labellisé

C'est ma source sérieuse côté labels. Jeu de données académique pensé pour la détection de fake news.

- **Données** : texte (titre, article) + URLs d'images + métadonnées sociales
- **Format** : CSV + scripts de collecte. Le dépôt ne livre pas tout le contenu directement. Il donne des identifiants qu'il faut « ré-hydrater » via des appels.
- **Langue** : anglais
- **Labels** : très bons. Ils viennent de **PolitiFact** et **GossipCop** donc de fact-checkers humains. C'est ce qui se rapproche le plus d'une vraie vérité terrain.
- **Droits** : usage recherche et éducatif, à citer.
- **Extraction** : récupération depuis GitHub + ré-hydratation par API.

Le bémol que j'anticipe : la ré-hydratation. Une partie des URLs d'articles ou d'images aura expiré depuis la publication du dataset. Je m'attends à perdre des entrées au passage. C'est le prix d'un dataset daté.

### 4.2 NewsData.io : l'API d'actualités

Une API d'actualités citée dans les ressources du projet. Elle renvoie du JSON propre avec un champ `image_url`. C'est exactement ce que je veux pour un premier script automatisé.

- **Données** : titre, description, contenu + `image_url`
- **Format** : API REST vers JSON
- **Langue** : multilingue (FR et EN dispo)
- **Labels** : aucun. C'est un flux d'actu brut « à analyser ».
- **Droits** : clé API obligatoire et **quotas** sur l'offre gratuite (typiquement un nombre limité de requêtes par jour). Il faudra paginer intelligemment et ne pas cramer le quota en tests.
- **Extraction** : `requests` avec gestion de la clé, de la pagination et des quotas.

C'est la source la plus facile à automatiser proprement. Pas de vérité terrain mais c'est normal : elle nourrit le moteur, elle ne l'entraîne pas.

### 4.3 Reddit : le flux social

Réseau social cité dans les recommandations. Les subreddits d'actu (`r/news`, `r/worldnews`) regorgent de posts texte + image.

- **Données** : titre, `selftext` + image du post
- **Format** : API REST vers JSON via la lib `PRAW`
- **Langue** : surtout anglais
- **Labels** : rien d'officiel. Au mieux des signaux faibles (score des votes, flair, subreddit).
- **Droits** : API officielle avec OAuth, conditions d'utilisation à respecter.
- **Extraction** : `PRAW` donc API officielle et pas de scraping.

Deux choses à surveiller. Tous les posts n'ont pas d'image (il faut filtrer ceux qui en ont vraiment une exploitable) et le label via les votes ne vaut rien comme vérité terrain. À traiter comme du signal social et pas comme une vérité.

### 4.4 Flux RSS de médias : le canal officiel le plus simple

Les grands médias publient des **flux RSS** ouverts (Le Monde, France Info, Reuters…). C'est le canal officiel par excellence : pas de clé, pas de scraping, un format standard et stable, prévu par l'éditeur pour être réutilisé.

- **Données** : titre + description/chapô + image de l'article (portée dans le flux par `media:content`, `media:thumbnail` ou une `enclosure`)
- **Format** : XML RSS/Atom, parsé en dictionnaire par `feedparser`
- **Langue** : selon le média (FR pour Le Monde/France Info, EN pour Reuters)
- **Labels** : aucun. Comme NewsData.io, c'est un flux d'actu à analyser, pas une vérité terrain.
- **Droits** : flux publics destinés à la syndication, donc usage explicitement autorisé par l'éditeur. Plus propre que de scraper le site.
- **Extraction** : `feedparser`, en ne gardant que les entrées portant réellement une image exploitable.

Deux réserves. Tous les médias n'incluent pas d'image dans leur flux (il faut choisir des flux qui le font et filtrer les entrées sans image), et la description est parfois un chapô tronqué plutôt que l'article complet — ce qui reste suffisant pour le NLP.

## 5. Synthèse

| | FakeNewsNet | NewsData.io | Reddit | Flux RSS |
|---|---|---|---|---|
| Texte + image | oui | oui (`image_url`) | oui (posts image) | oui (`media:content`) |
| Format | CSV + scripts | API / JSON | API / JSON | XML RSS/Atom |
| Langue | EN | Multi (FR/EN) | EN | FR/EN selon média |
| Labels vrai/faux | bons (fact-checkers) | aucun | aucun (signaux faibles) | aucun |
| Droits | recherche | clé + quotas | API OAuth | flux public (syndication) |
| Extraction | dépôt + API | `requests` | `PRAW` | `feedparser` |
| Rôle | entraînement supervisé | flux à analyser | flux à analyser | flux à analyser |

## 6. Format de sortie : JSON

Je pars sur du **JSON**, un objet par publication (en JSON Lines pour scaler facilement).

Pourquoi pas du CSV : les contenus mélangent du texte long, des URLs et des métadonnées parfois imbriquées. Le CSV s'en sort mal avec ça. Et puis deux de mes trois sources renvoient déjà du JSON donc autant rester dans ce format et éviter des conversions qui perdent de l'info. Le JSON encaisse aussi très bien les champs optionnels comme `label` vide.

Pour le stockage final (Étape 4), Parquet sera sûrement plus malin niveau compression et perf mais ça ne concerne pas l'acquisition. On verra le moment venu.

## 7. Ce que je recommande pour la suite

Je garde les quatre sources, elles sont complémentaires :

- **FakeNewsNet** pour les labels fiables (la seule à en avoir).
- **NewsData.io** pour un flux d'actu officiel et multilingue.
- **Reddit** pour du multimodal social via un canal officiel.
- **Flux RSS** pour du multimodal éditorial via le canal le plus léger et le plus explicitement autorisé.

Le point que je veux être clair là-dessus : **seul FakeNewsNet apporte une vérité terrain solide**. Les deux autres apportent du volume frais et multimodal mais sans label. Elles servent à alimenter le moteur et pas à l'entraîner en supervisé. Je préfère le dire franchement plutôt que de faire passer des votes Reddit pour des labels.

Pour l'Étape 2 je commence par **NewsData.io** : canal officiel, JSON natif, multimodal, et assez simple pour écrire un premier script d'extraction robuste qui tourne sans intervention. Reddit viendra ensuite comme deuxième source histoire de prouver que le pipeline est bien modulaire et pas collé à une seule API.
