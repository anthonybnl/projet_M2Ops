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

4. Lancement de la pipeline

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

2. Lancement des migrations Alembic

```bash
alembic upgrade head
```

3. Création d'une migration

Après avoir modifié les modèles de la base de données dans `db_models.py` :

```bash
alembic revision --autogenerate -m "Nom de la migration"
```