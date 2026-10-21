# projet_M2Ops

Réalisation d'une pipeline de gazette matinale automatisée

[`Document de cadrage du projet`](./docs/cadrage.md)

[Fichier `sources.csv`](./sources.csv)

## Contribution

1. Création d'un environnement virtuel `python`

```bash
python -m venv .venv
```

2. Activation de l'environnement virtuel

Linux:

`source .venv/bin/activate`

Windows:

`.\.venv\Scripts\activate`

3. Installation des dépendances

```bash
pip install -e ".[dev]"
```

4. Configuration de l'environnement

Créer un fichier `.env` à la racine du projet (ignoré par git) avec l'URL de la base de données, correspondant au `docker-compose.yml` :

```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/la_gazette_des_sorciers
```

5. Lancement de la base de données

```bash
docker compose up -d db
```

La base PostgreSQL est exposée sur le port `5432`. Pour l'interface Adminer (`http://localhost:8080`, système PostgreSQL, serveur `db`) :

```bash
docker compose up -d adminer
```

6. Application des migrations Alembic

```bash
alembic upgrade head
```

7. Import des sources depuis `sources.csv`

```bash
python -m la_gazette_des_sorciers.database.import_sources
```

Le script réalise un upsert sur `id` : les sources existantes sont mises à jour (`name`, `type`, `region`, `url_flux`, `conditions`, `notes`), les nouvelles sont créées actives. Il peut être relancé sans risque. Un autre fichier CSV peut être passé en argument.

8. Lancement de la pipeline

```bash
python -m la_gazette_des_sorciers.main
```

## Docker

1. Construction de l'image Docker

```bash
docker build -t la_gazette_des_sorciers .
```

2. Lancement du conteneur Docker

```bash
docker run --rm la_gazette_des_sorciers
```

## Pour aller plus loin

1. Génération du requirements.txt

```bash
pip-compile pyproject.toml -o requirements.txt
pip-compile pyproject.toml --extra=dev -o requirements-dev.txt
```

2. Création d'une migration

Après avoir modifié les modèles de la base de données dans `db_models.py` :

```bash
alembic revision --autogenerate -m "Nom de la migration"
```