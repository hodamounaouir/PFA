# Guide du dépôt — le rôle de chaque fichier, de A à Z

> **Ce document répond à une seule question : *« ce fichier, il sert à quoi ? »***
>
> Il ne remplace aucun des autres — il les **indexe**.
>
> | Vous cherchez… | Allez plutôt voir |
> |---|---|Icecube99??@@
> | le **quoi** et le **pourquoi fonctionnel** | [`CAHIER_DES_CHARGES.md`](../CAHIER_DES_CHARGES.md) (v4) |
> | **comment c'est structuré** (composants, flux) | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
> | **pourquoi ces choix techniques** | [`DESIGN.md`](DESIGN.md) |
> | **dans quel ordre c'est construit** | [`ROADMAP.md`](../ROADMAP.md) · [`PROGRESS.md`](../PROGRESS.md) |
> | **comment contribuer** | [`CONTRIBUTING.md`](../CONTRIBUTING.md) |
> | **comment lancer le projet** | [§16 de ce document](#16-lancer-le-projet-en-local) |

**Deux sections seulement, mais longues :**

1. [§1 → §15](#1-vue-densemble-en-une-minute) — **la carte du dépôt**, dossier par dossier, fichier par fichier.
2. [§16](#16-lancer-le-projet-en-local) — **la marche à suivre pour faire tourner le projet en local**, de zéro à la démo.

---

## 1. Vue d'ensemble en une minute

Le projet est un **pipeline Medallion sur Snowflake** (Bronze → Silver → Gold) surveillé par un
**agent LangGraph** qui détecte, diagnostique et **propose** des corrections — jamais ne les applique
sans un humain.

Le dépôt se lit donc dans le **sens du flux des données** :

```
datasets/olist.yaml ← le registre : ce que l'agent sait du dataset (aucun nom en dur dans agent/)
        │
data/         rejeu du CSV Kaggle en batchs quotidiens + nettoyage J1 + injection d'anomalies
        ▼
ingestion/    charge chaque batch dans Snowflake RAW (Bronze), sans rien transformer
        ▼
dbt/          RAW → STAGING (Silver) → MARTS (Gold), avec les tests statiques
        ▼
agent/        le cerveau : profile · detect · diagnose · propose ⏸ · apply · amend · validate · log
        │           s'appuie sur contracts/ (ce qui devrait être vrai) et écrit dans OPS.INCIDENTS
        ▼
streamlit/    les 6 écrans : voir les données, les incidents, et TRANCHER (approuver / amender / refuser)

airflow/      orchestre tout ce qui précède, un run par jour rejoué (11 tâches)
scripts/      les commandes qu'un humain tape à la main (setup, découverte, agent, décision, exports)
tests/        536 fonctions de test — sans base, sans réseau, sans LLM
benchmarks/   la baseline « dbt seul », figée, contre laquelle l'agent sera mesuré
docs/         ce document, l'architecture, le design, les ADR
```

**La règle qui explique presque tout le découpage** : *chaque couche ne connaît que la suivante, et le
SQL ne vit qu'à deux endroits* (`agent/connectors/` et `dbt/`). C'est ce qui rend l'agent générique —
brancher un second dataset ne demande **aucune ligne de Python**, seulement un `datasets/<nom>.yaml`.

---

## 2. Racine du dépôt

### 2.1 Les documents

| Fichier | Rôle |
|---|---|
| [`README.md`](../README.md) | La porte d'entrée : le problème en 30 s (le cas `sao paulo` / `são paulo`), l'architecture, le démarrage rapide, l'avancement, les limites assumées. |
| [`CAHIER_DES_CHARGES.md`](../CAHIER_DES_CHARGES.md) | **Le contrat fonctionnel (v4)** — il fait foi. Objectifs O1→O8, spécification de l'agent (§5), méthodologie de benchmark (§8), scénario de démo (§9), livrables. |
| [`ROADMAP.md`](../ROADMAP.md) | L'ordre de construction : phases 0 → 9, la *Definition of Done* de chacune, les pièges anticipés, l'ordre de sacrifice si le temps manque. |
| [`PROGRESS.md`](../PROGRESS.md) | Le journal de bord, au fil de l'eau (200 Ko). C'est là qu'on retrouve *pourquoi* une décision a été prise tel jour — et l'arrêt provisoire à la fin de la phase 6. |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Comment travailler dessus : installation, **les 7 règles non négociables** (R1→R7), où mettre quoi, workflow git, tests, format des ADR, pièges connus. |

### 2.2 La configuration et l'outillage

| Fichier | Rôle |
|---|---|
| [`pyproject.toml`](../pyproject.toml) | Le manifeste Python : nom du projet, `requires-python >=3.11,<3.12`, les 11 dépendances runtime (groq, pandas, snowflake-connector, dbt-snowflake, langgraph, langgraph-checkpoint-sqlite, pydantic, streamlit…), le groupe `dev` (pytest, ruff) et `pythonpath = ["."]` pour pytest. |
| `uv.lock` | Les versions **exactement figées** de tout l'arbre de dépendances, produites par `uv`. C'est lui qui garantit que deux machines installent le même environnement. Ne s'édite jamais à la main. |
| [`.python-version`](../.python-version) | `3.11` — la version que `uv` choisit automatiquement. |
| [`Makefile`](../Makefile) | Les six raccourcis du projet : `setup`, `test`, `lint`, `check`, et les quatre cibles dbt (`dbt-debug`, `dbt-run`, `dbt-test`, `dbt-build`). Les cibles dbt **sourcent `.env` puis entrent dans `dbt/`** — c'est le seul endroit où cet enchaînement est écrit. |
| [`.env.example`](../.env.example) | Le modèle de secrets, **versionné et sans valeurs** : `SNOWFLAKE_*` (6 variables) et `GROQ_API_KEY`. Toute nouvelle variable s'ajoute ici **et** dans `scripts/check_access.py`. |
| `.env` | Vos vrais secrets. **Jamais commité** (`.gitignore` couvre `.env*`, y compris `.env.bak` / `.env.local`). ⚠️ À enregistrer en **LF**, pas CRLF — voir [§16.3](#163-remplir-env--le-piège-crlf). |
| [`.gitignore`](../.gitignore) | Ce qui ne rentre pas dans git : secrets, `.venv/`, données (`data/olist/`, `data/incoming/`), sorties dbt (`dbt/target/`, `dbt/logs/`), checkpoints SQLite, logs Airflow. |
| [`.gitattributes`](../.gitattributes) | `* text=auto eol=lf` — force les fins de ligne LF dans tout le dépôt, parce que le code tourne dans des conteneurs Linux alors qu'il est édité sous Windows. Les `.png`/`.jpg`/`.csv` sont marqués binaires. |

### 2.3 Les fichiers générés à la racine

| Fichier | Rôle |
|---|---|
| `agent_checkpoints.sqlite` | **La mémoire des runs en pause.** Le `SqliteSaver` de LangGraph y persiste l'état complet de chaque exécution arrêtée sur `propose`. C'est ce qui fait qu'une proposition survit à un redémarrage de la machine, et que `scripts/decide.py` (ou Streamlit) peut reprendre le graphe *depuis un autre process*. Gitignoré (`*.sqlite`). |
| `.venv/` | L'environnement virtuel créé par `uv sync`. Gitignoré. *(Celui présent dans l'archive est un venv **Windows** — `.venv/Scripts/*.exe` ; sous Linux il faut le recréer, cf. [§16.2](#162-installer-lenvironnement).)* |

---

## 3. `datasets/` — le registre

Un seul fichier, et c'est **le seul à écrire pour brancher un nouveau dataset**.

| Fichier | Rôle |
|---|---|
| [`datasets/olist.yaml`](../datasets/olist.yaml) | Déclare : le `connector` à ouvrir (`snowflake`), et **les 17 tables surveillées** avec leur `layer` (bronze/silver/gold) et leur `batch_column` (`_batch_id`). Les tables Gold n'en ont pas — un agrégat est reconstruit en entier, il n'a pas de notion de lot. |

Trois choses y sont déclarées parce qu'elles **ne s'infèrent pas** : quelles tables méritent d'être
surveillées, quelle colonne identifie un lot, et à quelle couche Medallion chaque table appartient.

---

## 4. `data/` — rejeu, préparation, injection

Le pipeline **de fabrication des données**, en trois opérations distinctes. Aucune n'est jamais lue par
l'agent : c'est la condition pour que le benchmark ait un sens.

| Fichier | Rôle |
|---|---|
| [`data/config.py`](../data/config.py) | La configuration **figée** : fenêtre de rejeu `2018-03-01 → 2018-05-31` (92 jours), `REFERENCE_END_DAY = 43` (la fenêtre de référence doit rester propre), `SEED = 42`, les 4 tables quotidiennes, les 2 référentiels, et la correspondance table → nom de CSV Kaggle. **Ne pas modifier après le lancement de l'agent** : `ground_truth.yaml` s'y réfère. |
| [`data/replay.py`](../data/replay.py) | **Découpe** l'historique Olist en batchs quotidiens `data/incoming/YYYY-MM-DD/`. Au J1, livre les référentiels (products, geolocation) en entier. Applique aussi les *préparations* déclarées dans `ground_truth.yaml`. **Déterministe à l'octet près** (verrouillé par un test). |
| [`data/prepare.py`](../data/prepare.py) | **Retire** du désordre, au J1 uniquement — la seule opération qui nettoie. `geolocation_city` porte 2 042 collisions naturelles ; si l'agent apprenait son contrat dessus, il graverait le désordre comme la norme et le cas d'école du projet serait perdu avant d'avoir commencé. Le nettoyage est **déclaré** dans `ground_truth.yaml`, pas codé en dur. |
| [`data/inject.py`](../data/inject.py) | **Ajoute** du désordre : corrompt des jours choisis, après le rejeu. Une classe par type d'anomalie, seed dérivé de `data/config.py`, et un marqueur `.injected` qui **refuse de corrompre deux fois le même batch**. Sa configuration *est* `ground_truth.yaml` — une seule source, zéro divergence. |
| [`data/ground_truth.yaml`](../data/ground_truth.yaml) | ⭐ **Le contrat de vérité.** À la fois la config de l'injecteur et le corrigé du benchmark. Déclare la `preparation` (ce qu'on retire) et les anomalies datées (`schema_drift_j45`, `semantic_drift_j50`, les nulls J60/J85, les doublons J75…) avec leur dimension DAMA et leur ampleur. Règle d'honnêteté : modifiable pendant la construction, **gelé dès que l'agent est évalué**. |
| [`data/__init__.py`](../data/__init__.py) | Vide — rend `data/` importable comme paquet (`python -m data.replay`). |
| `data/olist/` | Les 9 CSV Kaggle bruts. **Non versionné** — à télécharger sur chaque machine. |
| `data/incoming/` | Les batchs produits par le rejeu, un dossier par jour. **Non versionné** — régénérable via `--seed 42`. |

---

## 5. `ingestion/` — la couche Bronze

| Fichier | Rôle |
|---|---|
| [`ingestion/load.py`](../ingestion/load.py) | Charge les batchs de `data/incoming/` dans le schéma Snowflake `RAW`. Bronze accepte **tout** : aucune transformation, aucun typage (**tout en VARCHAR**), aucun rejet de ligne. Ajoute 3 métadonnées par ligne (`_batch_id`, `_source`, `_ingested_at`), est **idempotent** (efface les lignes du batch avant de réinsérer), et **capture le schéma observé** dans `OPS._SCHEMA_HISTORY` — c'est cette table que lira `read_schema_history` pour repérer le renommage `payment_value → amount` du J45. |

Le VARCHAR partout est volontaire : si une colonne change de nom ou apparaît, l'ingestion ne casse pas.
C'est le rôle de Bronze de tout accepter ; c'est dbt qui typera.

---

## 6. `dbt/` — les transformations Silver et Gold

| Fichier | Rôle |
|---|---|
| [`dbt/dbt_project.yml`](../dbt/dbt_project.yml) | Le projet dbt `pfa_dbt` : chemins des modèles/macros/tests, et le mapping des couches — `staging` → schéma `STAGING` en **vue**, `marts` → schéma `MARTS` en **table**. |
| [`dbt/profiles.yml`](../dbt/profiles.yml) | La connexion Snowflake, **sans aucun secret en dur** : tout passe par `env_var('SNOWFLAKE_…')`, les mêmes variables que le reste du projet. C'est pourquoi les cibles `make dbt-*` sourcent `.env` avant d'appeler dbt. |
| [`dbt/macros/generate_schema_name.sql`](../dbt/macros/generate_schema_name.sql) | Neutralise le préfixe `<target_schema>_` que dbt ajoute par défaut, pour obtenir exactement les schémas Medallion `RAW` / `STAGING` / `MARTS` / `OPS`. |
| `dbt/.user.yml` · `dbt/logs/` · `dbt/target/` | Générés par dbt (identifiant anonyme, logs, artefacts de compilation dont `run_results.json` et `manifest.json`). Gitignorés. |

### 6.1 `dbt/models/staging/` — Silver

| Fichier | Rôle |
|---|---|
| [`_sources.yml`](../dbt/models/staging/_sources.yml) | Déclare les tables `RAW` comme sources dbt (c'est ce que référence `{{ source('raw', …) }}`). |
| [`_staging.yml`](../dbt/models/staging/_staging.yml) | Les tests statiques de la couche Silver (`not_null`, `unique`, `accepted_values`) — **la baseline**. |
| [`stg_orders.sql`](../dbt/models/staging/stg_orders.sql) | Commandes typées (VARCHAR → dates réelles). Les nulls injectés sur `customer_id` sont **conservés** pour que `not_null` les attrape. |
| [`stg_order_payments.sql`](../dbt/models/staging/stg_order_payments.sql) | Paiements typés. **Choix naïf assumé** : référence `payment_value`, le nom connu. Au J45 la colonne est renommée `amount` → le montant devient NULL et le test casse. C'est exactement la démonstration voulue. |
| [`stg_order_items.sql`](../dbt/models/staging/stg_order_items.sql) | Lignes de commande typées. **Pas de dédoublonnage**, volontairement : les doublons du J75 doivent survivre pour que le test `unique` les détecte. |
| [`stg_customers.sql`](../dbt/models/staging/stg_customers.sql) | ⭐ **Le trou volontaire du projet** : `customer_city` est copiée telle quelle, sans normaliser casse ni accents. Un data engineer normal n'a aucune raison de deviner que `são paulo` et `sao paulo` sont la même ville — c'est ce que l'agent doit trouver. |
| [`stg_geolocation.sql`](../dbt/models/staging/stg_geolocation.sql) | Référentiel géo typé (coordonnées en flottants). Même trou de casse laissé sur `geolocation_city`. |
| [`stg_products.sql`](../dbt/models/staging/stg_products.sql) | Référentiel produits typé. |

### 6.2 `dbt/models/marts/` — Gold

| Fichier | Rôle |
|---|---|
| [`_marts.yml`](../dbt/models/marts/_marts.yml) | Les tests statiques de la couche Gold. |
| [`fct_daily_sales.sql`](../dbt/models/marts/fct_daily_sales.sql) | CA et nombre de commandes par jour d'achat. Au J45 le CA chute : l'anomalie devient **visible métier**. |
| [`fct_avg_order_value.sql`](../dbt/models/marts/fct_avg_order_value.sql) | Panier moyen par jour. |
| [`fct_delivery_delays.sql`](../dbt/models/marts/fct_delivery_delays.sql) | Délais de livraison par commande (réel vs estimé). |
| [`fct_sales_by_city_state.sql`](../dbt/models/marts/fct_sales_by_city_state.sql) | Ventes par ville/état du client. NB : `customer_city` est déjà en ASCII pur chez Olist — le fan-out **ne se voit pas ici**. |
| [`fct_geolocation_by_city.sql`](../dbt/models/marts/fct_geolocation_by_city.sql) | ⭐ **Le démonstrateur du trou sémantique.** Une même métropole éclate en `são paulo` / `sao paulo` / `sãopaulo`, chacune avec sa part de points géo. **Aucun test baseline ne couvre ce cas** — impossible à écrire sans connaître les fautes à l'avance. C'est la table que l'agent doit faire parler. |

### 6.3 `dbt/tests/generic/`

| Fichier | Rôle |
|---|---|
| [`no_semantic_collisions.sql`](../dbt/tests/generic/no_semantic_collisions.sql) | Le test générique maison : deux écritures d'une même valeur. C'est **la règle que la baseline ne savait pas exprimer** — `not_null`, `unique` et `accepted_values` passent tous alors que le total par ville est faux. C'est aussi la seule façon de générer cette règle **sans faire entrer du SQL dans `agent/`**. |

---

## 7. `contracts/` — ce qui *devrait* être vrai

| Fichier | Rôle |
|---|---|
| `contracts/olist/*.v1.yaml` | **17 contrats**, un par table déclarée dans le registre — 6 en `RAW.`, 6 en `STAGING.`, 5 en `MARTS.`. Chacun décrit, colonne par colonne : le `role` inféré (`identifier`, `categorical`, `temporal`, `measure`…), et les clauses (`not_null`, `unique`, `accepted_values`, `no_semantic_collisions`, bornes). Versionnés dans git — un contrat est un objet de revue, pas une ligne en base. |

⚠️ **Ils sont tous en `status: proposed`.** Un contrat `proposed` **ne gouverne rien** :
`loader.charger()` ne le rend jamais. C'est le principe P3 — la machine propose, l'humain signe. Tant
que rien n'est approuvé, les familles de détection `contrat` restent muettes. (Le fil rouge São Paulo,
lui, n'en dépend pas : la famille sémantique lit le **rôle du profil**, pas le contrat.)

---

## 8. `agent/` — le cœur du projet

C'est le plus gros dossier, et le plus structuré. Deux invariants le gouvernent :
**aucun nom de table ou de colonne en dur**, et **le SQL n'existe que dans `agent/connectors/`**.

### 8.1 `agent/` (racine)

| Fichier | Rôle |
|---|---|
| [`__init__.py`](../agent/__init__.py) | Une ligne de docstring — le paquet. |
| [`state.py`](../agent/state.py) | **L'état partagé** `AgentState` (TypedDict) qui circule entre les nœuds. Chaque nœud reçoit l'état complet et retourne un **dictionnaire partiel**. Détail structurant : `logs: Annotated[list, add]` rend le journal *append-only par construction* — un nœud ne peut pas réécrire l'histoire, même par erreur (P5). Contient aussi les constantes de décision (`DECISION_APPROVED`, `DECISION_AMEND`, `DECISION_REJECTED`). |
| [`graph.py`](../agent/graph.py) | **Le câblage.** Ajoute les 8 nœuds, les arêtes, les 2 arêtes conditionnelles (`route_after_detect`, `route_after_propose`) et le `SqliteSaver`. N'ajoute **aucune logique métier** : le câblage est lui-même la garantie P3. Expose `build_agent()`, `thread(thread_id)` et la file des runs en attente. `CHECKPOINT_DB` y est défini. |
| [`llm.py`](../agent/llm.py) | **La frontière avec le LLM** — le seul endroit du projet qui appelle un modèle. Isolé pour être moquable en test, remplaçable (Groq / Cortex), et pour que R1 (« le LLM n'est appelé que dans `Diagnose` ») se vérifie d'un `grep`. |
| [`config.py`](../agent/config.py) | **Les seuils de détection**, et rien d'autre. `FENETRE_HISTORIQUE_LOTS = 30`, le plancher anti-démarrage-à-froid, les seuils de z-score… Changer une valeur ici rend l'agent plus ou moins **bavard**, jamais plus ou moins **autonome** — la distinction est tout l'objet du projet (ADR 008). Regroupés dans un seul fichier pour que chaque chiffre du benchmark soit rattachable au réglage qui l'a produit. |
| [`registry.py`](../agent/registry.py) | Charge et **valide** `datasets/<nom>.yaml`. Expose `Registre`, `TableDeclaree`, `charger()` et l'exception `RegistreInvalide`. C'est lui qui répond à « quelles tables surveiller, avec quelle colonne de lot, à quelle couche ». |
| [`incidents.py`](../agent/incidents.py) | **La signature d'une anomalie** — ce qui définit « la même anomalie ». Pièce centrale de la mémoire dans les deux sens : ce que l'agent *retrouve* (O7) et ce sur quoi il se *tait* (le silence après un refus). |
| [`freshness.py`](../agent/freshness.py) | La fraîcheur d'une colonne temporelle, **sans aucune requête** : c'est une *interprétation* des `min`/`max` déjà présents dans le profil. |
| [`impact.py`](../agent/impact.py) | **L'impact d'un écart** — la ligne dont dépend la décision. « 1 ligne sur 351 » semble négligeable jusqu'à voir « panier moyen 42,30 → 65,00 (+53,7 %) ». Sans ce champ, l'humain n'approuve pas : il signe. |
| [`corrections.py`](../agent/corrections.py) | **L'invariant P6** : ce qu'une correction a le droit de faire. L'agent peut isoler, mettre à NULL, exclure d'un agrégat, normaliser — **jamais deviner** (`8000` → `80`). Une substitution devinée est rejetée par `apply` *même après approbation humaine*. |
| [`sql_guard.py`](../agent/sql_guard.py) | Le garde-fou sur le SQL proposé par le modèle. **Première ligne de défense, pas la dernière** : il *constate* ; c'est `apply` qui *refuse d'exécuter*. |
| [`dbt_results.py`](../agent/dbt_results.py) | Lit les verdicts de dbt (`run_results.json`). Les échecs dbt sont des anomalies **déjà confirmées** : inutile que l'agent les redécouvre. |
| [`hitl.py`](../agent/hitl.py) | ⭐ **La voie unique de reprise** d'un run en pause. `scripts/decide.py` **et** les boutons Streamlit passent tous deux par ici (`proposition`, `trancher`, `questionner`). Une seconde voie de reprise serait une voie non testée. |

### 8.2 `agent/nodes/` — les 8 nœuds du graphe

Chaque nœud est une fonction pure `AgentState → dict`, donc testable **sans graphe, sans checkpointer,
sans Snowflake**.

| Fichier | LLM ? | Rôle |
|---|:-:|---|
| [`__init__.py`](../agent/nodes/__init__.py) | — | Expose les 8 nœuds. |
| [`profile.py`](../agent/nodes/profile.py) | ❌ | Mesure le lot du jour et le range dans l'historique (`OPS._PROFILES`). **Aucun nom de table ni de colonne n'y apparaît** : tout vient du registre et de l'état. |
| [`detect.py`](../agent/nodes/detect.py) | ❌ | Orchestre les 5 familles de détection. `detect` **constate**, il ne juge pas : il ne dit jamais « c'est une anomalie », il dit « ceci s'écarte de la référence R, de tant ». |
| [`diagnose.py`](../agent/nodes/diagnose.py) | ✅ | **Le seul nœud qui appelle le LLM.** Statistiques agrégées + métadonnées + lineage + incidents passés → diagnostic structuré (cause, correction proposée, explication) via `PydanticOutputParser`. |
| [`propose.py`](../agent/nodes/propose.py) | ❌ | **Le nœud central du projet** : appelle `interrupt()` et met le graphe en pause. Rien ne s'applique sans passer par ici. |
| [`apply.py`](../agent/nodes/apply.py) | ❌ | **Le seul nœud qui écrit dans les données** — un sur huit. Uniquement si `human_decision == "approved"`, en transaction, sur la table diagnostiquée seulement, mots-clés destructeurs rejetés, valeur devinée rejetée. |
| [`amend.py`](../agent/nodes/amend.py) | ❌ | Écrit dans le **contrat** (v1 → v2) quand la donnée est juste et que c'est la règle qui a vieilli. **N'écrit rien dans les données** — et ne mène pas à `apply`. |
| [`validate.py`](../agent/nodes/validate.py) | ❌ | Re-profile la table : l'anomalie a-t-elle disparu ? On ne croit **jamais** une correction sur parole — un `WHERE` trop étroit s'exécute sans erreur SQL tout en ne réglant rien. Échec → « à traiter manuellement ». |
| [`log.py`](../agent/nodes/log.py) | ❌ | **La sortie unique du graphe.** Tous les chemins passent par ici avant `END`, y compris « rien d'anormal » et « refusé ». La complétude du journal est donc **topologique**, pas disciplinaire. |

### 8.3 `agent/detect/` — les 5 familles de détection

| Fichier | Rôle |
|---|---|
| [`__init__.py`](../agent/detect/__init__.py) | Assemble les familles et définit la forme commune d'un écart. |
| [`inventaire.py`](../agent/detect/inventaire.py) | *Le registre ne décrit plus la réalité.* La seule famille qui s'exerce **avant** de profiler, et la seule qui puisse constater qu'il n'y a **rien** à profiler. |
| [`schema.py`](../agent/detect/schema.py) | *Les colonnes ne sont plus les mêmes.* Diff avec le dernier schéma connu — c'est elle qui attrape `schema_drift_j45` (`payment_value` → `amount`). |
| [`contrat.py`](../agent/detect/contrat.py) | *Le lot viole ce qu'un humain a signé.* 3ᵉ pilier de détection. Sa force : elle attrape une anomalie **dès le premier lot**, sans historique. |
| [`statistique.py`](../agent/detect/statistique.py) | *Le lot s'écarte de ses prédécesseurs.* Compare chaque mesure aux N lots précédents (`OPS._PROFILES`), en **médiane/MAD**, pas moyenne/écart-type. |
| [`semantique.py`](../agent/detect/semantique.py) | ⭐ *Le lot se contredit lui-même.* **La famille qui justifie le projet** : les quatre autres comparent le lot à quelque chose d'extérieur, celle-ci le compare à lui-même. C'est elle qui voit `sao paulo` ≡ `são paulo`. |
| [`dbt.py`](../agent/detect/dbt.py) | ⚠️ **Ce n'est pas un détecteur** : elle ne constate rien, elle *traduit* les verdicts de dbt dans la forme commune des écarts. |
| [`silence.py`](../agent/detect/silence.py) | Le **filtre de silence** : ne pas resoumettre ce qu'un humain a déjà refusé. Un agent qui repose chaque jour la même question qu'on lui a refusée est un agent qu'on finit par ignorer. Rien n'est supprimé — la liste des silences est requêtable et **réactivable d'un clic** dans Streamlit. |

### 8.4 `agent/characterize/` — de « ce qu'on a mesuré » à « ce que c'est »

| Fichier | Rôle |
|---|---|
| [`__init__.py`](../agent/characterize/__init__.py) | La caractérisation : le profilage rend des *faits*, la caractérisation leur donne un **rôle** — et c'est le rôle qui dit quels contrôles ont un sens. |
| [`roles.py`](../agent/characterize/roles.py) | ⭐ **Le moteur de généricité.** Classe chaque colonne par rôle inféré (`identifier`, `categorical`, `temporal`, `measure`, `free_text`…) à partir d'agrégats seuls. Savoir qu'une colonne porte 8 000 valeurs distinctes ne dit pas quoi lui appliquer ; savoir que c'est un *identifiant*, si. |
| [`collisions.py`](../agent/characterize/collisions.py) | Quand deux valeurs sont la même chose écrite deux fois — le cœur du fil rouge. Pour un compteur, `sao paulo` et `são paulo` sont deux unités ; pour un humain, c'est la même métropole. |

### 8.5 `agent/contracts/` — proposer, écrire, signer, amender

| Fichier | Rôle |
|---|---|
| [`__init__.py`](../agent/contracts/__init__.py) | Le 3ᵉ pilier de la détection, après l'historique de schéma et la dérive statistique. |
| [`proposer.py`](../agent/contracts/proposer.py) | Construit un contrat **à partir d'un profil**. Le piège évité : un générateur naïf *grave ce qu'il observe* — sur `customer_city`, il écrirait la liste des 2 206 villes comme `accepted_values`. Il refuse donc d'exiger certaines choses, et le dit. |
| [`loader.py`](../agent/contracts/loader.py) | Le contrat sur disque : écrire, relire, versionner (`contracts/<dataset>/<TABLE>.v<N>.yaml`). ⭐ **Ne rend jamais un contrat `proposed`** — c'est ce qui fait qu'un contrat non signé ne gouverne rien. |
| [`validation.py`](../agent/contracts/validation.py) | ⭐ **La voie unique de signature.** `scripts/discover.py --approve` et l'écran « Contrats » de Streamlit passent par le même code — même raison que `hitl.py`. |
| [`amend.py`](../agent/contracts/amend.py) | Le miroir d'`apply` et le mécanisme **anti-obsolescence** : passe le contrat en v2 quand la donnée est juste et que la règle a vieilli. Aucune écriture sur les données. |

### 8.6 `agent/connectors/` — la seule porte vers une base

| Fichier | Rôle |
|---|---|
| [`__init__.py`](../agent/connectors/__init__.py) | La **fabrique** de connecteurs : `enregistrer()`, `enregistres()`, `ouvrir()`, `fermer()`, l'exception `ConnecteurInconnu`. C'est ce qui permet au registre de dire `connector: snowflake` sans que `agent/` connaisse Snowflake. |
| [`snowflake.py`](../agent/connectors/snowflake.py) | **Le seul fichier de `agent/` où du SQL a le droit d'exister.** Au-dessus de lui, l'agent ne manipule que des dictionnaires : `profile`, `detect` et `diagnose` ignorent jusqu'à l'existence d'une base. |
| [`ops.py`](../agent/connectors/ops.py) | La mémoire de l'agent — le schéma `OPS` (`INCIDENTS`, `_PROFILES`, `_SCHEMA_HISTORY`). Second fichier autorisé à contenir du SQL, **par distinction et non par commodité** : `OPS` n'est pas le système observé, c'est ce que l'agent écrit sur lui. |

### 8.7 `agent/tools/` — les outils LangChain

Un fichier par tool, décoré `@tool`, **testé isolément**. Aucun n'est jamais lié à un modèle
(`bind_tools` n'apparaît nulle part) : c'est le graphe qui contrôle le flux, pas le LLM (ADR 004).

| Fichier | Accès | Rôle |
|---|---|---|
| [`__init__.py`](../agent/tools/__init__.py) | — | Expose les tools. |
| [`_connecteur.py`](../agent/tools/_connecteur.py) | — | Le préambule commun : un `@tool` ne reçoit que des chaînes, il doit donc **résoudre son connecteur lui-même**. |
| [`profile_table.py`](../agent/tools/profile_table.py) | lecture | **L'assembleur** : une table → une fiche. C'est le point où le profilage devient consommable par la détection. |
| [`top_values.py`](../agent/tools/top_values.py) | lecture | Quelles valeurs, et pas seulement combien. **Sans lui, aucune détection sémantique n'est possible.** |
| [`robust_stats.py`](../agent/tools/robust_stats.py) | lecture | Médiane et MAD, **jamais** moyenne et écart-type — une seule valeur aberrante déplace la moyenne et fait taire la détection. |
| [`read_schema_history.py`](../agent/tools/read_schema_history.py) | lecture | À quoi ressemblait cette table. La **référence** de la famille `schema`. |
| [`read_past_incidents.py`](../agent/tools/read_past_incidents.py) | lecture | **La mémoire de l'agent** (O7). Ne rend que les incidents ayant **reçu une décision humaine** — sinon l'agent apprendrait ses propres erreurs (R5). |
| [`run_sql.py`](../agent/tools/run_sql.py) | **lecture seule** | L'échappatoire d'investigation. Rejet des mots-clés d'écriture + journalisation systématique de chaque requête. |
| [`generate_dq_rule.py`](../agent/tools/generate_dq_rule.py) | écriture fichier | ⭐ Transforme un écart constaté en **test dbt** rattaché à une dimension DAMA. C'est ce qui fait que l'agent **durcit le pipeline** au lieu de seulement réparer la donnée. |
| [`write_log.py`](../agent/tools/write_log.py) | écriture | La seule écriture du journal métier : **une ligne par run** dans `OPS.INCIDENTS`, quel que soit le chemin. Append-only. |

---

## 9. `scripts/` — les commandes qu'on tape à la main

| Fichier | Rôle |
|---|---|
| [`check_access.py`](../scripts/check_access.py) | ✅ **La première commande à lancer.** Dit en une exécution si l'environnement est utilisable : Snowflake, LLM. Code retour 0 seulement si tout est vert. *(Le seul script lancé par son chemin et non en `-m` — la commande est promise dans le README.)* |
| [`setup_snowflake.py`](../scripts/setup_snowflake.py) | Crée la base `DATA_QUALITY` et ses 4 schémas (`RAW`, `STAGING`, `MARTS`, `OPS`). **Idempotent** (`IF NOT EXISTS` partout) — c'est ce qui permet de repartir d'un trial Snowflake neuf sans rien faire à la main (ADR 001). |
| [`discover.py`](../scripts/discover.py) | **Le cycle A** — la découverte, hors du DAG : introspection → profilage → caractérisation → proposition de contrat ⏸ → signature. `--list`, `--table`, `--approve TABLE --by NOM`, `--accept-warnings`. Ici, la pause **est un fichier** sur disque (`status: proposed`), pas un `interrupt()` : l'humain édite le YAML, et un checkpoint écraserait ses corrections. |
| [`check_layer.py`](../scripts/check_layer.py) | **Le cycle B** — lance l'agent sur toutes les tables d'une couche. C'est ce qu'Airflow appelle (`check_bronze`/`check_silver`/`check_gold`) : le DAG ne contient donc aucune logique. ⭐ **Une pause n'est pas un échec** — le code de sortie ne répond qu'à *« l'agent a-t-il pu tourner ? »* (`0` = oui, `1` = une table n'a pas pu être examinée). Une table qui échoue n'emporte pas les autres. |
| [`decide.py`](../scripts/decide.py) | Injecte une décision humaine dans un run en pause : `--list`, puis `<thread_id>` seul (voir), `ask "…"`, `approve`, `amend`, `reject`, avec `--by` et `--fix`. Tourne dans un **process séparé** de celui qui a lancé le run — on peut répondre le lendemain, depuis un autre terminal. Le `thread_id` est `<dataset>|<table>|<jour>`. |
| [`export_graph.py`](../scripts/export_graph.py) | Régénère `docs/img/agent_graph.mmd` (source Mermaid, hors ligne) et `.png` (via mermaid.ink, donc réseau) **depuis le graphe compilé**. À relancer après toute modification de `agent/graph.py` — un diagramme dessiné à la main décrit vite un agent qui n'existe plus. |
| [`export_contracts_doc.py`](../scripts/export_contracts_doc.py) | Régénère [`docs/CONTRATS.md`](CONTRATS.md) : une fiche par table, ce que le contrat exige **et ce que la découverte a refusé d'exiger**. À relancer après toute découverte, signature ou amendement. Ne connaît pas Olist — il lit le registre. |

---

## 10. `streamlit/` — les écrans

| Fichier | Rôle |
|---|---|
| [`app.py`](../streamlit/app.py) | **Ne contient que de l'affichage.** Six écrans, organisés autour de trois questions : *Où en est-on ?* (**🏠 Accueil**) · *Que dois-je faire ?* (**✅ Décisions**, **📜 Règles**) · *Que s'est-il passé ?* (**📊 Vos données**, **📚 Historique**, **🔕 Alertes désactivées**). Les noms d'écrans sont des **constantes** (`ACCUEIL`, `DECISIONS`, `REGLES`…), pas des chaînes recopiées — l'accueil renvoyait vers « l'onglet Contrats » alors que l'écran s'appelait « Règles » depuis la refonte. Les boutons Approuver/Amender/Refuser appellent `agent/hitl.py` — **exactement le même code** que `scripts/decide.py`. |
| [`donnees.py`](../streamlit/donnees.py) | **Toute la logique, aucune interface** — donc testable sans navigateur. Lit le journal, résume un incident, calcule la file d'attente, charge les contrats et les agrégats Gold, et surtout **traduit le vocabulaire interne** (« écart de famille sémantique » → une phrase que comprend quelqu'un qui connaît le métier, pas le projet). |

---

## 11. `airflow/` — l'orchestration

| Fichier | Rôle |
|---|---|
| [`dags/medallion_pipeline.py`](../airflow/dags/medallion_pipeline.py) | Le DAG, **un run par jour rejoué**, aujourd'hui **11 tâches** : `replay → inject → ingest_bronze → check_bronze 🤖 → dbt_run_silver → dbt_test_silver → check_silver 🤖 → dbt_run_gold → dbt_test_gold → check_gold 🤖 → archive_baseline`. Que des `BashOperator` : **aucune logique métier**, elle vit dans `scripts/` et `data/`, donc elle se teste sans Docker. |
| [`docker-compose.yaml`](../airflow/docker-compose.yaml) | Airflow local en **LocalExecutor + Postgres** (pas de Celery/Redis). Monte **tout le dépôt** dans `/opt/airflow/project` — c'est ce qui fait que `agent_checkpoints.sqlite` est visible des deux côtés, et qu'on peut reprendre depuis le PC un run mis en pause par le DAG. Charge `../.env` pour les identifiants Snowflake. |
| [`Dockerfile`](../airflow/Dockerfile) | `apache/airflow:2.10.5-python3.11` **+ un venv Python isolé** (`/opt/airflow/pipeline-venv`) pour les dépendances du pipeline. Airflow épingle ses propres versions (dont pandas) ; le venv séparé rend tout conflit impossible. |
| [`.env.example`](../airflow/.env.example) | Uniquement `AIRFLOW_UID` (pour les permissions Linux). ⚠️ **Les identifiants Snowflake ne sont pas ici** — ils sont dans le `.env` **à la racine** du dépôt. |
| [`README.md`](../airflow/README.md) | Le mode d'emploi complet : build, `airflow-init`, backfill (option A prudente / option B `catchup`), rejeu d'un jour, arrêt/reset, la convention « une tâche `check_*` verte ne veut pas dire rien trouvé », et un tableau de dépannage. |

---

## 12. `benchmarks/` — la baseline figée

| Fichier | Rôle |
|---|---|
| [`archive_baseline.py`](../benchmarks/archive_baseline.py) | Confronte les tests dbt (Silver + Gold) du jour rejoué à `ground_truth.yaml` et complète `baseline_run.json`. Appelé en fin de DAG. Lit `dbt/target/silver/` et `dbt/target/gold/` — le DAG donne un `--target-path` dédié à chaque `dbt test` pour ne pas les écraser. |
| [`baseline_run.json`](../benchmarks/baseline_run.json) | **La trace figée** de ce que « dbt seul » détecte, une entrée par jour : `expected_anomalies`, chaque test avec son statut, et `baseline_detected`. **Versionné** — c'est la référence contre laquelle l'agent sera mesuré en phase 8. |
| [`proof_semantic_gap.py`](../benchmarks/proof_semantic_gap.py) | **La preuve par requête** que la baseline rate le fan-out sémantique : interroge `MARTS.fct_geolocation_by_city` et montre `são paulo` / `sao paulo` / `sãopaulo` sur trois lignes distinctes. Sans cette preuve, le projet n'a pas de sujet. |

---

## 13. `tests/` — 27 fichiers, 536 fonctions

**Aucun test n'ouvre de connexion, n'appelle un LLM, ni ne touche au réseau.** La CI doit être
déterministe, gratuite, et tourner sans clé API.

| Fichier | Rôle |
|---|---|
| [`conftest.py`](../tests/conftest.py) | **Les garde-fous de la suite** : ni vrai LLM, ni vraie base. La règle reposait sur la discipline ; elle est ici **mécanique**. |
| [`sitecustomize.py`](../tests/sitecustomize.py) | Installe les mêmes doubles dans les **sous-processus** lancés par les tests (Python importe `sitecustomize` au démarrage de l'interpréteur). |
| [`test_sanity.py`](../tests/test_sanity.py) | L'environnement est correctement installé. |
| [`test_replay_determinism.py`](../tests/test_replay_determinism.py) | **Verrou 1** : deux rejeux du même jour produisent des fichiers identiques à l'octet près. |
| [`test_ground_truth_coherence.py`](../tests/test_ground_truth_coherence.py) | **Verrou 2** : pour chaque anomalie déclarée, le batch injecté porte bien la panne annoncée (type, cible, ampleur). |
| [`test_semantic_case.py`](../tests/test_semantic_case.py) | Le fil rouge, en trois temps : `sao paulo` à travers le rejeu, la préparation et l'injection. |
| [`test_socle.py`](../tests/test_socle.py) | Le socle générique : registre, fabrique, connecteur — éprouvé avec un **curseur factice** qui enregistre le SQL émis. |
| [`test_tools.py`](../tests/test_tools.py) | Les 8 tools, isolément. |
| [`test_characterize.py`](../tests/test_characterize.py) | Le classement par rôle — sans base : décider ne coûte aucune requête. |
| [`test_contracts.py`](../tests/test_contracts.py) | Proposer, écrire, relire un contrat ; et le défaut de naissance évité (ne pas graver 2 206 villes en `accepted_values`). |
| [`test_detect.py`](../tests/test_detect.py) | Les 5 familles, une par une — des fonctions pures sur l'état. |
| [`test_discover.py`](../tests/test_discover.py) | Le cycle Découverte de bout en bout, avec une fiche de profil préparée. |
| [`test_agent_state.py`](../tests/test_agent_state.py) | L'état partagé. |
| [`test_agent_nodes.py`](../tests/test_agent_nodes.py) | Les 8 nœuds **isolément**, sans graphe ni checkpointer. |
| [`test_agent_graph.py`](../tests/test_agent_graph.py) | Le **câblage** — ce que les nœuds ne peuvent pas garantir seuls. Un nœud parfait mal relié ne vaut rien. |
| [`test_apply_validate.py`](../tests/test_apply_validate.py) | `apply` borné et `validate` réel. |
| [`test_p6.py`](../tests/test_p6.py) | L'invariant P6 : ne jamais inventer une valeur. |
| [`test_incidents.py`](../tests/test_incidents.py) | Signature, silence, journal. |
| [`test_impact.py`](../tests/test_impact.py) | L'impact estimé et la file d'attente. |
| [`test_hitl.py`](../tests/test_hitl.py) | La voie **unique** de reprise (CLI et Streamlit passent par le même code). |
| [`test_check_layer.py`](../tests/test_check_layer.py) | Le lanceur de couche — tout ce qui peut mal tourner dans Airflow se teste ici. |
| [`test_freshness_run_sql.py`](../tests/test_freshness_run_sql.py) | Fraîcheur et `run_sql`. |
| [`test_generate_dq_rule.py`](../tests/test_generate_dq_rule.py) | Le générateur de règles dbt. |
| [`test_export_contracts_doc.py`](../tests/test_export_contracts_doc.py) | Le générateur de `docs/CONTRATS.md`. |
| [`test_streamlit_donnees.py`](../tests/test_streamlit_donnees.py) | La couche de données des écrans, sans navigateur. |
| [`test_streamlit_app.py`](../tests/test_streamlit_app.py) | Les **six écrans exécutés pour de vrai** via `streamlit.testing.v1.AppTest` : on clique, on lit, on vérifie — sans navigateur. |
| ⭐ [`test_preuves.py`](../tests/test_preuves.py) | **Les cinq preuves du projet — des livrables, pas de l'hygiène.** Écrit pour être *lu* : chaque test énonce une garantie en une phrase et la démontre sur le graphe **assemblé**. ① aucun chemin vers `apply` sans approbation ② une valeur devinée est rejetée même approuvée ③ pause + reprise après redémarrage ④ `apply` borné ⑤ `amend` ne touche pas aux données. |

---

## 14. `docs/` — la documentation

| Fichier | Rôle |
|---|---|
| **`GUIDE_FICHIERS.md`** | ← **ce document** : le rôle de chaque fichier + la marche à suivre pour lancer en local. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | **Comment c'est structuré** : les 6 principes P1→P6, la vue d'ensemble, les composants, les couches Medallion, l'agent (état, nœuds, arêtes, tools), le HITL, le flux d'une exécution, l'orchestration, la résilience, la sécurité. |
| [`DESIGN.md`](DESIGN.md) | **Pourquoi ces choix** — 11 questions et leurs arbitrages : pourquoi un agent alors qu'on a dbt test, pourquoi une machine à états et pas ReAct, pourquoi le LLM ne voit pas les lignes, comment détecter une anomalie sémantique, pourquoi le HITL pur, le design de la mémoire, du lineage, du benchmark, **ce qui a été délibérément écarté**, les hypothèses fragiles, la ligne à ne pas franchir. |
| [`dataset.md`](dataset.md) | La carte d'identité d'Olist : modèle de données, les 9 tables, les nulls **naturels** (à ne pas confondre avec les injections), la couverture temporelle, le fil rouge sémantique mesuré, et le choix de la fenêtre de rejeu. |
| [`DEMO.md`](DEMO.md) | **Le runbook de la démonstration**, écran par écran : la préparation en terminal, puis les 6 étapes à la souris, les deux écrans qui distinguent le projet (Signatures en silence, Contrats), et la variante « refus » en 30 secondes. |
| [`CONTRATS.md`](CONTRATS.md) | **Généré** par `scripts/export_contracts_doc.py` : une fiche lisible par table, ce que le contrat exige et ce que la découverte a refusé d'exiger. Ne pas éditer à la main. |
| [`img/agent_graph.mmd`](img/agent_graph.mmd) · `img/agent_graph.png` | **Générés** par `scripts/export_graph.py` **depuis le graphe compilé**. Le `.mmd` est la version de référence (GitHub la rend, un `git diff` montre ce qui a changé dans le câblage) ; le `.png` sert au rapport et aux diapos. |

### 14.1 `docs/adr/` — les décisions structurantes

Une décision par fichier, au format *contexte / options / décision / conséquences*, rédigées **au fil de
l'eau** : une décision reconstituée trois mois plus tard est une justification, pas une décision.

| ADR | Décision |
|---|---|
| [`001-snowflake-access.md`](adr/001-snowflake-access.md) | Accès Snowflake : trial personnel — d'où l'exigence d'un `setup_snowflake.py` idempotent. |
| [`004-langgraph-vs-function-calling.md`](adr/004-langgraph-vs-function-calling.md) | LangGraph plutôt que function calling, **et ce que « tool » veut dire ici** (un `@tool` non lié à un modèle). |
| [`008-hitl-pur-vs-scoring.md`](adr/008-hitl-pur-vs-scoring.md) | Validation humaine systématique plutôt qu'un scoring d'autonomie. *(Remplace le mécanisme de scoring des v1–v3 du cahier des charges.)* |
| [`009-source-hybride-olist.md`](adr/009-source-hybride-olist.md) | Olist réel rejoué + anomalies injectées, plutôt qu'un générateur Faker. |
| [`010-agent-generique.md`](adr/010-agent-generique.md) | **L'ADR le plus long (48 Ko)** : deux cycles, zéro nom en dur, contrats versionnés, 8 nœuds / 3 issues, ne jamais inventer une valeur. |

> Les ADR 000, 002, 003, 005, 006, 007 sont cités dans `ARCHITECTURE.md` §11 mais **ne sont pas encore
> rédigés** dans le dépôt (le 006 est de toute façon remplacé par le 008).

---

## 15. Les fichiers `.gitkeep`

`agent/.gitkeep`, `benchmarks/.gitkeep`, `contracts/.gitkeep`, `data/.gitkeep`, `dbt/.gitkeep`,
`docs/adr/.gitkeep`, `ingestion/.gitkeep`, `scripts/.gitkeep`, `streamlit/.gitkeep`, `tests/.gitkeep`,
`airflow/dags/.gitkeep` — des fichiers vides qui n'existent que pour que git **versionne un dossier
vide**. Créés en phase 0 quand la structure a été posée avant le code. Aucun rôle fonctionnel.

---

# 16. Lancer le projet en local

> **À lire d'abord.** Le projet a **deux modes de fonctionnement**, et le premier ne demande rien :
>
> | Mode | Ce qu'il faut | Ce que vous obtenez |
> |---|---|---|
> | **A — La suite de tests** | Python 3.11 + `uv`. **Ni Snowflake, ni clé LLM, ni Docker.** | 536 tests, dont les 5 preuves du projet et les 6 écrans Streamlit exécutés. |
> | **B — La chaîne complète** | + un compte Snowflake, une clé Groq, les CSV Kaggle, Docker | Le pipeline réel, l'agent, la démo. |
>
> **Commencez par A.** C'est 3 minutes, et ça valide l'installation avant que Snowflake s'en mêle.

---

## 16.1 Prérequis

| Besoin | Version / note |
|---|---|
| **Python** | ≥ 3.11, < 3.12 (`.python-version` dit `3.11`) |
| **[`uv`](https://github.com/astral-sh/uv)** | Le gestionnaire d'environnement. `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Compte Snowflake** | *(mode B)* Trial personnel — voir [ADR 001](adr/001-snowflake-access.md) et [`ROADMAP.md`](../ROADMAP.md#️-à-régler-dès-maintenant--la-fenêtre-snowflake) |
| **Clé LLM** | *(mode B)* **Groq** (gratuit, recommandé) — ou Google AI Studio / Snowflake Cortex |
| **CSV Kaggle Olist** | *(mode B)* `olistbr/brazilian-ecommerce`, ~100 k commandes |
| **Docker** | *(mode B, optionnel)* Uniquement pour Airflow. L'agent et le pipeline tournent sans. |
| **`make`** | Facultatif — chaque cible est un raccourci de 1 à 2 commandes. Sous Windows, utiliser **Git Bash** : le Makefile utilise la syntaxe `sh` (`set -a; . ./.env`). |

---

## 16.2 Installer l'environnement

```bash
git clone https://github.com/hodamounaouir/PFA.git
cd PFA

make setup          # = uv sync  +  cp .env.example .env s'il manque
```

Sans `make` :

```bash
uv sync
test -f .env || cp .env.example .env
```

> ⚠️ Si le dépôt vous arrive avec un `.venv/` **Windows** (`.venv/Scripts/*.exe`), supprimez-le avant :
> `rm -rf .venv && uv sync`.

### ✅ Point de contrôle — **le mode A est déjà utilisable**

```bash
make test           # = uv run pytest        → 536 tests, sans base ni réseau
make lint           # = uv run ruff check .
make check          # lint + test
```

Si tout est vert, l'installation est bonne. **Tout ce qui suit concerne le mode B.**

---

## 16.3 Remplir `.env` — le piège CRLF

Ouvrez `.env` et renseignez les 7 variables de `.env.example` :

```dotenv
SNOWFLAKE_ACCOUNT=xy12345.eu-west-1
SNOWFLAKE_USER=…
SNOWFLAKE_PASSWORD=…
SNOWFLAKE_ROLE=ACCOUNTADMIN
SNOWFLAKE_WAREHOUSE=COMPUTE_WH
SNOWFLAKE_DATABASE=DATA_QUALITY
GROQ_API_KEY=gsk_…
```

> ⚠️⚠️ **Enregistrez `.env` en LF, pas en CRLF.** Sous Windows, un `\r` parasite se glisse dans les
> valeurs Snowflake et **la connexion échoue avec une erreur qui ne dit pas pourquoi** (`250001`, un
> hostname bizarre). Dans VS Code : coin bas-droit → cliquer `CRLF` → choisir `LF` → sauvegarder.
> C'est le piège n° 1 du projet, il est documenté dans trois fichiers pour cette raison.

**Ne commitez jamais ce fichier.** `.gitignore` couvre `.env*` (y compris `.env.bak`, `.env.local`).

---

## 16.4 Vérifier les accès — **la commande qui décide de tout**

```bash
uv run python scripts/check_access.py
# ✅ Snowflake  ✅ LLM (Groq)
```

> **Si ce n'est pas vert, arrêtez-vous là.** Tout le reste échouera plus loin et plus obscurément.

---

## 16.5 Créer la base et ses schémas

```bash
uv run python scripts/setup_snowflake.py
# 🎉 Base DATA_QUALITY prête — RAW · STAGING · MARTS · OPS
```

**Idempotent** (`IF NOT EXISTS` partout) : relançable sans risque, et c'est ce qui permet de repartir
d'un trial neuf sans rien faire à la main dans la console Snowflake.

---

## 16.6 Récupérer le dataset Olist

Les CSV **ne sont pas versionnés** — à copier à la main sur chaque machine.

```bash
# via l'API Kaggle (nécessite ~/.kaggle/kaggle.json)
kaggle datasets download olistbr/brazilian-ecommerce -p data/olist --unzip
```

Ou télécharger [le dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) à la main et
dézipper les 9 CSV dans `data/olist/`. Les noms attendus sont listés dans
[`data/config.py`](../data/config.py) (`CSV_BY_TABLE`).

---

## 16.7 Fabriquer les données : rejeu → injection

```bash
# 1. Découper l'historique en 92 batchs quotidiens (applique aussi le nettoyage du J1)
uv run python -m data.replay --from 2018-03-01 --to 2018-05-31 --seed 42

# 2. Injecter les anomalies déclarées dans ground_truth.yaml
uv run python -m data.inject
```

Ou jour par jour :

```bash
uv run python -m data.replay --day 2018-05-14
uv run python -m data.inject --day 2018-05-14 --if-scheduled   # n'injecte que si ce jour est prévu
```

> 📌 **La fenêtre `2018-03-01 → 2018-05-31` est figée** dans `data/config.py` : c'est le plateau stable
> du dataset, et `ground_truth.yaml` y est indexé. **Un jour hors fenêtre est refusé.**
>
> 📌 **Ne relancez jamais `inject` seul sur un batch déjà injecté** : il refuse de corrompre deux fois le
> même jour (marqueur `.injected`). Pour rejouer un jour, **repartez de `replay`**, qui régénère le
> batch à neuf.

Résultat : `data/incoming/2018-03-01/` … `data/incoming/2018-05-31/`, 4 à 6 CSV par jour.

---

## 16.8 Ingérer en Bronze

```bash
uv run python -m ingestion.load --from 2018-03-01 --to 2018-05-31
# ou : --day 2018-05-14   |   sans argument : toute la fenêtre
```

**Idempotent** : recharger le même batch ne duplique rien. Remplit le schéma `RAW` (tout en VARCHAR)
et alimente `OPS._SCHEMA_HISTORY`.

---

## 16.9 Transformer avec dbt (Silver + Gold)

```bash
make dbt-debug      # vérifie la connexion — à faire une fois
make dbt-run        # RAW → STAGING (vues) → MARTS (tables)
make dbt-test       # les tests statiques : la BASELINE
```

Sans `make` (les cibles ne font que sourcer `.env` puis entrer dans `dbt/`) :

```bash
set -a; . ./.env; set +a
cd dbt && uv run dbt run --profiles-dir . && uv run dbt test --profiles-dir .
```

> Des **échecs de `dbt test` sont attendus** sur les jours d'anomalie (J45, J60, J75, J80, J85) : ce
> sont des **détections**, pas des pannes. C'est la convention du projet — `rc=1` = détection = vert.

Vous pouvez déjà vérifier le trou que l'agent doit combler :

```bash
PYTHONPATH=. uv run python benchmarks/proof_semantic_gap.py
# → 'são paulo', 'sao paulo', 'sãopaulo' sur trois lignes distinctes
```

---

## 16.10 Cycle A — la découverte des contrats

Se fait **une fois par table**, hors du DAG. Les 17 contrats d'Olist sont déjà versionnés dans
`contracts/olist/`, **mais tous en `status: proposed`**.

```bash
uv run python -m scripts.discover olist --list                    # où en est chaque contrat
uv run python -m scripts.discover olist                           # (re)découvrir toutes les tables
uv run python -m scripts.discover olist --table RAW.ORDERS        # une seule
uv run python -m scripts.discover olist --approve RAW.CUSTOMERS --by <votre-nom>
```

> ⚠️ **Un contrat `proposed` ne gouverne rien.** Tant qu'il n'est pas signé, aucune de ses clauses ne
> sert à la détection : les familles `contrat` (nulls J60, doublons J75) restent muettes. Le fil rouge
> São Paulo n'en dépend pas — la famille sémantique lit le **rôle du profil**, pas le contrat.
>
> Si la découverte a émis des réserves sur un contrat, `--approve` refuse ; forcer avec
> `--accept-warnings`.

Pour régénérer la documentation lisible après une signature :

```bash
uv run python -m scripts.export_contracts_doc olist    # → docs/CONTRATS.md
```

---

## 16.11 Cycle B — lancer l'agent (sans Docker)

```bash
uv run python -m scripts.check_layer olist gold --day 2018-05-14
# layer ∈ {bronze, silver, gold}   ·   --day est obligatoire
```

> ⭐ **Une tâche verte ne veut pas dire « rien trouvé ».** Le code de sortie répond à *« l'agent a-t-il
> pu tourner ? »*, pas à *« qu'a-t-il trouvé ? »* :
>
> | Sortie | Signification |
> |:-:|---|
> | `0` | toutes les tables ont été examinées — **avec ou sans proposition en attente** |
> | `1` | au moins une table n'a pas pu l'être : là, il y a vraiment un problème |
>
> **Ce que l'agent a trouvé se lit dans `OPS.INCIDENTS`.** Une proposition en attente est le
> fonctionnement *normal*.

---

## 16.12 Trancher — en ligne de commande

Le `thread_id` est reconstructible de tête : **`<dataset>|<table>|<jour>`**.

```bash
uv run python -m scripts.decide --list                              # la file d'attente
uv run python -m scripts.decide "olist|MARTS.FCT_GEOLOCATION_BY_CITY|2018-05-14"   # voir la proposition

# les trois décisions
uv run python -m scripts.decide "<thread_id>" approve --by <nom>            # la donnée est fausse
uv run python -m scripts.decide "<thread_id>" approve --by <nom> --fix "…"  # …avec votre propre correction
uv run python -m scripts.decide "<thread_id>" amend   --by <nom>            # la règle a vieilli → contrat v2
uv run python -m scripts.decide "<thread_id>" reject  --by <nom>            # cas isolé → silence

# et la quatrième réponse, qui n'est PAS une décision
uv run python -m scripts.decide "<thread_id>" ask "pourquoi le job amont plutôt qu'un changement métier ?"
```

`ask` renvoie la question à `diagnose`, la réponse revient, et la proposition **attend de nouveau** —
autant de fois qu'il le faut. **Discuter ne rapproche pas de l'écriture** : dix questions n'ouvrent pas
`apply`, et un test le vérifie.

---

## 16.13 Ouvrir Streamlit — l'observabilité et la validation

```bash
uv run streamlit run streamlit/app.py
# → http://localhost:8501
```

Six écrans, dans l'ordre de la barre latérale : **🏠 Accueil · ✅ Décisions · 📜 Règles · 📊 Vos
données · 📚 Historique · 🔕 Alertes désactivées**. Le bouton *Approuver* **reprend réellement le graphe
en pause** — il passe par `agent/hitl.py`, exactement le même code que `scripts/decide.py`.

> ⚠️ `README.md` et `docs/DEMO.md` citent encore les **anciens** noms d'écrans (« Dashboard BI »,
> « Incidents », « Validation HITL », « Contrats »). Les noms ci-dessus sont ceux du code
> (les constantes en tête de [`streamlit/app.py`](../streamlit/app.py)) ; ce sont eux qui font foi.

Le déroulé écran par écran de la démonstration est le runbook [`docs/DEMO.md`](DEMO.md).

---

## 16.14 Airflow — tout orchestrer (optionnel)

Toutes les commandes se lancent **depuis `airflow/`**, avec Docker Desktop **démarré**.

```bash
cd airflow

docker compose build              # Airflow + le venv isolé du pipeline (quelques minutes)
docker compose up airflow-init    # UNE SEULE FOIS : crée la base de métadonnées + l'admin
docker compose up -d              # webserver + scheduler en tâche de fond
```

→ **http://localhost:8080**, login **`airflow`** / **`airflow`**. Le DAG `medallion_pipeline` doit
apparaître.

Sous Linux, avant le `build`, fixez votre UID pour éviter les problèmes de permissions :

```bash
echo "AIRFLOW_UID=$(id -u)" > airflow/.env
```

### Rejouer la fenêtre

```bash
# Option A (recommandée) : les 30 jours propres d'abord, le reste ensuite
docker compose exec airflow-scheduler \
  airflow dags backfill -s 2018-03-01 -e 2018-03-30 medallion_pipeline
docker compose exec airflow-scheduler \
  airflow dags backfill -s 2018-03-31 -e 2018-05-31 medallion_pipeline
```

**Option B** : activer (unpause) le DAG dans l'UI — `catchup=True` + `max_active_runs=1` rejouent les
92 jours dans l'ordre.

Rejouer **un** jour proprement (toujours repartir de la tâche `replay`) :

```bash
docker compose exec airflow-scheduler \
  airflow dags backfill -s 2018-04-14 -e 2018-04-14 --reset-dagruns medallion_pipeline
```

Arrêter :

```bash
docker compose down       # garde la base Airflow et les volumes
docker compose down -v    # efface tout → refaire airflow-init
```

> 💡 **Les runs mis en pause par le DAG se reprennent depuis votre PC, hors du conteneur** : tout le
> dépôt est monté dans Airflow (`../:/opt/airflow/project`), donc `agent_checkpoints.sqlite` vit des
> deux côtés à la fois. Rien à configurer. *(Sous Linux, si `scripts/decide.py` se plaint des
> permissions, un `chown` sur le fichier suffit.)*

---

## 16.15 Le chemin le plus court vers la démo

Si vous voulez juste **voir le fil rouge**, sans rejouer 92 jours (c'est la préparation de
[`docs/DEMO.md`](DEMO.md)) :

```bash
uv run python scripts/check_access.py
uv run python -m data.replay    --day 2018-05-14
uv run python -m data.inject    --day 2018-05-14 --if-scheduled
uv run python -m ingestion.load --day 2018-05-14
make dbt-run
uv run python -m scripts.check_layer olist gold --day 2018-05-14
uv run streamlit run streamlit/app.py
```

Puis, dans Streamlit : 📊 **Vos données** (São Paulo sur deux lignes) → ✅ **Décisions** (l'impact, les
gestes autorisés, votre nom, **Approuver**) → 📚 **Historique** (la ligne du run) → retour sur 📊 **Vos
données** : São Paulo tient sur une ligne.

---

## 16.16 Les commandes utilitaires

| Commande | Quand la lancer |
|---|---|
| `uv run python -m scripts.export_graph` | **Après toute modification de `agent/graph.py`** — régénère `docs/img/agent_graph.{mmd,png}` depuis le graphe compilé. |
| `uv run python -m scripts.export_contracts_doc olist` | Après toute découverte, signature ou amendement — régénère `docs/CONTRATS.md`. |
| `PYTHONPATH=. uv run python benchmarks/proof_semantic_gap.py` | Pour prouver, par requête, que la baseline rate le fan-out sémantique. |
| `uv run python -m benchmarks.archive_baseline --day 2018-04-14` | Archiver le verdict dbt d'un jour dans `baseline_run.json` (le DAG le fait tout seul). |
| `make check` | Avant tout commit : `ruff` + `pytest`. |

---

## 16.17 Dépannage

| Symptôme | Cause probable / solution |
|---|---|
| `check_access.py` : connexion Snowflake KO, code `250001`, hostname bizarre | **`.env` en CRLF** → réenregistrer en **LF**. C'est le piège n° 1. |
| `env file ../.env not found` (docker compose) | Le `.env` **à la racine du dépôt** manque : `cp .env.example .env` puis le remplir. |
| `❌ Batch introuvable` à l'ingestion | `data/olist/` est vide — les CSV Kaggle ne sont pas dans le dépôt. |
| `hors fenêtre de rejeu` | Jour en dehors de `2018-03-01 → 2018-05-31` (fenêtre figée dans `data/config.py`). |
| `inject` refuse de tourner | Le batch est déjà injecté (marqueur `.injected`). Repartir de `data.replay` pour ce jour. |
| L'agent ne détecte rien de « contrat » | Les 17 contrats sont en `status: proposed`. Signez-en un : `scripts.discover olist --approve <TABLE> --by <nom>`. |
| L'agent est muet en début de fenêtre | Normal : sans historique suffisant, la détection statistique se tait (garde-fou anti-démarrage-à-froid, `agent/config.py`). Il doit « apprendre le normal » d'abord. |
| `scripts.decide` ne trouve pas la proposition | La base de checkpoints diffère entre celui qui a lancé le run et celui qui décide. Les deux doivent viser le même fichier (`--db`, défaut : `agent_checkpoints.sqlite` à la racine). |
| `ImportError` sur `donnees` au lancement de Streamlit | Lancer depuis **la racine du dépôt** : `uv run streamlit run streamlit/app.py`. |
| L'image Airflow ne se build pas (tag introuvable) | Ajuster la version dans `airflow/Dockerfile` (`apache/airflow:2.10.5-python3.11`). |
| Port 8080 déjà pris | Remplacer `"8080:8080"` par `"8081:8080"` dans `airflow/docker-compose.yaml`. |
| `make` échoue sous Windows | Utiliser **Git Bash** — les cibles dbt utilisent la syntaxe `sh` (`set -a; . ./.env`). |

---

## 17. « Je veux faire X » → le fichier à ouvrir

| Je veux… | Ouvrir |
|---|---|
| brancher un **nouveau dataset** | `datasets/<nom>.yaml` — **et rien d'autre** |
| ajouter une **anomalie de test** | `data/ground_truth.yaml` (obligatoire) puis `data/inject.py` |
| changer la **fenêtre de rejeu** ou le seed | `data/config.py` — ⚠️ gelé une fois l'agent évalué |
| régler la **sensibilité** de la détection | `agent/config.py` — jamais l'autonomie, uniquement le bavardage |
| ajouter une **famille de détection** | `agent/detect/<famille>.py` + l'enregistrer dans `agent/detect/__init__.py` |
| ajouter un **tool** | `agent/tools/<nom>.py`, un fichier, testé isolément |
| modifier **ce que l'agent a le droit de faire** | `agent/corrections.py` (P6) et `agent/sql_guard.py` |
| toucher au **câblage** du graphe | `agent/graph.py` — puis relancer `scripts.export_graph` **et** `tests/test_preuves.py` |
| écrire du **SQL** | `agent/connectors/` (les 2 seuls fichiers autorisés) ou `dbt/models/` — **jamais ailleurs** |
| ajouter une **transformation** | `dbt/models/staging/` ou `dbt/models/marts/` — jamais en Python |
| ajouter un **écran** | `streamlit/app.py` (affichage) **+** `streamlit/donnees.py` (toute la logique) |
| ajouter une **tâche** au pipeline | `airflow/dags/medallion_pipeline.py` — un `BashOperator`, zéro logique |
| documenter une **décision structurante** | `docs/adr/NNN-titre.md`, format contexte / options / décision / conséquences |

---

## 18. Ordre de lecture conseillé

Pour comprendre le projet sans se noyer, dans cet ordre :

1. [`README.md`](../README.md) — le problème en 30 secondes.
2. [`docs/DESIGN.md`](DESIGN.md) **§1** — pourquoi un agent alors qu'on a dbt test.
3. [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) **§1 et §5** — les 6 principes, puis les 8 nœuds.
4. [`tests/test_preuves.py`](../tests/test_preuves.py) — **les cinq garanties, en code**. C'est le
   fichier le plus dense du dépôt : cinq phrases, cinq démonstrations.
5. [`agent/graph.py`](../agent/graph.py) — le câblage, où ces garanties deviennent topologiques.
6. [`docs/DEMO.md`](DEMO.md) — et le fil rouge, écran par écran.
