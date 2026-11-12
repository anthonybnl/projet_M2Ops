# Embeddings des articles avec SBERT + CamemBERT

Ce document décrit comment calculer un embedding (vecteur dense) pour chaque article collecté depuis les flux RSS, à partir du texte `titre + extrait`, avec la librairie **Sentence-Transformers (SBERT)** et un modèle **CamemBERT** entraîné pour le français.

---

## 1. Principe

- **SBERT** (Sentence-BERT) est un *bi-encoder* : chaque texte est encodé **indépendamment** en un vecteur de taille fixe (768 ou 1024 dimensions selon le modèle).
- Deux textes de sens proche donnent deux vecteurs proches. On compare avec la **similarité cosinus**.
- Une fois les articles encodés, on peut faire : recherche sémantique, détection de doublons entre sources, clustering par sujet, recommandations, etc.

```
"Grève RATP : trafic perturbé lundi"   ──►  SBERT/CamemBERT  ──►  [0.012, -0.087, ..., 0.044]  (768 floats)
```

### Attention : CamemBERT « brut » ≠ modèle SBERT

`camembert-base` (le modèle d'origine d'Inria) est un modèle de langue entraîné à deviner des mots masqués. Il **n'est pas entraîné à produire des embeddings de phrases** : si on l'utilise tel quel, les similarités obtenues sont médiocres.

Il faut un CamemBERT **fine-tuné pour la similarité de phrases** (entraînement STS / NLI), publié au format Sentence-Transformers :

| Modèle (Hugging Face)                    | Dimension | Taille     | Usage conseillé                             |
| ---------------------------------------- | --------- | ---------- | ------------------------------------------- |
| `dangvantuan/sentence-camembert-base`    | 768       | ~110 M param. (~440 Mo)  | **Point de départ recommandé** : rapide sur CPU |
| `dangvantuan/sentence-camembert-large`   | 1024      | ~335 M param. (~1,3 Go)  | Meilleure qualité, ~3× plus lent            |

> Avant de figer le choix, ouvrir la fiche du modèle sur Hugging Face pour vérifier la licence et les scores annoncés, puis noter le hash de commit (`revision`) utilisé (voir §7).

---

## 2. Installation

### 2.1 Dépendances

Ajouter dans `pyproject.toml` :

```toml
dependencies = [
  # ... dépendances existantes
  "sentence-transformers>=3.0",
  "torch>=2.2",
  "numpy",
]
```

`sentence-transformers` installe aussi `transformers`, `huggingface_hub` et `tokenizers`.

### 2.2 PyTorch en version CPU (fortement conseillé)

Par défaut, `pip install torch` sous Linux télécharge la version **CUDA** (plusieurs Go). Pour un pipeline CPU (Docker, CI), on utilise l'index CPU de PyTorch :

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

```bash
pip install sentence-transformers
```

Avec `pip-tools` (ce que le projet utilise déjà), on régénère les fichiers verrouillés en ajoutant l'index CPU :

```bash
pip-compile --extra-index-url https://download.pytorch.org/whl/cpu --output-file=requirements.txt pyproject.toml
```

```bash
pip-compile --extra=dev --extra-index-url https://download.pytorch.org/whl/cpu --output-file=requirements-dev.txt pyproject.toml
```

L'option `--extra-index-url` est alors écrite en tête de `requirements.txt`, et `pip install -r requirements.txt` (y compris dans le `Dockerfile`) récupère automatiquement la version CPU.

> Si vous avez un GPU NVIDIA en local et voulez l'utiliser, installez la version CUDA correspondante (voir https://pytorch.org/get-started/locally/). Le code ne change pas : Sentence-Transformers choisit le device automatiquement.

### 2.3 Vérification

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("dangvantuan/sentence-camembert-base")
print(model)                                     # architecture : Transformer + Pooling
print(model.get_sentence_embedding_dimension())  # 768
print(model.max_seq_length)                      # longueur max en tokens (le reste est tronqué)
print(model.device)                              # cpu / cuda
```

Au premier lancement, le modèle est téléchargé depuis Hugging Face et mis en cache dans `~/.cache/huggingface/` (ou dans `HF_HOME` si la variable est définie).

---

## 3. Premier test

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("dangvantuan/sentence-camembert-base")

phrases = [
    "Grève à la RATP : le trafic du métro très perturbé lundi",
    "Mouvement social dans les transports parisiens, plusieurs lignes à l'arrêt",
    "Le PSG s'impose face à Marseille au Parc des Princes",
]

embeddings = model.encode(phrases, normalize_embeddings=True)
print(embeddings.shape)  # (3, 768)

sim = model.similarity(embeddings, embeddings)
print(sim)
# Les deux premières phrases doivent avoir une similarité nettement plus forte
# entre elles qu'avec la troisième.
```

---

## 4. Préparer le texte des articles

### 4.1 Extraire les items du JSON

Après `collecte_json`, le flux RSS converti par `xmltodict` se trouve dans `content.rss.channel.item`.

Deux pièges propres à `xmltodict` :

1. Si le flux ne contient **qu'un seul** `<item>`, `item` est un **dict** et non une liste.
2. Si une balise a des attributs, sa valeur devient un dict (`{"@attr": ..., "#text": ...}`).

```python
def lister_items(document: dict) -> list[dict]:
    channel = document["content"]["rss"]["channel"]
    items = channel.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return items


def texte_de(valeur) -> str:
    """Récupère le texte d'un champ xmltodict (str, dict avec #text, ou None)."""
    if valeur is None:
        return ""
    if isinstance(valeur, dict):
        return valeur.get("#text", "") or ""
    return str(valeur)
```

> Le flux RSS peut aussi être Atom (`feed` / `entry` / `summary`) selon les sources. Si c'est le cas, prévoir une branche spécifique.

### 4.2 Nettoyer le texte

Le champ `<description>` des flux RSS contient souvent du HTML (`<p>`, `<img>`, entités `&eacute;`, mentions « L'article … est apparu en premier sur … »). Il faut le nettoyer avant l'encodage :

```python
import html
import re

RE_BALISES = re.compile(r"<[^>]+>")
RE_ESPACES = re.compile(r"\s+")


def nettoyer(texte: str) -> str:
    texte = html.unescape(texte)          # &eacute; -> é, &amp; -> &
    texte = RE_BALISES.sub(" ", texte)    # supprime les balises HTML
    texte = RE_ESPACES.sub(" ", texte)    # espaces / retours à la ligne multiples
    return texte.strip()
```

(Pour du HTML plus complexe, `BeautifulSoup(texte, "html.parser").get_text(" ")` est plus robuste.)

### 4.3 Concaténer titre + extrait

```python
def texte_article(item: dict) -> str:
    titre = nettoyer(texte_de(item.get("title")))
    extrait = nettoyer(texte_de(item.get("description")))
    if titre and extrait:
        return f"{titre}. {extrait}"
    return titre or extrait
```

Remarques :

- Le séparateur `". "` aide le modèle à voir deux phrases distinctes (mieux qu'une simple concaténation sans ponctuation).
- **Troncature** : tout ce qui dépasse `model.max_seq_length` tokens est coupé silencieusement. Le titre étant placé en premier, il est toujours conservé. Un titre + extrait RSS tient généralement dans la limite, mais à vérifier (§4.4).
- **Doublons** : un même article peut apparaître dans plusieurs collectes successives. Utiliser `guid` (ou `link` à défaut) comme identifiant pour ne pas le ré-encoder.

### 4.4 Vérifier la longueur en tokens

```python
nb_tokens = [len(model.tokenizer(t)["input_ids"]) for t in textes]
trop_longs = sum(n > model.max_seq_length for n in nb_tokens)
print(f"max={max(nb_tokens)}, tronqués={trop_longs}/{len(textes)}")
```

---

## 5. Calculer les embeddings en lot

```python
import logging

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("embeddings")

NOM_MODELE = "dangvantuan/sentence-camembert-base"

_model: SentenceTransformer | None = None


def charger_modele() -> SentenceTransformer:
    """Charge le modèle une seule fois (le chargement prend plusieurs secondes)."""
    global _model
    if _model is None:
        logger.info("Chargement du modèle %s", NOM_MODELE)
        _model = SentenceTransformer(NOM_MODELE)
    return _model


def encoder(textes: list[str], batch_size: int = 32) -> np.ndarray:
    model = charger_modele()
    return model.encode(
        textes,
        batch_size=batch_size,
        normalize_embeddings=True,   # vecteurs de norme 1 -> cosinus = produit scalaire
        convert_to_numpy=True,
        show_progress_bar=True,
    ).astype(np.float32)
```

Points importants :

- **Encoder par lots** (une liste de textes) plutôt qu'en boucle article par article : c'est beaucoup plus rapide.
- **`normalize_embeddings=True`** : la similarité cosinus devient un simple produit scalaire, ce qui simplifie le stockage et la recherche (et c'est ce qu'attendent la plupart des index vectoriels).
- **Charger le modèle une seule fois** par exécution, pas à chaque article.
- `batch_size` : 16 à 64 sur CPU. Augmenter si vous avez de la RAM ou un GPU.

### Exemple de bout en bout

```python
documents = [...]  # JSON produits par collecte_json (local ou S3)

articles = []
for doc in documents:
    for item in lister_items(doc):
        texte = texte_article(item)
        if not texte:
            continue
        articles.append({
            "id": texte_de(item.get("guid")) or texte_de(item.get("link")),
            "source_id": doc["source_id"],
            "texte": texte,
        })

# Dédoublonnage sur l'identifiant
articles = list({a["id"]: a for a in articles}.values())

vecteurs = encoder([a["texte"] for a in articles])
for article, vecteur in zip(articles, vecteurs, strict=True):
    article["embedding"] = vecteur
```

---

## 6. Stocker les embeddings

### Option A : PostgreSQL + pgvector (recommandé, le projet utilise déjà Postgres)

L'extension [`pgvector`](https://github.com/pgvector/pgvector) ajoute un type `vector(n)` et des index de recherche par similarité.

1. Utiliser une image Postgres qui contient l'extension, par exemple `pgvector/pgvector:pg17` dans `compose.yaml` (à aligner sur la version de Postgres actuelle).
2. Ajouter le paquet Python `pgvector` (intégration SQLAlchemy).
3. Créer la table via une migration Alembic :

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE article_embedding (
    article_id   TEXT PRIMARY KEY,
    modele       TEXT NOT NULL,        -- ex : dangvantuan/sentence-camembert-base@<revision>
    embedding    vector(768) NOT NULL,
    cree_le      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index HNSW pour la recherche par similarité cosinus
CREATE INDEX ON article_embedding USING hnsw (embedding vector_cosine_ops);
```

Modèle SQLAlchemy :

```python
from pgvector.sqlalchemy import Vector
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

class ArticleEmbedding(Base):
    __tablename__ = "article_embedding"

    article_id: Mapped[str] = mapped_column(String, primary_key=True)
    modele: Mapped[str] = mapped_column(String)
    embedding = mapped_column(Vector(768))
```

Recherche des 5 articles les plus proches d'une requête :

```python
requete = encoder(["manifestation contre la réforme des retraites"])[0]

stmt = (
    select(ArticleEmbedding.article_id,
           ArticleEmbedding.embedding.cosine_distance(requete).label("distance"))
    .order_by("distance")
    .limit(5)
)
```

(`cosine_distance` = 1 − similarité cosinus : plus c'est petit, plus c'est proche.)

### Option B : fichiers Parquet / NumPy sur S3

Pour une couche « silver/gold » sans base vectorielle : un fichier Parquet par jour avec les colonnes `article_id`, `source_id`, `embedding` (liste de float32). Simple et peu coûteux, mais la recherche se fait en chargeant les vecteurs en mémoire (suffisant pour quelques dizaines de milliers d'articles).

---

## 7. Bonnes pratiques

- **Même modèle partout** : les embeddings de deux modèles différents (ou de deux versions) ne sont **pas comparables**. Stocker le nom du modèle avec chaque vecteur et tout ré-encoder en cas de changement.
- **Figer la version du modèle** pour la reproductibilité :
  ```python
  SentenceTransformer(NOM_MODELE, revision="<hash du commit sur Hugging Face>")
  ```
- **Cache du modèle en Docker** : sans précaution, le modèle est re-téléchargé à chaque conteneur. Deux solutions :
  - le télécharger au build :
    ```dockerfile
    ENV HF_HOME=/models
    RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('dangvantuan/sentence-camembert-base')"
    ```
  - ou monter un volume sur `HF_HOME` dans `compose.yaml`.
- **Mode hors ligne** en production une fois le modèle en cache : `HF_HUB_OFFLINE=1`.
- **N'encoder que les nouveaux articles** : vérifier en base les `article_id` déjà présents avant d'appeler `encoder`.
- **Taille de l'image Docker** : torch CPU ajoute plusieurs centaines de Mo ; le modèle base ~440 Mo. Rester sur torch CPU sauf besoin réel de GPU.
- **Configuration** : mettre `NOM_MODELE` dans le `.env` (comme `DATA_DIR`) pour pouvoir le changer sans toucher au code.

---

## 8. Tests

Ne pas charger le vrai modèle dans les tests unitaires (lent, nécessite le réseau). Tester séparément :

- l'extraction et le nettoyage du texte (`lister_items`, `texte_de`, `nettoyer`, `texte_article`) : fonctions pures, faciles à tester ;
- la fonction d'encodage avec un faux modèle :

```python
import numpy as np

class FauxModele:
    def encode(self, textes, **kwargs):
        return np.ones((len(textes), 768), dtype=np.float32)

def test_encoder(monkeypatch):
    monkeypatch.setattr("la_gazette_des_sorciers.embeddings._model", FauxModele())
    vecteurs = encoder(["a", "b"])
    assert vecteurs.shape == (2, 768)
```

Un test d'intégration (marqué `@pytest.mark.slow`) peut charger le vrai modèle et vérifier que deux phrases synonymes sont plus proches qu'une phrase hors sujet.

---

## 9. Récapitulatif

1. `pip install torch --index-url https://download.pytorch.org/whl/cpu` puis `pip install sentence-transformers`.
2. Modèle : `dangvantuan/sentence-camembert-base` (pas `camembert-base`).
3. Texte : `titre + ". " + extrait`, HTML nettoyé, entités décodées, dédoublonné par `guid`.
4. `model.encode(textes, batch_size=32, normalize_embeddings=True)` → `np.ndarray (n, 768)`.
5. Stockage dans Postgres avec `pgvector` (`vector(768)` + index HNSW cosinus), en conservant le nom/version du modèle.
