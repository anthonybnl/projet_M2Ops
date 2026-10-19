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

## Pipeline Kestra

Kestra lance chaque étape dans un conteneur de l'image `gazette:local` :
`collecte` (flux RSS -> XML brut + JSON dans `data/raw/`) puis `nettoyage` (-> `data/clean/<date>/articles.json`).

```bash
cd containers
cp .env.example .env                    # puis renseigner DATA_DIR_HOST
docker compose --profile build build    # image gazette:local
docker compose up -d                    # Kestra sur http://localhost:8080
curl -u admin@kestra.io:Admin1234 -X POST -H 'Content-Type: application/x-yaml'      --data-binary @../kestra/flows/gazette.yml http://localhost:8080/api/v1/main/flows   # déploie le flow
```

Le flow `gazette/gazette` se lance depuis l'interface (Execute) ou tous les jours à 6h (Europe/Paris).
Les données sont stockées en local dans `data/` (ignoré par git), en attendant un bucket S3.

## Pour aller plus loin

1. Génération du requirements.txt

```bash
pip-compile pyproject.toml -o requirements.txt
```
