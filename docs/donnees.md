# Contrat des données silver

Le schéma PostgreSQL `silver` contient les articles nettoyés et le
suivi des traitements bronze vers silver. Les dates utilisent `TIMESTAMPTZ`.
Le service PostgreSQL du Compose utilise UTC.

## Tables

### `public.sources`

Une ligne décrit une source avec les identifiants de `sources.csv`.

| Colonne | Type | Rôle |
|---|---|---|
| `id` | VARCHAR, clé primaire | Identifiant du CSV, repris dans `source_id` en silver |
| `name` | VARCHAR | Nom du média |
| `url_flux` | TEXT | Première URL du champ `acces` |
| `type` | TEXT | Type de source, par exemple PQN ou PQR |
| `region` | TEXT | Région indiquée dans le CSV |

La table est créée par `alembic upgrade head`. Le module
`la_gazette_des_sorciers.database.import_sources` charge le CSV et actualise les
sources existantes. La table contient également les conditions d'utilisation,
les notes, le statut actif et les informations ETag/Last-Modified de la collecte.
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
Le traitement renseigne la fin et le statut ensemble. Chaque lancement crée une
nouvelle exécution, y compris une relance ou un retraitement avec de nouvelles règles.

### `articles_propres`

Une ligne représente un article accepté et identifié de manière stable dans
une source. L'exécution et la référence bronze décrivent sa première acceptation.

| Colonne | Type | Rôle |
|---|---|---|
| `article_id` | BIGINT, identité, clé primaire | Identifiant de l'article |
| `execution_id` | BIGINT, clé étrangère | Première exécution d'acceptation |
| `source_id` | TEXT | Identifiant de la source de collecte |
| `identifiant_article` | TEXT | Identité stable préfixée `guid:` ou `url:` |
| `reference_bronze` | TEXT | URI du JSON bronze contenant le flux |
| `position_item` | INTEGER | Position dans le flux à partir de 1 |
| `date_collecte` | TIMESTAMPTZ | Valeur `fetched_at` du bronze |
| `titre` | TEXT | Titre obligatoire, contenu validé par le nettoyage |
| `extrait` | TEXT | Extrait complet fourni par le flux, après normalisation |
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
| `source_id` | TEXT | Identifiant de la source de collecte |
| `reference_bronze` | TEXT | URI du JSON bronze |
| `position_item` | INTEGER | Position dans le flux à partir de 1 |
| `date_collecte` | TIMESTAMPTZ | Valeur `fetched_at` du bronze |
| `regles_rejet` | TEXT[] | Liste non vide, par exemple `{R01_publi,R02_horoscope}` |
| `date_traitement` | TIMESTAMPTZ | Date d'insertion, renseignée par défaut |

La base impose au moins une règle par rejet. Le nettoyage définit le format
des codes et fournit chaque code une seule fois. Les motifs et exemples
sont documentés dans `docs/qualite.md`.
L'unicité porte sur `(execution_id, reference_bronze, position_item)`.

## Contraintes SQL et nettoyage

Les contraintes SQL se limitent aux clés primaires et étrangères, aux champs
obligatoires, aux unicités, aux trois statuts autorisés, aux positions positives,
à une fin supérieure ou égale au début et à une liste de règles non vide par rejet.
Les contrôles de texte vide, d'URL, de format des règles
et de dates de publication sont réalisés dans le nettoyage.

Pour initialiser PostgreSQL et ouvrir Adminer, démarrer les services depuis
le dossier contenant `compose.yaml`, avec Docker Desktop démarré.

```powershell
docker compose up -d --wait db adminer
```

Sur un volume PostgreSQL vide, Compose exécute `01_tables.sql` pour créer les trois
tables silver. La table des sources de collecte est créée par Alembic et alimentée
par l'import Python du CSV. Les démarrages suivants conservent les données.

## Traçabilité et rapports

Une référence bronze est une URI telle que `s3://bucket/json/date/flux.json`
ou `file:///chemin/absolu/flux.json`. Elle désigne le JSON contenant le flux entier.
`position_item` désigne sa n-ième entrée RSS, dans l'ordre du document d'origine.
Le fichier bronze doit être conservé sans modification pendant sa rétention.

Les clés étrangères garantissent l'existence des exécutions. `source_id` conserve
l'identifiant de la source de collecte sans liaison SQL à l'ancien référentiel
`silver.sources`. Le chargement attribue à chaque item une décision entre acceptation
et rejet et enregistre les résultats dans une transaction commune. Un verrou
transactionnel sérialise les chargements concurrents du pipeline.

Pour une exécution terminée où chaque item a une décision, le total entré est
le nombre d'articles acceptés plus le nombre de rejets de cette exécution.
Une erreur de chargement annule les articles et rejets du passage et marque
l'exécution en échec. Les résultats des exécutions précédentes sont conservés.

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
Les contrôles des dates futures, des volumes par source et des taux de rejet
sont calculés après insertion, sur les lignes de l'exécution. L'orchestration,
l'exposition des métriques et les alertes restent à intégrer.

Le stockage propre conserve le titre, l'extrait complet fourni par le RSS, le lien, la date, la
source et aux métadonnées de traçabilité. Le schéma des rejets conserve les références
et les codes de règles. Les corps complets, auteurs et coordonnées personnelles
ne font pas partie du contrat silver.

Les durées de rétention du bronze, des articles, des rejets et des rapports ainsi
que l'archivage des éditions restent à valider avec l'équipe avant l'exploitation.
Les scripts d'initialisation conservent les données existantes à leur réexécution.
