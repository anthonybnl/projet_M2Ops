# Contrat des données silver

Le schéma PostgreSQL `silver` prépare le stockage des articles nettoyés et le
suivi des traitements bronze vers silver. Les dates utilisent `TIMESTAMPTZ`.
Le service PostgreSQL du Compose utilise UTC.

## Tables

### `sources`

Une ligne décrit une source avec les identifiants de `sources.csv`.

| Colonne | Type | Rôle |
|---|---|---|
| `source_id` | TEXT, clé primaire | Identifiant du CSV |
| `nom` | TEXT | Nom du média |
| `url_flux` | TEXT | Première URL du champ `acces` |
| `type` | TEXT | Type de source, par exemple PQN ou PQR |
| `region` | TEXT | Région indiquée dans le CSV |

`02_sources.sql` charge les sources dont l'accès commence par HTTP ou HTTPS.
Sa réexécution actualise les sources présentes dans le CSV et conserve les
anciennes lignes afin de préserver les références des articles et des rejets.
Les conditions d'utilisation restent documentées dans `sources.csv`.
La présence d'une source dans le référentiel ne vaut pas autorisation de republication.

### `executions_silver`

Une ligne représente un passage du nettoyage et du contrôle bronze vers silver.

| Colonne | Type | Rôle |
|---|---|---|
| `execution_id` | BIGINT, identité, clé primaire | Identifiant du passage |
| `debut` | TIMESTAMPTZ | Début, renseigné par défaut à l'insertion |
| `fin` | TIMESTAMPTZ, nullable | Fin du passage |
| `statut` | TEXT | `en_cours`, `termine` ou `echec` |
| `version_regles` | TEXT | Version des règles appliquées |

Lorsqu'une fin est renseignée, elle est supérieure ou égale au début.
Le traitement renseignera la fin et le statut ensemble. Une reprise du même passage conserve son
identifiant. Un retraitement avec de nouvelles règles crée une nouvelle exécution.

### `articles_propres`

Une ligne représente un article accepté et identifié de manière stable dans
une source. L'exécution et la référence bronze décrivent sa première acceptation.

| Colonne | Type | Rôle |
|---|---|---|
| `article_id` | BIGINT, identité, clé primaire | Identifiant de l'article |
| `execution_id` | BIGINT, clé étrangère | Première exécution d'acceptation |
| `source_id` | TEXT, clé étrangère | Source de l'article |
| `identifiant_article` | TEXT | Identité stable préfixée `guid:` ou `url:` |
| `reference_bronze` | TEXT | URI du JSON bronze contenant le flux |
| `position_item` | INTEGER | Position dans le flux à partir de 1 |
| `date_collecte` | TIMESTAMPTZ | Valeur `fetched_at` du bronze |
| `titre` | TEXT | Titre obligatoire, contenu validé par le nettoyage |
| `extrait` | TEXT | Extrait dont la longueur sera bornée par le nettoyage |
| `lien` | TEXT | Lien HTTP ou HTTPS vers l'article |
| `date_publication` | TIMESTAMPTZ | Date publiée par la source, normalisée |
| `date_traitement` | TIMESTAMPTZ | Date d'insertion, renseignée par défaut |

Le futur nettoyage construira `identifiant_article` à partir du GUID RSS s'il
est utilisable, sinon du lien normalisé. La contrainte d'unicité sur
`(source_id, identifiant_article)` empêche sa réinsertion dans plusieurs passages.
Une seconde contrainte porte sur `(execution_id, reference_bronze, position_item)`
pour les reprises. Les champs qui composent une identité devront être déterministes.

Un article retrouvé à l'identique sera enregistré comme rejet de doublon lors du
nouveau passage. Les reprises entre médias et les titres proches nécessiteront
les règles de dédoublonnage du traitement. La politique de mise à jour d'un article
modifié devra être définie lors de cette étape pour préserver les rapports historiques.

### `rejets`

Une ligne représente un item rejeté pendant un passage, avec tous ses codes de règles.

| Colonne | Type | Rôle |
|---|---|---|
| `rejet_id` | BIGINT, identité, clé primaire | Identifiant du rejet |
| `execution_id` | BIGINT, clé étrangère | Exécution concernée |
| `source_id` | TEXT, clé étrangère | Source de l'item |
| `reference_bronze` | TEXT | URI du JSON bronze |
| `position_item` | INTEGER | Position dans le flux à partir de 1 |
| `date_collecte` | TIMESTAMPTZ | Valeur `fetched_at` du bronze |
| `regles_rejet` | TEXT[] | Liste non vide, par exemple `{R01_publi,R02_horoscope}` |
| `date_traitement` | TIMESTAMPTZ | Date d'insertion, renseignée par défaut |

La base impose au moins une règle par rejet. Le nettoyage définira le format
des codes et fournira chaque code une seule fois. Les motifs et exemples
seront documentés dans `docs/qualite.md` lors de l'implémentation des règles.
L'unicité porte sur `(execution_id, reference_bronze, position_item)`.

## Contraintes SQL et nettoyage

Les contraintes SQL se limitent aux clés primaires et étrangères, aux champs
obligatoires, aux unicités, aux trois statuts autorisés, aux positions positives,
à une fin supérieure ou égale au début et à une liste de règles non vide par rejet.
Les contrôles de texte vide, d'URL, de longueur d'extrait, de format des règles
et de dates de publication seront implémentés dans le nettoyage.

Pour initialiser PostgreSQL et ouvrir Adminer, démarrer les services depuis
le dossier contenant `compose.yaml`, avec Docker Desktop démarré.

```powershell
docker compose up -d --wait db adminer
```

Sur un volume PostgreSQL vide, Compose exécute `01_tables.sql`, puis
`02_sources.sql`. Le premier crée les tables avec les contraintes simplifiées.
Le second charge les sources depuis le CSV. Les démarrages suivants conservent
les données et utilisent les tables existantes.

## Traçabilité et rapports

Une référence bronze est une URI telle que `s3://bucket/json/date/flux.json`
ou `file:///chemin/absolu/flux.json`. Elle désigne le JSON contenant le flux entier.
`position_item` désigne sa n-ième entrée RSS, dans l'ordre du document d'origine.
Le fichier bronze doit être conservé sans modification pendant sa rétention.

Les clés étrangères garantissent l'existence des sources et des exécutions.
Le futur chargement devra garantir qu'un item d'une exécution reçoit exactement
une décision entre acceptation et rejet. Les contraintes d'unicité s'appliquent
dans chacune des deux tables et ce contrat entre tables devra être assuré par
le chargement transactionnel, y compris lors de traitements concurrents.

Pour une exécution terminée où chaque item a une décision, le total entré est
le nombre d'articles acceptés plus le nombre de rejets de cette exécution.
Un passage en échec peut contenir un traitement partiel. Les rapports utiliseront
son statut pour distinguer ce cas.

Le comptage par règle pourra utiliser la requête suivante en adaptant l'exécution.
`DISTINCT` évite de compter deux fois une même règle pour un item.

```sql
SELECT regle_id, count(*) AS nombre_items
FROM (
    SELECT DISTINCT rejet_id, unnest(regles_rejet) AS regle_id
    FROM silver.rejets
    WHERE execution_id = 101
) AS regles_par_item
GROUP BY regle_id
ORDER BY nombre_items DESC, regle_id;
```

## Qualité, fraîcheur et rétention

L'objectif du projet est une gazette disponible à 7 h sur les dernières 24 heures.
Les contrôles opérationnels des dates futures, des volumes par source et des taux
de rejet seront ajoutés avec le nettoyage et l'orchestration.

Le stockage propre est limité au titre, à l'extrait court, au lien, à la date, à la
source et aux métadonnées de traçabilité. Le schéma des rejets conserve les références
et les codes de règles. Les corps complets, auteurs et coordonnées personnelles
ne font pas partie du contrat silver.

Les durées de rétention du bronze, des articles, des rejets et des rapports ainsi
que l'archivage des éditions restent à valider avec l'équipe avant l'exploitation.
Les scripts d'initialisation conservent les données existantes à leur réexécution.
