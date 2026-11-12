# Qualité du traitement bronze vers silver

Les fonctions de `normalisation.py` retirent le HTML et les blocs script/style,
décodent les entités, réparent les mots présentant un encodage UTF-8 mal interprété,
normalisent les espaces et convertissent les dates en UTC. Un fuseau explicite est
requis pour les dates. Les valeurs `guid` et `category` sous forme `#text` sont prises
en charge, ainsi que les canaux RSS contenant un seul item.

Les paramètres sont regroupés dans `ConfigurationNettoyage`, dans
`regles_nettoyage.py`. La version `v2` conserve la totalité de l'extrait fourni
par le flux après normalisation. Le seuil Jaccard est 0,85 et le taux maximal de rejet par source
est 80 %. Les arguments du script permettent de les modifier. Une modification
des paramètres ou des règles doit être accompagnée d'une nouvelle `version_regles`.

## Règles initiales

| Identifiant | Ce qui est écarté | Pourquoi | Exemple |
|---|---|---|---|
| `R01_publi` | Mentions de partenariat ou de publi-reportage dans le titre, les rubriques ou l'extrait complet | Contenu promotionnel | « Contenu partenaire » |
| `R02_horoscope` | Horoscope ou astrologie dans le titre ou les rubriques | Hors périmètre de la gazette | « Horoscope du jeudi » |
| `R03_programme_tv` | Programmes TV dans le titre ou les rubriques | Hors périmètre | « Les programmes TV de ce soir » |
| `R04_jeux_concours` | Jeux concours, mots fléchés, mots croisés ou sudoku | Hors périmètre | « Jeu concours du mois » |
| `R05_titre_vide` | Titre vide après normalisation | Article inexploitable | `<p> </p>` |
| `R06_date_invalide` | Publication absente, illisible ou sans fuseau | Impossible de vérifier sa fraîcheur | Article avec seulement un titre et un lien |
| `R07_date_future` | Publication après la date de référence UTC | Date incohérente | Publication en 2027 pendant un traitement en 2026 |
| `R08_lien_invalide` | Lien absent, sans hôte HTTP(S), avec espaces ou identifiants | Lien inexploitable | `javascript:alert(1)` |
| `R09_doublon_exact` | Même identité ou lien par source, ou même titre normalisé le même jour UTC entre médias | Éviter les reprises identiques | Même dépêche dans deux flux |
| `R10_doublon_proche` | Titres dont la similarité Jaccard atteint le seuil le même jour UTC | Éviter les reprises proches | Même titre avec un mot supplémentaire |
| `R11_encodage` | Caractère Unicode de remplacement restant dans le titre ou l'extrait | Texte altéré dont l'information est perdue | `Actualit�` |

Les dates absentes ne sont pas remplacées par la date de collecte. Le dédoublonnage
compare les candidats qui ont passé les autres règles aux articles déjà retenus.
Une même identité est conservée à sa première acceptation. Une future politique
de mise à jour devra préciser le traitement des articles corrigés par leur média.

Les motifs sont des heuristiques à ajuster sur les données réelles. Les expressions
régulières et les seuils sont visibles dans le module dédié. Le rapprochement des
titres utilise les ensembles de mots normalisés et le rapport intersection/union.

## Rapports et contrôles

Chaque passage produit deux rapports JSON horodatés dans `rapports/`, associés au
même `execution_id`. Le premier contient les
volumes entrés, gardés et rejetés, les chiffres par source et par règle, les cinq
motifs les plus fréquents et les résultats des contrôles.

Le second, avec le suffixe `-par-regle.json`, présente les règles avec leur libellé,
leur nombre de rejets et la répartition par source. Toutes les règles connues
figurent dans ce rapport, même celles à zéro. `taux_sur_entres` rapporte ce nombre
au total des entrées et `part_des_rejets` au total des articles rejetés. Ces valeurs
sont des proportions entre 0 et 1.

Un item déclenchant plusieurs règles compte une fois dans le total rejeté et une
fois pour chaque règle. `declenchements_regles` additionne ces occurrences et peut
donc dépasser le nombre d'articles rejetés, comme la somme des parts par règle peut
dépasser 100 %.

Les contrôles portent sur les résultats du passage et vérifient les titres non
vides, l'absence de dates futures, les volumes non vides et un taux de rejet inférieur
ou égal au seuil pour chaque source observée. Le code de sortie est 0 si les contrôles
passent, 2 si au moins un échoue et 1 si la lecture ou le traitement est interrompu.
Les résultats et le rapport restent disponibles en cas d'échec d'un contrôle.

Une erreur de métadonnées bronze ou de structure RSS interrompt le passage avec
un message explicite. Elle ne se transforme pas en une fausse réussite à zéro item.
Un canal RSS valide mais vide produit un rapport dont le contrôle de volume échoue.

Le chargement recalcule les contrôles sur les lignes insérées dans PostgreSQL pour
l'exécution concernée. Le rapport reprend son `execution_id`. La tâche
d'orchestration, les métriques exposées et les alertes vers un canal d'équipe
restent à intégrer à l'exploitation.

## Ajustements à consigner

Pour chaque ajustement, noter la date, la version, le motif observé dans le rapport,
le paramètre ou la règle modifiée et l'effet attendu. Les dix cas ci-dessus servent
de point de départ aux fixtures. Ils devront être complétés par les pollueurs
effectivement observés dans les collectes quotidiennes.
