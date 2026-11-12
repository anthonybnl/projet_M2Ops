# Lancer le nettoyage

Le module `nettoyage` lit les JSON bronze et enregistre les résultats dans
`silver.articles_propres` et `silver.rejets`. Chaque lancement crée une ligne dans
`silver.executions_silver`. Les transformations pures sont testées dans
`tests/test_normalisation.py` et `tests/test_preprocess.py`.
Les règles sont décrites dans [qualite.md](qualite.md).

Depuis la racine du dépôt, installer les dépendances de développement dans le `.venv`.

```powershell
python -m pip install -e ".[dev]"
```

## Préparation PostgreSQL

Renseigner la connexion dans `.env`, avec les identifiants du Compose.

```env
DATABASE_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/la_gazette_des_sorciers
```

Les tables silver sont initialisées par `sql/silver/01_tables.sql` au premier
démarrage sur un volume vide. Sur une base déjà créée, appliquer le script monté
dans le conteneur avec les commandes suivantes.

```powershell
docker compose up -d --wait db
docker compose exec db psql -U postgres -d la_gazette_des_sorciers -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/01_tables.sql
```

Le référentiel des sources de collecte est `public.sources`, géré par Alembic et
le module `database.import_sources`. Le script SQL silver conserve `source_id`
comme valeur de traçabilité et retire les anciennes liaisons vers `silver.sources`.

## Traitement de données bronze

Pour un fichier local, fournir son chemin avec `--fichier`. L'option peut être
répétée pour dédoublonner plusieurs fichiers et plusieurs sources ensemble.
La date de référence est l'heure UTC du passage sauf si `--maintenant` est fourni.

```powershell
python -m la_gazette_des_sorciers.nettoyage --fichier chemin/flux-a.json --fichier chemin/flux-b.json
```

Pour S3, configurer `.env` comme pour les collecteurs, avec `S3_ENABLED=1`,
`S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_REGION` et les identifiants RustFS.

```powershell
python -m la_gazette_des_sorciers.nettoyage --prefixe json/2026-11-12/
```

Sans `--fichier` ni `--prefixe`, le script utilise le préfixe JSON du jour UTC.
Il lit les objets contenant le flux converti et leurs métadonnées. Les anciens
JSON locaux contenant `filepath` et les nouveaux contenant `s3_file_key` sont
acceptés. La référence de traçabilité est celle du JSON effectivement lu.

Les commandes alimentent directement la base indiquée par `DATABASE_URL`.
L'option `--rapport` permet de choisir le chemin du rapport par source.
L'option `--rapport-regles` permet de choisir celui du second rapport, par règle.
L'extrait fourni dans `description` est conservé en entier après nettoyage HTML,
des espaces et de l'encodage. La colonne PostgreSQL est de type `TEXT`.

Les options `--seuil-doublon`, `--taux-rejet-max` et
`--version-regles` configurent le passage. Les fichiers bronze sont conservés.

## Correspondance PostgreSQL

Les colonnes produites pour les articles sont `source_id`, `identifiant_article`,
`reference_bronze`, `position_item`, `date_collecte`, `titre`, `extrait`, `lien`,
`date_publication` et `date_traitement`.

Les rejets contiennent `source_id`, `reference_bronze`, `position_item`,
`date_collecte`, `regles_rejet` et `date_traitement`.

PostgreSQL génère les clés primaires. Le chargement ajoute `execution_id` à chaque
article et rejet. Une exécution commence avec `en_cours`, puis passe à `termine`
après l'enregistrement des résultats dans une transaction commune. Une erreur
annule l'ensemble des articles et rejets du passage et marque l'exécution `echec`.

Les candidats sont comparés aux articles déjà présents. Une relance crée une
nouvelle exécution et classe les articles déjà connus parmi les rejets de doublon.
Le premier article accepté conserve son identité et sa traçabilité d'origine.
Un verrou transactionnel PostgreSQL sérialise les chargements du pipeline entre
la recherche des doublons et l'insertion pour éviter les doublons concurrents.

Les contrôles sont recalculés sur les lignes réellement insérées pour l'exécution.
Les deux rapports contiennent son identifiant et sont archivés dans `rapports/`.

- `qualite-AAAA-MM-JJ-execution-ID.json` contient les chiffres par source et les contrôles.
- `qualite-AAAA-MM-JJ-execution-ID-par-regle.json` détaille chaque règle, son libellé,
  le nombre de rejets concernés et leur répartition par source, y compris les règles à zéro.

Avec un chemin `--rapport` personnalisé, le second fichier reçoit par défaut le
suffixe `-par-regle.json` à la place de l'extension du premier.
Les articles propres et les rejets sont enregistrés dans PostgreSQL.

Un contrôle de qualité en échec donne un code de sortie 2. L'exécution reste
`termine` puisque le traitement et son stockage ont abouti. Une erreur technique
donne un code de sortie 1. Si l'archivage du rapport échoue après validation de la
transaction, le message indique l'identifiant de l'exécution déjà stockée.

## Tests

```powershell
python -m pytest
python -m ruff check .
```

Les tests PostgreSQL sont activés avec `TEST_DATABASE_URL` sur une base de test
initialisée avec le même script SQL. Ils couvrent les insertions, les relances,
les erreurs, l'annulation des résultats et les chargements concurrents.

La fixture `tests/fixtures/bronze_preprocess.json` produit deux articles propres
et cinq rejets lors d'un premier passage avec la référence temporelle
`2026-11-12T07:00:00Z`. Son utilisation avec la commande de nettoyage inscrit ces
données fictives dans la base configurée.
