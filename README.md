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

4. Point d'entrée actuel

```bash
python -m la_gazette_des_sorciers.main
```

La collecte bronze se lance avec les commandes de la section suivante.

## Collecte bronze et stockage S3

La collecte utilise une seule destination, choisie par `S3_ENABLED` :

- `true` : `collecte_xml` écrit les XML et leurs métadonnées directement dans
  le bucket ; `collecte_json` y lit ces objets, les convertit et y écrit les JSON.
  Aucun fichier n'est créé dans `DATA_DIR` par ces collecteurs.
- `false` : les deux collecteurs lisent et écrivent uniquement dans `DATA_DIR`.

Le module `stockage_s3` sert à transférer vers S3 des fichiers collectés en
mode local lors d'une exécution précédente. Il n'est pas nécessaire en mode S3.

1. Copier `.env.example` vers `.env`. Le mode local (`S3_ENABLED=false`) est la
   valeur par défaut. Pour utiliser S3, définir `S3_ENABLED=true` et renseigner
   les identifiants du serveur. `.env` est ignoré par Git. `S3_ENDPOINT_URL`
   doit viser l'API S3, et non la console web. Pour RustFS local, les ports
   habituels sont `9000` et `9001`.
   Les chemins relatifs de `.env`, comme `./sources.csv` et `./data`, sont résolus
   depuis le dossier contenant `.env`, même si les scripts sont lancés ailleurs.
   Sur un poste sans bucket, conserver `S3_ENABLED=false`.

2. Démarrer RustFS dans un autre terminal PowerShell, avec les **mêmes**
   identifiants que `AWS_ACCESS_KEY_ID` et `AWS_SECRET_ACCESS_KEY` dans `.env` :

```powershell
$env:RUSTFS_ACCESS_KEY = "<access-key>"
$env:RUSTFS_SECRET_KEY = "<secret-key>"
New-Item -ItemType Directory -Force .\.local\rustfs | Out-Null
& "<chemin-vers-rustfs.exe>" server --address "127.0.0.1:9000" --console-enable --console-address "127.0.0.1:9001" ".\.local\rustfs"
```

3. Depuis la racine du projet, avec Python 3.12 et les dépendances installées :

```powershell
python -m la_gazette_des_sorciers.collecte_xml
python -m la_gazette_des_sorciers.collecte_json
```

La première commande lit `SOURCES_FILE` et crée les XML et leurs métadonnées.
La deuxième les convertit en JSON depuis la destination choisie. En mode S3,
le bucket `S3_BUCKET` est créé s'il manque. En cas d'erreur S3, la collecte
échoue et ne bascule pas automatiquement vers `DATA_DIR`.

Pour transférer plus tard les fichiers d'une collecte locale vers S3 :

```powershell
python -m la_gazette_des_sorciers.stockage_s3
```

Pour ne renvoyer qu'une journée UTC, ajouter `--date AAAA-MM-JJ`. Relancer le
dépôt sur les mêmes fichiers remplace les objets aux mêmes clés.

Les clés S3 suivent les mêmes chemins relatifs qu'en mode local, par exemple
`xml/2026-10-21/flux.xml`, `xml/2026-10-21/flux.json` et
`json/2026-10-21/flux.json`. Les métadonnées contiennent `filepath` en mode
local et `s3_key` en mode S3 pour retrouver le XML à convertir.

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
```
