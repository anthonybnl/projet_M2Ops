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

## Supervision

Stack : Prometheus + Alertmanager + Grafana (+ Loki). Les services sont derrière le profil Compose `supervision` : ils ne démarrent pas avec le pipeline.

1. Créer le fichier secret de l'URL du webhook d'alerte

```bash
cp infra/secrets/webhook_url.example infra/secrets/webhook_url
```

Puis remplacer son contenu par l'URL réelle (une seule ligne).

2. Démarrer la supervision

```bash
docker compose -f infra/docker-compose.yml --profile supervision up -d
```

3. Interfaces

| Service | URL |
| --- | --- |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| Grafana | http://localhost:3000 |
| Loki | http://localhost:3100 |

4. Arrêter la supervision

```bash
docker compose -f infra/docker-compose.yml --profile supervision down
```

## Pour aller plus loin

1. Génération du requirements.txt

```bash
pip-compile pyproject.toml -o requirements.txt
```
