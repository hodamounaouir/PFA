# PROGRESS — Suivi de réalisation du projet de A à Z

> Compagnon d'exécution de la [`ROADMAP.md`](ROADMAP.md). La roadmap dit *quand une phase est finie*
> (Definition of Done) ; **ce fichier dit quoi faire, étape par étape, et où on en est.**
>
> **Comment l'utiliser** : cocher les cases au fil de l'eau ; mettre à jour le tableau de bord à chaque
> fin de séance de travail ; ne jamais commencer une phase avant que la précédente affiche ✅.

**Décision source de données (2026-07-20)** : montage **hybride** — dataset réel **Olist** (Kaggle)
rejoué jour par jour + **injection contrôlée** d'anomalies documentées dans `ground_truth.yaml`.
On ne génère pas de données ; on rejoue des données réelles et on en corrompt certaines, à des dates
choisies, de façon documentée.

**Décision agent générique (2026-07-28)** : l'agent doit fonctionner sur **n'importe quel dataset**,
Olist n'étant qu'un cas de test. Cinq conséquences structurantes, détaillées dans les phases 3 à 5 :

1. **Deux cycles au lieu d'un.** Un cycle *Découverte* (hors DAG, une fois par table) qui introspecte,
   profile une fenêtre de référence, classe chaque colonne par **rôle inféré** et propose un **contrat
   YAML versionné** validé par l'humain. Un cycle *Surveillance* (le graphe LangGraph, à chaque batch).
2. **Zéro nom de table ou de colonne en dur.** Tout vient d'`INFORMATION_SCHEMA` et du contrat. La
   détection sémantique s'applique à *toute* colonne classée catégorielle — São Paulo est attrapé par
   généricité, pas par cas particulier.
3. **Le contrat devient le 3ᵉ pilier de détection**, à côté du z-score et des dbt tests. Il est
   **versionné** (jamais figé) et construit sur une **période de référence propre (J1→J44)**, sinon il
   apprend les anomalies injectées comme normales.
4. **Le graphe passe à 8 nœuds** : `Propose` a trois issues — `approved` → `Apply`, `amend_contract` →
   `Amend` (le contrat avait tort, pas la donnée), `rejected` → `Log`. C'est le mécanisme
   anti-obsolescence du contrat.
5. **Nouveau garde-fou structurel : l'agent n'invente jamais une valeur.** Il peut isoler, mettre à
   NULL, exclure d'un agrégat — jamais deviner (8000 → 80). Au même rang que le HITL.

**Ce qui reste spécifique à Olist** : `ground_truth.yaml` — c'est le **benchmark**, pas l'agent.
Changer de dataset = écrire un nouveau `datasets/<nom>.yaml` et refaire le benchmark, sans toucher au code.

---

## Tableau de bord

| Phase | Titre | Durée estimée | Statut |
|:-:|-------|:-:|:-:|
| 0 | Fondations & accès | 3–5 j | ✅ terminé le 2026-07-21 |
| 1 | Dataset hybride : Olist + rejeu + injection | 1–1,5 sem | ✅ terminé le 2026-07-21 · §1.5 ajoutée le 2026-08-04 |
| 2 | Pipeline Medallion sans agent (baseline) | 2–3 sem | ✅ terminé le 2026-07-27 |
| 3 | Squelette agent LangGraph (8 nœuds) | 1–2 sem | ✅ terminé le 2026-08-03 |
| 4 | Socle générique + agent réel + `INCIDENTS` | 3 sem | ⬜ ⬅️ **prochaine** |
| 5 | HITL complet : pause, reprise, Apply borné | 1–2 sem | ⬜ |
| 6 | Observabilité & validation Streamlit | 1–2 sem | ⬜ |
| 7 | 🌟 Cause racine (lineage) + extensions | 1–2 sem | ⬜ |
| 8 | Benchmark chiffré | 1–2 sem | ⬜ |
| 9 | Documentation, ADR, soutenance | 1 sem | ⬜ |

Légende : ⬜ pas commencé · 🚧 en cours · ✅ terminé · ⏭️ sacrifié (extensions uniquement)

---

# Phase 0 — Fondations & accès

**Objectif** : un dépôt qui s'installe en une commande, tous les accès validés, zéro ligne de logique métier.

### 0.1 Dépôt & environnement
- [x] Créer le repo Git ; structure de dossiers : *(fait 2026-07-20 — remote `hodamounaouir/PFA`, 1er commit poussé)*
  ```
  ingestion/  dbt/  agent/  airflow/dags/  streamlit/  data/  benchmarks/  scripts/  tests/  docs/adr/
  ```
- [x] Environnement Python isolé (`uv init` puis `uv add ...`), versions figées (`uv.lock` commité) *(Python 3.11.15 épinglé ; deps : python-dotenv · dev : ruff, pytest)*
- [x] `Makefile` : cibles `setup`, `test`, `lint`, `check` *(`make check` vert)*
- [x] `.gitignore` : `.env`, `data/*.csv`, `dbt/target/`, checkpoints SQLite, `.venv/`
- [x] `.env.example` commité (clés sans valeurs) ; `cp .env.example .env` en local

### 0.2 Accès externes
- [x] **Snowflake** : trancher la question du trial (compte Tython ? trial différé ? second trial de secours ?)
      → consigner dans `docs/adr/001-snowflake-access.md` *(fait 2026-07-21 : trial perso de Hoda, déjà ouvert ; tout scripter pour pouvoir rejouer sur un second trial si expiration)*
- [x] Créer la base + les schémas : `RAW` (bronze), `STAGING` (silver), `MARTS` (gold), `OPS` (tables techniques)
      *(fait 2026-07-21 : base `DATA_QUALITY` via `scripts/setup_snowflake.py` — rejouable, auto-suspend COMPUTE_WH à 60 s)*
- [x] **LLM** : créer la clé Groq (gratuite), valider un appel « hello world » depuis Python
      *(fait 2026-07-21 : `llama-3.3-70b-versatile` répond via le SDK `groq`)*
- [x] **Kaggle** : ~~compte + `kaggle.json` pour télécharger Olist en ligne de commande~~
      *(décision 2026-07-21 : téléchargement **manuel** du zip Olist depuis kaggle.com → CSV déposés dans `data/olist/` (gitignoré). L'API Kaggle n'apporte rien ici ; à documenter dans le README en phase 1)*
- [x] Écrire `scripts/check_access.py` : teste Snowflake + LLM en une exécution, sortie ✅/❌ par service
      *(fait 2026-07-21 : Snowflake ✅ · Groq ✅ · + bonus contrôle des 9 CSV Olist ✅)*

### 0.3 Décisions à tracer maintenant
- [x] `docs/adr/008-hitl-pur-vs-scoring.md` — la décision v4 (contexte encore frais) *(fait 2026-07-21)*
- [x] `docs/adr/009-source-hybride-olist.md` — données réelles rejouées + injection vs génération Faker
      *(fait 2026-07-21 — avec la mesure réelle du fil rouge : 135 800 `sao paulo` vs 24 918 `são paulo`)*
- [x] Figer par écrit les **2 sources** de l'objectif O1 : (1) fichiers Olist (CSV), (2) une table Olist
      exposée via **API REST locale (FastAPI)** — PostgreSQL écarté *(figé dans l'ADR 009, §sources O1)*

**☑ Phase terminée quand** : un tiers clone le repo, lance `make setup`, et `python scripts/check_access.py`
est tout vert ; les ADR 001/008/009 existent.

---

# Phase 1 — Dataset hybride : Olist + rejeu + injection

**Objectif** : des batchs quotidiens **réels** (Olist rejoué par date) + des anomalies **contrôlées et
documentées** (`ground_truth.yaml`). C'est le contrat de vérité du projet.

### 1.1 Acquisition & exploration d'Olist
- [x] Télécharger le dataset Olist (Kaggle, ~120 Mo, 9 fichiers CSV) *(fait 2026-07-21, manuel → `data/olist/`)*
- [x] Explorer et documenter les 9 tables (notebook jetable ou `docs/dataset.md`) : clés, volumes,
      plages de dates, taux de nulls naturels *(fait 2026-07-21 → `docs/dataset.md` ; intégrité FK 100 %)*
- [x] Sélectionner le **sous-ensemble utile** (recommandé : `orders`, `order_items`, `order_payments`,
      `customers`, `products`, `geolocation`) — noter ce qu'on écarte et pourquoi
      *(validé 2026-07-21 : les 6 recommandées ; reviews/sellers/translation écartées, raisons dans dataset.md)*
- [x] **Vérifier le cas sémantique réel** : requête sur `geolocation_city` → confirmer les variantes
      (`são paulo` / `sao paulo` / `sao paulo - sp`…) et mesurer leur ampleur. C'est le futur fil rouge ;
      s'il est trop faible, le plan B est l'injection (1.3)
      *(confirmé 2026-07-21 : 135 800 `sao paulo` / 24 918 `são paulo` / 2 `sãopaulo` → plan B inutile ;
      requête témoin dans `tests/` à faire en 1.4)*

### 1.2 Simulateur de rejeu (`data/replay.py`)
- [x] Découper les données par **date de commande** (`order_purchase_timestamp`) : 1 jour = 1 batch
- [x] CLI : `python -m data.replay --day 2017-03-15` → écrit les fichiers du jour dans `data/incoming/`
      (le dossier que l'ingestion lira) *(fait 2026-07-21 ; garde-fou : refuse un jour hors fenêtre)*
- [x] Mode rattrapage : `--from ... --to ...` pour rejouer une plage (utile pour construire l'historique
      des profils vite)
- [x] Choisir la **fenêtre de rejeu** du projet (recommandé : ~90 jours dans une période dense de 2017-2018)
      et la figer dans la config *(2018-03-01 → 2018-05-31, 92 j, figée dans `data/config.py` avec le seed)*
- [x] Les tables de référence (produits, clients) sont livrées au jour 1 puis en delta
      *(products + geolocation en entier au J1 ; customers arrive en delta quotidien avec les commandes)*

### 1.3 Injecteur d'anomalies (`data/inject.py`)
- [x] Architecture : une classe par type d'anomalie, activée par config `(jour, table, paramètres)` —
      l'injecteur **modifie le batch du jour après rejeu**, il ne génère rien
      *(fait 2026-07-21 : `data/inject.py` — la config de l'injecteur EST `ground_truth.yaml` (source
      unique) ; marqueur `.injected` contre la double corruption ; seed dérivé de `config.py`)*
- [x] Types à implémenter :
  - [x] **Dérive de schéma** : renommage de colonne (`payment_value` → `amount` au J45) ✓ vérifié
  - [x] **Complétude** : 30 % de nulls sur `orders.customer_id` au J60 ✓ vérifié (51/171 vides)
  - [x] **Doublons** : 15 % des lignes de `order_items` au J75 ✓ vérifié (413 → 475, 62 doublons)
  - [x] **Fichier tronqué** : `orders` coupé à 30 % au J80 ✓ vérifié (139 → 42 lignes)
  - [x] **Sémantique (plan B)** : ~~inutile~~ — cas réel `sao paulo` confirmé massif (1.1), consigné
        dans `ground_truth.yaml` section `real_anomalies`
- [x] **Récidive** : nulls identiques J60 **et** J85 (même colonne, même taux, lié par `recidive_of`)
      → mesure du gain mémoire (T1 vs T2) en phase 8 ✓ vérifié (34/114 vides au J85)
- [x] `data/ground_truth.yaml` : pour chaque anomalie → jour, table, colonne, type, ampleur, dimension
      DAMA. **Écrit ici, jamais modifié après que l'agent tourne** (honnêteté du benchmark)
      *(fait 2026-07-21 : 5 anomalies injectées + 1 réelle (sémantique) ; cohérence day↔date vérifiée
      par l'injecteur au chargement)*

### 1.4 Verrous méthodologiques
- [x] Rejeu + injection **déterministes** (`--seed 42` pour les choix aléatoires de lignes) : deux
      exécutions produisent exactement les mêmes batchs
      *(fait 2026-07-21 : `tests/test_replay_determinism.py` — hash SHA-256 identiques sur double rejeu)*
- [x] Test automatique : `ground_truth.yaml` et les anomalies effectivement présentes dans les fichiers
      coïncident (compteur par type)
      *(fait 2026-07-21 : `tests/test_ground_truth_coherence.py` — 7 tests : marqueurs, schéma J45,
      taux de nulls J60/J85, doublons J75, troncature J80, récidive strictement identique)*
- [x] Vérifier que le cas sémantique provoque un **double comptage mesurable** dans un agrégat par ville
      (requête témoin conservée dans `tests/`) *(fait 2026-07-21 : `tests/test_semantic_case.py`,
      2 tests — la normalisation récupère >20 000 lignes ; skip automatique si dataset absent)*

**☑ Phase terminée quand** : `replay --from J1 --to J90` + injection produisent des batchs reproductibles ;
`ground_truth.yaml` est exhaustif ; le double comptage est prouvé par une requête.
✅ **Rempli le 2026-07-21**, puis **rouvert le 2026-08-04** (§1.5) pour rendre la fenêtre de référence propre.

### 1.5 Fenêtre de référence propre & chargement incrémental ✅ *2026-08-04 — rouverture assumée*

> **Pourquoi rouvrir une phase terminée.** Le contrat de la phase 4.2 se construit sur la fenêtre de
> référence. La mesure du 2026-08-04 a montré qu'elle portait **2 042 collisions naturelles** sur
> `geolocation_city` : le contrat aurait gravé `sao paulo` + `são paulo` comme deux villes légitimes,
> et le cas d'école du projet aurait été perdu **avant** d'avoir commencé. C'était le dernier moment
> où la correction restait honnête — `detect` (4.3) n'est pas écrit, donc aucune mesure n'est faussée
> rétroactivement. La règle du corrigé l'autorise explicitement : *modifiable pendant la construction,
> gelé dès que l'agent est évalué*.

- [x] **Décision de méthode** : la fenêtre **J1→J43 est entièrement propre** (`config.REFERENCE_END_DAY`),
      les anomalies n'existent que dans les lots qui arrivent **après**. Chaque jour chargé devient un
      événement que l'agent doit traiter — c'est aussi ce qui se montre en soutenance.
- [x] **Audit préalable des 5 colonnes texte du registre** : une seule est sale.
      `customer_city` 2 206/2 206 · `customer_state` 27/27 · `order_status` 6/6 ·
      `product_category_name` 73/73 · **`geolocation_city` 8 011/5 945** ⚠️
- [x] `data/prepare.py` — **3ᵉ opération du pipeline**, la seule qui *retire* du désordre. Trois règles
      déclarées dans `ground_truth.yaml` (jamais codées en dur : on doit pouvoir reconstruire *tout* ce
      qui a été fait au dataset) :
  - [x] `strip_accents_lower_collapse_spaces` : 8 011 → 5 967 (2 044 collisions)
  - [x] `fold_space_variants_on_majority` : 5 967 → 5 945 — replie `['arcoverde', 'arco verde']` sur la
        forme **majoritaire observée**, départage alphabétique. Ne décide jamais que deux villes sont la
        même : constate que le dataset les écrit déjà ainsi et tranche par le nombre.
  - [x] `repair_declared_mojibake` : 5 945 → 5 942 — `sa£o paulo`, `maceia³`, `´teresopolis`. **Corruption
        d'octets, pas d'accent** : rien dans la chaîne ne dit que `£` valait `ã`, donc on énumère.
        `4º centenario` **non réparé** volontairement — vraie commune du Paraná.
- [x] `semantic_variants` + **rampes étalées** dans `data/inject.py` : une anomalie peut se déclarer en
      plage avec des paliers, résolue au chargement en une entrée par jour. `inject_day` inchangé.
- [x] `ground_truth.yaml` : section `preparation`, anomalie `semantic_drift_j50` (J50→J92, paliers
      10/40/80 % sur `customer_city`, 18 villes déclarées), **`real_anomalies` supprimée** — tout ce que
      l'agent doit trouver est désormais daté et quantifié, donc mesurable en phase 8.
- [x] **Rechargement** : DROP des 6 tables RAW (un `TRUNCATE` aurait laissé la colonne `AMOUNT` créée par
      la dérive du J45 — la fenêtre doit être propre jusque dans son *schéma*), `_SCHEMA_HISTORY` vidée,
      rejeu + ingestion J1→J43, `dbt run`.
- [x] **Vérifié** : écart de cardinalité normalisée **= 0 sur les 6 colonnes** · `AMOUNT` absente du
      schéma et de l'historique · 0 marqueur `.injected` · `sao paulo` consolidé à 160 719 points en
      **une** ligne, sans fusionner les homonymes (São Paulo do Potengi/RN, de Olivença/AM, das
      Missões/RS, et celui de l'Acre restent distincts) · **dbt test : 18 PASS / 0 échec** (avant : 13
      PASS / 5 détections) — la baseline elle-même ne trouve plus rien à redire.
- [ ] ⚠️ **Dette ouverte** : `benchmarks/baseline_run.json` décrit encore l'ancien run de 92 jours. Il se
      régénérera **au fil du chargement progressif**, une ligne par jour, avant la phase 8.

---

# Phase 2 — Pipeline Medallion sans agent (baseline)

**Objectif** : Bronze → Silver → Gold de bout en bout, orchestré par Airflow, **sans une ligne d'IA**.
C'est aussi la **baseline du benchmark** — à figer.

### 2.1 Ingestion → Bronze ✅ (2026-07-22)
- [x] `ingestion/load.py` : lit `data/incoming/`, charge **brut** dans Snowflake `RAW` (aucune
      transformation, aucun rejet — tout en VARCHAR, référentiels products/geolocation chargés au J1 seul)
- [x] Métadonnées sur chaque ligne : `_ingested_at` (DEFAULT Snowflake), `_source`, `_batch_id`
- [x] **Idempotence** : recharger le même batch ne duplique rien (DELETE sur `_batch_id` puis réinsertion)
- [x] Capture du schéma observé à chaque ingestion → table `OPS._SCHEMA_HISTORY`
      (une ligne par colonne : nom, position ordinale — c'est ce que lira `read_schema_history` en phase 4)
- CLI : `--day` (1 jour, ce qu'Airflow appellera en 2.3) / `--from`/`--to` / défaut = fenêtre entière
- Dépendance ajoutée : `pyarrow` (requise par `write_pandas` ; l'extra `[pandas]` du connecteur exige
  pandas<3, incompatible avec le projet — on installe pyarrow directement)
- **Validé** : fenêtre entière chargée (92 jours transactionnels, 2018-03-01→2018-05-31 ;
  orders=20 926, order_items=24 179, order_payments=21 856, customers=21 023 ;
  products=32 951 et geolocation=1 000 163 au J1 seul). Idempotence prouvée (2 runs = mêmes comptes).
  Dérive de schéma J45 confirmée dans `_SCHEMA_HISTORY` : `amount` au seul 2018-04-14, `payment_value`
  les 91 autres jours — conforme à `ground_truth.yaml` (`schema_drift_j45` = rename d'un seul batch)

### 2.2 dbt : Silver puis Gold ✅ (2026-07-22)
- [x] Projet dbt (`dbt/`) + profil Snowflake (via `.env`, `env_var`) ; conventions `stg_`/`fct_` ;
      macro `generate_schema_name` → schémas Medallion exacts (STAGING/MARTS, sans préfixe dbt) ;
      cibles Makefile `dbt-debug`/`dbt-run`/`dbt-test`/`dbt-build` (chargent le `.env`)
- [x] Modèles **Silver** (6 vues `stg_`) : typage (`try_cast`/`try_to_timestamp`), clé `order_item_sk` ;
      **PAS** de dédoublonnage (les doublons J75 doivent survivre pour le test `unique`) ;
      `customer_city`/`geolocation_city` **laissées brutes** (trou sémantique)
- [x] Modèles **Gold** (5 tables `fct_`) : `daily_sales`, `sales_by_city_state`, `delivery_delays`,
      `avg_order_value`, + `geolocation_by_city` (démonstrateur du fan-out)
- [x] **dbt tests baseline** figés (`_staging.yml`) : `not_null`, `unique`, `relationships`,
      `accepted_values`. Attrapent les 4 anomalies faciles → nulls customer_id (85), payment_amount J45
      (150), doublons order_item_sk (62), troncature J80 via relationships (120 + 103). 13 PASS / 5 détections.
      **NB : ces 5 échecs sont les *détections* de la baseline, pas des bugs** (à traiter comme signal en 2.3)
- [x] Preuve `benchmarks/proof_semantic_gap.py` : la baseline **rate** le fan-out São Paulo
      (`fct_geolocation_by_city` : `sao paulo` 135 799 / `são paulo` 24 917 / `sãopaulo` 2 → 3 lignes,
      conforme à `ground_truth.yaml` `semantic_sao_paulo`)
- **Correction en cours de route** : le fan-out est ancré sur `geolocation_city` (pas `customer_city`,
  déjà ASCII chez Olist) → mart dédié `fct_geolocation_by_city` ajouté comme démonstrateur.
- Dépendance ajoutée : `dbt-snowflake`

### 2.3 Orchestration Airflow ✅ (fichiers 2026-07-24 — backfill exécuté sur le PC 2026-07-27)
> Airflow ne tourne pas sur le serveur (pas de Docker) : les fichiers sont écrits ici et
> versionnés ; le DAG s'exécute **sur le PC** (Windows + Docker Desktop). Cf. `airflow/README.md`.
- [x] Airflow en local (Docker Compose) — `airflow/Dockerfile` (image + venv **isolé** du pipeline)
      + `airflow/docker-compose.yaml` (LocalExecutor + Postgres, repo monté, `.env` Snowflake branché)
- [x] DAG `medallion_pipeline` : `replay` → `inject` (`--if-scheduled`) → `ingest_bronze` →
      `dbt run/test` (silver) → `dbt run/test` (gold) → `archive_baseline` — paramétré par `{{ ds }}`,
      `@daily`, `catchup=True`. Tests dbt tolérants : rc=1 (détections) = vert, rc=2 (erreur dbt) = rouge.
- [x] Archivage `benchmarks/archive_baseline.py` → `benchmarks/baseline_run.json` (une entrée/jour,
      confrontée à `ground_truth.yaml`). Ajout `--if-scheduled` à `data/inject.py` (additif, tests OK).
- [x] **Exécuté sur le PC** (2026-07-27) : `docker compose build` + `up`, DAG dépausé avec
      `catchup=True` / `max_active_runs=1` → **92 runs séquentiels verts** sur toute la fenêtre.
      RAW/STAGING/MARTS peuplés et interrogeables ; `benchmarks/baseline_run.json` archivé
      (**92 entrées**, commit `8ffd7a1`) — c'est la colonne « baseline » du tableau de la phase 8.

**☑ Phase terminée quand** : ~~le DAG est vert de bout en bout sur la fenêtre rejouée ; les 3 couches sont
peuplées et interrogeables ; la baseline rate le cas sémantique (prouvé) ; `baseline_run.json` est archivé.~~
✅ **Les 4 critères sont remplis (2026-07-27).** La baseline est figée : à partir d'ici, on ne la modifie
plus — c'est le point de comparaison de tout le reste du projet.

---

# Phase 3 — Squelette agent LangGraph (8 nœuds)

**Objectif** : le graphe tourne de START à END avec des stubs ; la mécanique **pause/reprise** est validée.
On teste la tuyauterie, pas l'intelligence.

> **Révision 2026-07-28** : 8 nœuds au lieu de 7, et `propose` a **3 issues** au lieu de 2 (ajout de
> `amend_contract` → nœud `amend`). Le reste de la phase est inchangé : les nœuds sont des stubs, donc
> la généricité décidée le 2026-07-28 ne coûte rien ici — elle se paie en phase 4.

```
START
  │
  ▼
profile ──► detect ──(rien d'anormal)──────────────────────────► log ──► END
               │ (anomalies)
               ▼
           diagnose                    ← seul nœud qui appelle le LLM
               │
               ▼
           propose  ⏸ interrupt — décision humaine
               │
      ┌────────┼──────────────────┐
 (approved)  (amend_contract)  (rejected)
      │        │                  │
      ▼        ▼                  │
    apply    amend                │
      │        │                  │
      ▼        │                  │
  validate     │                  │
      │        │                  │
      └────────┴──────────────────┴──► log ──► END
```

`log` est la **sortie unique** : aucun run ne peut se terminer sans laisser de trace. C'est structurel,
au même titre que « aucun chemin n'atteint `apply` sans approbation » — et ça se prouve par test.

### 3.0 Tracer la décision avant de coder
- [x] `docs/adr/010-agent-generique.md` : les 5 décisions du 2026-07-28 (deux cycles · zéro nom en dur ·
      contrat versionné comme 3ᵉ pilier · 8 nœuds / 3 issues · ne jamais inventer une valeur), avec les
      alternatives écartées — dont « découverte une seule fois puis contrat figé », rejetée pour cause
      d'obsolescence du contrat et de piège descriptif ↔ normatif
- [x] Mettre `README.md`, `ROADMAP.md`, `CAHIER_DES_CHARGES.md` (§5.2/5.3/5.4) et `docs/ARCHITECTURE.md`
      en cohérence : ~~ils décrivent encore un graphe à **7 nœuds** et 2 issues~~
      *(fait : les 4 fichiers prévus + `docs/DESIGN.md` et `CONTRIBUTING.md`, qui portaient les mêmes
      chiffres. Ajouts : §0bis du cahier (les 5 décisions du 2026-07-28), invariant **P6** « ne jamais
      inventer une valeur » dans ARCHITECTURE (5 → 6 invariants), règle **R7** dans CONTRIBUTING
      (6 → 7 règles), §5.2 du cahier et §5.1 d'ARCHITECTURE réalignés sur `agent/state.py` réel.
      Le tableau d'avancement du README, resté bloqué à « phase 0 en cours », est resynchronisé.)*

### 3.1 Le graphe
- [x] `agent/state.py` : `AgentState` (TypedDict) — base §5.2 du cahier, dont `logs: Annotated[list, add]`.
      **Champs ajoutés le 2026-07-28** : `dataset` (nom du registre), `contract` (le contrat chargé),
      `contract_version`, et `human_decision` qui accepte désormais `approved | rejected | amend_contract`
- [x] `agent/nodes/` : les **8 nœuds en stub** (valeurs en dur) : `profile`, `detect`, `diagnose`,
      `propose`, `apply`, **`amend`**, `validate`, `log`
- [x] `agent/graph.py` : assemblage + les **2 conditional edges** :
      `detect → (diagnose | log)` et `propose → (apply | amend | log)` ⬅️ *3 branches*
      *(fait : `build_graph()` / `build_agent(checkpointer=None)` ; aiguillages `route_after_detect` et
      `route_after_propose`, tous deux avec un `path_map` explicite — un nom hors liste fait échouer le
      run au lieu de router au hasard. Défaut de `route_after_propose` = `log`, jamais `apply` : `None`,
      `rejected` et toute valeur inattendue retombent sur le journal. Les 4 chemins tournent de bout en
      bout)*
- [x] Export PNG du graphe (`draw_mermaid_png()`) → `docs/img/agent_graph.png` (README + soutenance)
      *(fait via `scripts/export_graph.py`, **régénérable d'une commande** plutôt que produit une fois
      à la main : un diagramme extrait du code ne ment pas au moment où on le génère, mais il vieillit
      dès que le câblage change. Deux sorties : `agent_graph.mmd` (hors ligne, rendu nativement par
      GitHub, diffable) et `agent_graph.png` (rapport et diapos, rendu via mermaid.ink). Le mermaid
      écrit à la main dans le README a été remplacé par l'image générée — c'était exactement le type
      de doc qui a dérivé jusqu'à décrire un graphe à 7 nœuds.)*

### 3.2 Pause & reprise (le mécanisme critique) ✅
- [x] Checkpointer `SqliteSaver` branché à la compilation
      *(`agent_persistant()` dans `graph.py` — une seule façon d'ouvrir le graphe persistant, donc une
      seule façon de se tromper de base de checkpoints. Plus `thread(id)` et `proposition_en_attente()`,
      qui isolent les conventions LangGraph au lieu de les disséminer)*
- [x] `propose` appelle `interrupt()` avec la proposition comme payload
      *(conséquence assumée : `propose` n'est plus appelable hors d'un graphe — un nœud dont la raison
      d'être est de suspendre n'a pas de sens isolé. Les parties pures ont été extraites dans
      `build_proposal()` et `lire_reponse()`. **Aucun contournement**, pas même pour les tests (R3).
      Vérifié : sans checkpointer le run est **bloqué** sur `propose`, jamais « passe outre » — donc
      `apply` reste inatteignable même en oubliant la persistance)*
- [x] Script CLI `scripts/decide.py <thread_id> approve|reject|amend` : injecte la décision
      (`Command(resume=...)`) → le graphe reprend
      *(sans verbe : affiche la proposition en attente. `--by` trace le décideur, `--fix` porte la
      correction réécrite par l'humain — refusé sur `reject`/`amend`, qui n'écrivent rien dans les
      données. Invoqué en `-m scripts.decide`, comme `data.replay` et `benchmarks.archive_baseline`)*
- [x] **Test clé** : lancer un run → interruption → **tuer le process** → relancer → la décision reprend
      le graphe exactement après `propose`
      *(le run est lancé par un vrai `subprocess` qu'on laisse mourir ; seul le fichier de checkpoints
      est partagé. Fait deux fois : en direct, et via `scripts/decide.py` — le chemin réel. Plus :
      un run en pause n'écrit rien, et deux `thread_id` simultanés ne se mélangent pas)*
- [x] **Dialogue avant décision** ⬅️ *ajouté le 2026-08-03, à la demande* : une **4ᵉ réponse**,
      `question`, qui n'est **pas** une décision — elle diffère au lieu de clore. Le graphe repart vers
      `diagnose`, la réponse revient, la proposition attend de nouveau. C'est la seule branche qui
      **remonte** dans le graphe.
      *Pourquoi renvoyer à `diagnose` plutôt que répondre dans `propose` : c'est ce qui préserve R1
      (« le LLM n'est appelé que dans Diagnose »). Deux nœuds qui parlent au modèle, ce serait deux
      endroits à auditer, à simuler et à surveiller.*
      *Pourquoi c'est utile : un humain à qui on ne laisse que trois boutons approuve vite et mal.
      C'est la faiblesse connue du HITL (§5.3 de `DESIGN.md`). Le dialogue est conservé dans l'état,
      donc dans `INCIDENTS` — on pourra montrer « a posé deux questions, obtenu ces réponses, **puis**
      approuvé » plutôt qu'un simple taux d'approbation.*
      *Garde-fous : plafond de 10 échanges (sans lui, la boucle peut tourner sans fin si le modèle est
      en panne) ; au-delà le run se clôt **sans décision**, rien n'est écrit. Une question vide n'en est
      pas une. Et **discuter ne rapproche pas de l'écriture** : un test vérifie P3 après cinq questions.*
      *CLI : `uv run python -m scripts.decide <run> ask "pourquoi … ?"`*
- [x] **Vérification par mutation** — trois sabotages, tous détectés : `propose` ne s'interrompt plus →
      échecs sur les 4 chemins et P3 · la décision humaine est ignorée → 12 échecs · le checkpointer est
      neutralisé → 46 échecs.
- ⚠️ **Limite rencontrée** : `Command(resume=None)` lève un `UnboundLocalError` **dans LangGraph 1.2.9**
      (`_loop.py`, `resume_is_map` référencé avant affectation). Le cas « aucune décision » n'est donc
      pas injectable au niveau du graphe ; il est couvert au niveau unitaire (`lire_reponse(None)`,
      `route_after_propose`). À re-tester lors d'une future montée de version.
- [x] Note de conception : **un seul mécanisme d'interruption, trois usages** (corriger / amender /
      refuser) — et il resservira tel quel pour la validation des contrats en phase 4
      *(écrite dans l'en-tête de `agent/nodes/propose.py` et dans `scripts/decide.py`)*

### 3.3 Premier vrai appel LLM ✅
- [x] `diagnose` : appel Groq réel → sortie forcée `{root_cause, proposed_fix, explanation}`
      *(nouveau module `agent/llm.py` : **une seule frontière réseau** dans tout le projet — si un
      appel LLM apparaît ailleurs, la règle R1 est cassée et ça se voit d'un `grep`. Modèle
      `llama-3.3-70b-versatile`, `temperature=0`.)*
- [x] **Écart assumé au plan** : `PydanticOutputParser` (LangChain) remplacé par le **mode JSON natif
      de Groq** (`response_format={"type": "json_object"}`) + validation Pydantic. Le parser injecte des
      consignes de format dans le prompt puis parse ; le mode JSON **empêche le format invalide
      d'exister**. Les deux barrières sont conservées : l'API garantit un JSON *valide*, Pydantic
      garantit que c'est le *bon* JSON (un modèle peut renvoyer `cause` au lieu de `root_cause`).
- [x] **Barrière R2 explicite** : `construire_contexte()` choisit champ par champ ce qui part au modèle,
      au lieu de faire confiance au profil. Testé avec un profil qui transporte un échantillon de lignes
      — la tentation exacte de la phase 4 : il ne franchit pas la barrière.
- [x] Gestion d'échec : l'état porte `diagnosis = None` → le run continue vers `propose` en
      « à traiter manuellement » (pas d'exception qui tue le graphe)
      *(réseau coupé, clé absente, quota dépassé, JSON illisible, champ manquant → même mode dégradé.
      L'humain voit alors les **faits** établis par `detect` sans LLM, et décide sans explication.)*
- [x] **Garde-fou de test structurel** (`tests/conftest.py`) : deux fixtures `autouse` — la couture LLM
      est simulée pour toute la suite, **et** la création d'un client Groq lève. Écrit après s'être fait
      prendre : trois helpers appelaient la vraie API, la suite est passée de 6 à 172 s et dépendait du
      réseau. Une règle qu'on peut oublier n'est pas une règle.
- [x] **Vérification par mutation** — trois sabotages, tous détectés : suppression du `try/except` →
      les tests de panne tombent · fuite du profil complet dans le contexte → `test_le_modele_ne_voit_
      que_des_agregats` tombe · retrait de la consigne « ne jamais deviner » → le test de consigne tombe.
- Dépendance déclarée : `pydantic` (l'agent s'en sert directement, il ne doit pas dépendre du hasard
  d'une dépendance transitive de LangGraph).

### 3.4 Tests
> Écrits dans `tests/test_agent_graph.py` (85 tests). Principe retenu : **chaque preuve est établie
> deux fois**, une fois *topologiquement* (inspection du graphe compilé — vaut pour toute exécution,
> y compris celles auxquelles on n'a pas pensé) et une fois *dynamiquement* (exécution réelle sur un
> jeu de décisions hostiles). Une preuve statique seule laisserait passer un aiguillage qui ment ;
> une preuve dynamique seule ne couvrirait que les cas testés.

- [x] Les **4 chemins** du graphe — 4 tests, LLM mocké :
      rien d'anormal / refusé / **amendé** / approuvé
      *(+ un test qui vérifie que les 4 parcours sont réellement distincts, et un test de
      préconditions : si le stub `profile` changeait, les autres deviendraient faussement verts)*
- [x] **Test de preuve P3** : instrumenter `apply` → prouver qu'aucune exécution ne l'atteint sans
      `human_decision == "approved"` (parcours exhaustif — la branche `amend` ne doit **pas** y mener)
      *(topologie : `apply` n'a qu'une arête entrante, `("propose", "approved")` · exécution : 16
      décisions invalides × 2 profils de batch, `apply` espionné, jamais atteint. Plus le test
      réciproque — `apply` **est** atteint quand c'est approuvé — sans lequel un `apply` devenu
      inatteignable en toutes circonstances passerait pour un succès)*
- [x] **Test de sortie unique** : les 4 chemins passent tous par `log` avant `END`
      *(topologie : `log` est le seul nœud relié à END · exécution : `log` apparaît exactement une
      fois en fin de parcours, y compris avec une décision absurde)*
- [x] **Vérification par mutation** — trois sabotages volontaires de `graph.py`, chacun bien détecté :
      `propose` approuve tout → 57 échecs · `amend` recâblé vers `apply` → 6 échecs dont les deux
      tests P3 dédiés · `validate` branché sur `END` → 3 échecs dont le test de sortie unique.
      Un test qui ne peut pas échouer ne prouve rien.
- [x] Test pause/reprise après redémarrage du process *(fait avec l'étape 3.2, dont il dépendait)*

**☑ Phase terminée quand** : ~~les 4 chemins passent en test ; la reprise post-redémarrage marche ; les
tests de preuve P3 et « sortie unique » passent ; le PNG du graphe est généré.~~
✅ **Les 4 critères sont remplis (2026-08-03).** 184 tests verts. Ce qui est acquis et ne doit plus
régresser : `apply` inatteignable sans approbation (P3, prouvé topologiquement *et* à l'exécution),
`log` en sortie unique, la pause qui survit à la mort du process, et un LLM dont la panne ne tue pas
le run. Les nœuds restent des **stubs** : c'est la tuyauterie qui est validée, pas l'intelligence.

---

# Phase 4 — Socle générique + agent réel + table `INCIDENTS`

**Objectif** : les stubs deviennent réels — l'agent lit vraiment Snowflake, détecte vraiment, journalise
vraiment, et commence à se souvenir. **Et il le fait sans un seul nom de table écrit en dur.**

> **Révision 2026-07-28** : c'est ici que se paie la généricité. La phase gagne deux blocs (**4.0** socle
> interchangeable, **4.2** cycle Découverte + contrats) et passe de 2 à ~3 semaines. Découpage conseillé :
> **4a = 4.0 → 4.2** (le socle générique, testable sur Olist *et* sur un second dataset jouet) puis
> **4b = 4.3 → 4.6** (la détection et la mémoire).

```
CYCLE A — DÉCOUVERTE  (hors DAG, une fois par table, puis à la demande)

  connect ──► introspect ──► profile_ref ──► characterize ──► propose_contract ⏸ ──► save_contract
                                                                      │                    │
                                                              décision humaine     contracts/<table>.v1.yaml

CYCLE B — SURVEILLANCE  (le graphe 8 nœuds de la phase 3, à chaque batch, dans Airflow)
```

### 4.0 Socle générique — ce qui rend l'agent interchangeable ✅ *terminé le 2026-08-03*

> **Écart au plan assumé** (ADR 010, décision 7) : pas de `agent/connectors/base.py`. Le projet n'a
> qu'un backend réel — Postgres a été écarté par l'ADR 009, et l'API REST/FastAPI de O1 est une source
> d'**ingestion**, pas un connecteur d'agent (confusion de catégorie du plan initial, corrigée ici).
> Une classe abstraite pour une implémentation unique aurait été de la généralisation spéculative. On
> garde la **couture** — tout le SQL sous `agent/connectors/` — et c'est un **test** qui l'impose.

- [x] `agent/connectors/__init__.py` : le contrat des trois méthodes (`list_tables`, `get_schema`,
      `profile`) + une fabrique nom → connecteur. `profile` reçoit `(batch_column, batch_id)` et
      **jamais un fragment de SQL** — sinon du SQL existerait au-dessus de la couture.
- [x] `agent/connectors/snowflake.py` : le seul fichier de `agent/` où du SQL a le droit d'exister
- [x] **Une table déclarée mais absente ne fait pas lever le connecteur** : `get_schema` et `profile`
      retournent `None`. C'est ce qui permet à la famille *inventaire* de 4.3 de la traiter comme une
      **anomalie constatée** plutôt que comme un plantage. Un agent qui casse quand la donnée manque
      ne détecte rien — il disparaît au moment où on a le plus besoin de lui.
- [x] **Symétrique** : un registre *mal écrit* (`batch_column` inexistante), lui, échoue bruyamment.
      Ce n'est pas une anomalie de donnée mais une erreur de déclaration — la masquer profilerait la
      table entière en croyant filtrer un lot, ce qui diluerait l'anomalie cherchée.
- [x] `datasets/olist.yaml` : le **registre** — 17 tables sur les 3 couches. Gold n'a pas de
      `batch_column` (un agrégat est reconstruit en entier) : le connecteur profile alors toute la
      table, et c'est le comportement correct.
- [x] `agent/registry.py` : chargement + **validation stricte** — couche fermée, champ inconnu refusé,
      doublon refusé. Un registre fautif échoue au chargement, pas trois nœuds plus loin.
- [x] Test de généricité : un dataset RH étranger à Olist, branché par un YAML + un connecteur en
      mémoire, **sans qu'une ligne de `agent/` change**
- [x] `test_aucun_sql_hors_des_connecteurs` : le garde-fou qui remplace la classe abstraite
- [x] `OPS` exclu de `list_tables()` — la mémoire de l'agent n'est pas le système observé
      (ADR 010, décision 8)
- [x] Ce qui reste **déclaré** et non inférable, documenté honnêtement : la colonne de batch, les
      tables à surveiller, les règles métier (injectées par l'humain à la validation du contrat)
- [ ] ⏭️ *Reporté, option ouverte* : un connecteur CSV/pandas (~1 j) ferait passer la promesse de
      « portable d'un schéma à l'autre » (démontré) à « portable d'un backend à l'autre » (démontrable
      en direct devant un jury). Seul endroit de la phase 4 où un jour achète une réponse de soutenance.

### 4.1 Les tools (un par un, testés isolément)

> **Décision préalable, tranchée le 2026-08-03** ([ADR 004](docs/adr/004-langgraph-vs-function-calling.md)) :
> les tools sont bien décorés `@tool` comme le demande le §5.6 du cahier — mais **`bind_tools`
> n'apparaît nulle part**. Le décorateur est un *format* ; le tool-calling est une *délégation de flux*,
> celle que `DESIGN.md` §2 rejette. Un test l'impose, comme le test anti-fuite SQL de 4.0.
> Conséquence : les signatures ne prennent que des chaînes, et le tool résout le connecteur lui-même —
> soit exactement la forme dont Airflow aura besoin en 4.5.

- [x] **4.1.1** `read_schema_history` : lit `OPS._SCHEMA_HISTORY` via `agent/connectors/ops.py`
      *(2ᵉ et dernier fichier de `agent/` autorisé à contenir du SQL — la mémoire de l'agent, pas le
      système observé, cf. ADR 010 décision 8)*
  - [x] ⚠️ **Deux pièges hérités de la phase 2.1, absorbés ici** : l'historique enregistre le nom du
        **fichier CSV** (`orders`, pas `RAW.ORDERS`) et la **casse du CSV** (`order_id`), alors que
        Snowflake rend `ORDER_ID`. Comparer naïvement ferait apparaître **toutes** les colonnes comme
        renommées, à chaque run, sur chaque table. On normalise en majuscules avant de rendre.
  - [x] **Portée à dire honnêtement** : `_SCHEMA_HISTORY` n'est écrite que par l'ingestion, donc elle
        ne couvre que **Bronze**. La dérive de schéma en Silver/Gold devra se mesurer contre le
        contrat (4.2), pas contre cet historique.
- [x] **4.1.2** ⭐ `top_values` : les K valeurs les plus fréquentes d'une colonne. **Sans elle, aucune
      détection sémantique** — l'agent sait aujourd'hui qu'il y a 8 000 villes distinctes, pas
      lesquelles. Une requête par colonne, donc un critère de choix est nécessaire (provisoirement
      « texte + faible cardinalité », le vrai critère vient de la caractérisation en 4.2).
  - [x] **Le contrat des connecteurs passe de 3 à 4 méthodes** ([ADR 010](docs/adr/010-agent-generique.md),
        décision 9a). Écarté : faire remonter le top-K depuis `profile`. Argument de **coût**, pas de
        style — `profile` fait *un* passage sur la table, un top-K coûte un `GROUP BY` **par colonne**.
        L'imposer à toutes multiplierait le coût du profilage par le nombre de colonnes, pour rien sur
        un identifiant ou du texte libre.
  - [x] ⚠️ **R2 change de nature** (décision 9b) : jusqu'ici le modèle ne recevait que des chiffres —
        il n'y avait *rien* à fuiter. Une valeur + sa fréquence reste une **distribution** et non une
        ligne, mais la garantie devient **conditionnelle** : elle ne tient que sur des colonnes
        catégorielles. Trois mesures — une seule colonne nue dans la projection (testée sur le SQL
        émis), `coverage` rendu avec la réponse, et un tool qui **constate** au lieu de se censurer.
  - [x] **Colonne absente → `None`, colonne de lot fausse → exception.** La symétrie du connecteur : ce
        qui est *observé* se constate (une colonne disparue **est** l'anomalie du J45 — lever tuerait
        le run sur l'incident qu'il cherche), ce qui est *déclaré* échoue bruyamment.
  - [x] **Départage des ex æquo** (`ORDER BY COUNT(*) DESC, valeur ASC`) : sans lui, le K-ième rang
        basculerait d'un run à l'autre et la détection deviendrait intermittente. Même leçon qu'au
        repli des variantes en 1.5.
  - [x] `connectors.fermer()` : `close()` reste **hors** du contrat (décision 9c) — un connecteur en
        mémoire n'a rien à fermer, et la règle vit à un seul endroit plutôt que dans chaque tool.
- [ ] **4.1.3** Statistiques robustes : **médiane + MAD**, pas moyenne + écart-type *(sinon l'anomalie
      du J60 entre dans l'historique et fait paraître la récidive du J85 moins grave)*. ⚠️ Sur Bronze
      tout est VARCHAR : `AVG` échouerait — `TRY_CAST`, ou stats numériques réservées à Silver/Gold.
- [ ] **4.1.4** Fraîcheur — dépend de savoir quelle colonne est temporelle, donc partiellement de 4.2
- [ ] **4.1.5** `profile_table` : l'assembleur — agrégats du connecteur + top-K + stats robustes, en
      une seule fiche. C'est le point où 4.1 devient consommable par 4.3.
      *(⚠️ min/max sont indispensables : une seule ligne aberrante — 8000 dans une colonne à [1–100] —
      ne déplace presque pas la moyenne mais fait exploser le max. Déjà livrés en 4.0.)*
- [ ] **4.1.6** `run_sql` : **lecture seule** — rejet par liste de mots-clés d'écriture + journalisation
      de chaque requête. *(C'est le premier brouillon du garde-fou d'`Apply`, règle R4, phase 5.)*
- [ ] **4.1.7** DDL `OPS.INCIDENTS` + `write_log` — **le DDL est monté depuis 4.4** : il fait dix
      lignes, et sans lui `write_log` se code à l'aveugle
- [ ] **4.1.8** `generate_dq_rule` : produit un dbt test YAML rattaché à une dimension DAMA
      *(en dernier — rien avant 4.5 n'en dépend)*

**Chemin critique vers la détection** : 4.1.1 ✅ · 4.1.2 ✅ · 4.1.3 · 4.1.5. Avec ces quatre-là, `detect`
(4.3) peut attraper les 4 anomalies injectées **et** le cas São Paulo. `run_sql`, `write_log` et
`generate_dq_rule` ne bloquent rien.

### 4.2 Cycle Découverte : caractérisation & contrats ⬅️ *nouveau*
- [ ] `agent/characterize/` : **classer chaque colonne par rôle inféré** — c'est le moteur de généricité

  | Rôle | Reconnu à | Contrôles qui en découlent |
  |---|---|---|
  | identifiant | cardinalité ≈ nb lignes, non-null | unicité, nulls, format |
  | clé étrangère | valeurs ⊂ identifiants d'une autre table | intégrité référentielle, orphelins |
  | catégoriel | texte, cardinalité faible | valeurs nouvelles/disparues, **collisions sémantiques**, distribution |
  | numérique | type numérique, cardinalité élevée | bornes, moyenne/σ, outliers, négatifs/zéros |
  | temporel | type date/timestamp | fraîcheur, dates futures, trous, monotonie |
  | texte libre | texte, cardinalité élevée | nulls + longueurs **seulement** (surtout pas de valeurs acceptées) |

- [ ] `scripts/discover.py <dataset>` : introspection → profilage de la **fenêtre de référence
      J1→J44** (⚠️ *avant* la 1ʳᵉ injection, sinon le contrat apprend les anomalies comme normales) →
      caractérisation → proposition de contrat
- [ ] **Validation humaine du contrat** (même `interrupt()` qu'en 3.2) : les bornes proposées sont
      *descriptives* (« observé entre 1 et 100 »), l'humain les rend *normatives* (« oui, 100 est une
      vraie borne métier »). C'est le moment où le métier entre dans le système.
- [ ] **Piège descriptif ↔ normatif** : la découverte doit *critiquer* ce qu'elle trouve, pas seulement
      l'enregistrer. Elle fait tourner la détection de collisions **pendant** la découverte, sinon le
      contrat grave `sao paulo` + `são paulo` comme deux valeurs légitimes et le cas d'école est perdu.
      → clause attendue : `cardinalité_normalisée == cardinalité_brute`
- [ ] `contracts/<table>.v1.yaml` **versionnés dans git** ; `agent/contracts/loader.py` les charge au runtime

### 4.3 Profile & Detect réels
- [ ] `profile` : appelle `profile_table` + **persiste le profil du jour** dans `OPS._PROFILES`
      (ordre impératif : lire l'historique **avant** d'y écrire le profil du jour)
- [ ] `detect` — **cinq familles**, toutes déterministes, toutes génériques :
  - [ ] **inventaire** ⬅️ *ajouté le 2026-08-03* : la liste des tables **déclarées** dans
        `datasets/<dataset>.yaml` confrontée à celles **réellement présentes** (`list_tables()`).
        C'est la seule famille qui s'exerce **avant** de profiler quoi que ce soit — et la seule qui
        puisse constater qu'il n'y a rien à profiler. Trois écarts à produire :
    - [ ] **table déclarée absente** — l'incident le plus grave qui puisse arriver. Sans cette famille,
          le connecteur lèverait et le run planterait : personne ne saurait *pourquoi*, et l'anomalie
          serait masquée par un bug apparent. L'agent doit la **constater**, pas trébucher dessus.
    - [ ] **table nouvelle non déclarée** — elle n'est pas surveillée, et personne ne le sait
    - [ ] **hypothèse de renommage** : une table déclarée a disparu **et** une table nouvelle porte un
          schéma identique. `detect` n'énonce que le fait (« A absente, B nouvelle, schémas
          identiques ») ; c'est `diagnose` qui formule « probablement un renommage », et l'humain qui
          tranche. Répartition habituelle : le code constate, le LLM suppose, l'humain décide.
  - [ ] dérive de **schéma** : diff du schéma du jour vs `_SCHEMA_HISTORY` + contrat
  - [ ] **violation de contrat** ⬅️ *nouveau* : confrontation aux clauses du YAML (bornes, unicité,
        nulls interdits, valeurs acceptées, cohérence normalisée)
  - [ ] dérive **statistique** : écart du profil du jour vs les N derniers jours (`_PROFILES`)
  - [ ] **collisions sémantiques** : normalisation (casse/accents/espaces) des top-K valeurs de
        **toute colonne classée catégorielle** → clusters de collision (attrape `sao paulo`/`são paulo`)
  - [ ] intégration des **échecs dbt test** du run comme anomalies déjà confirmées
- [ ] ⚠️ **Question ouverte, à trancher en 4.3** : quelle issue pour « le **registre** a vieilli » ?
      Une table renommée n'est ni une donnée fausse (`approved`), ni un contrat périmé
      (`amend_contract`), ni un cas isolé (`rejected`) — c'est `datasets/<dataset>.yaml` qui ne décrit
      plus la réalité. Deux options : élargir `amend_contract` (même idée : « ce que j'ai déclaré est
      faux, pas la donnée »), ou ajouter une 4ᵉ issue. Trancher **avant** d'écrire `detect`, et
      consigner dans l'ADR 010.
- [ ] **Statistiques robustes** : médiane + MAD plutôt que moyenne + écart-type — sinon l'anomalie du J60
      entre dans l'historique, gonfle σ, et la récidive du J85 paraît *moins* grave (contamination de
      la référence). Plancher sur σ pour le cas « historique parfaitement constant » (0 % de nulls
      → division par zéro).
- [ ] **Démarrage à froid** : pas de détection statistique avant N jours d'historique (N ≈ 15–30).
      Chez Olist c'est confortable : 1ʳᵉ injection au J45, donc 44 jours propres pour apprendre.
- [ ] Seuils de détection dans `agent/config.py` — ce sont des réglages de **détection**, pas des règles
      de décision (la décision, c'est l'humain)

### 4.4 La table `INCIDENTS` et la mémoire (dans les deux sens)
- [ ] DDL `OPS.INCIDENTS` (schéma §5.5 du cahier) — append-only
- [ ] `log` réel : une ligne par run, **quel que soit le chemin** (y compris « rien d'anormal » et
      « refusé » — un faux positif est une **donnée de mesure** pour la précision en phase 8)
- [ ] **Signature d'anomalie** ⬅️ *nouveau* — `(table, colonne, type, ordre de grandeur)`. C'est elle qui
      définit ce que veut dire « la même anomalie ». Granularité critique : trop large = l'agent devient
      aveugle (« plus jamais de nulls sur `customer_id` » le ferait taire même à 90 %).
- [ ] Tool `read_past_incidents` : SQL sur `INCIDENTS`, filtre `human_decision IS NOT NULL` (R5),
      match par signature. **La mémoire sert dans les deux sens** :
  - [ ] `approved` → l'agent **retrouve la solution** : au J85 il cite l'incident du J60 et propose
        la même correction (c'est l'objectif O7, mesuré T1 vs T2 en phase 8)
  - [ ] `rejected` → l'agent **se tait** : filtre appliqué entre `detect` et `diagnose`, l'écart est
        journalisé mais pas soumis. Il **reparle si l'ampleur change franchement** (30 % → 85 % de nulls
        n'est plus la même signature).
- [ ] Garde-fou anti-cécité : rien n'est supprimé, tout est en base — la liste des signatures en silence
      est requêtable (et affichée en phase 6, réactivable d'un clic)
- [ ] `diagnose` réel : prompt = profil + anomalies + métadonnées + incidents passés ; sortie parsée
      Pydantic ; garde-fou sur le SQL proposé (table concernée uniquement, pas de mot-clé destructeur —
      première ligne de défense, `apply` re-vérifiera)

### 4.5 Règles dynamiques & branchement Airflow
- [ ] ≥ 3 règles dbt générées (format, complétude, cohérence) écrites sur disque et **vertes** une fois
      réintégrées dans dbt
- [ ] Tâches Airflow `check_bronze` / `check_silver` / `check_gold` : invoquent l'agent avec
      `(dataset, layer, table, batch_id)` après chaque couche

### 4.6 Validation sur les anomalies réelles
- [ ] Rejouer la fenêtre avec injections : l'agent détecte le renommage (J45), les nulls (J60), les
      doublons (J75), la troncature (J80)
- [ ] **Le moment clé** ⭐ : l'agent signale le cluster `sao paulo` que la baseline rate
- [ ] Sur la récidive (J85) : `diagnose` **cite l'incident de J60** dans son contexte
- [ ] **Table de couverture** à produire — quel détecteur attrape quoi, contre quelle référence :

  | Anomalie | Détecteur | Référence |
  |---|---|---|
  | `schema_drift_j45` | schéma | dernier schéma connu |
  | `nulls_j60` | contrat + statistique | clause `not_null` + historique |
  | `duplicates_j75` | contrat (unicité) + statistique (volume) | clause unicité + historique |
  | `truncate_j80` | statistique | historique des volumes |
  | `nulls_j85` | idem J60 **+ mémoire** citant J60 | historique + `INCIDENTS` |
  | `semantic_sao_paulo` ⭐ | sémantique | le batch avec lui-même |
  | *(hors ground truth)* table absente ou renommée | **inventaire** | le registre `datasets/*.yaml` |

**☑ Phase terminée quand** : le socle tourne sur un second dataset sans modification de code ; les
contrats sont générés et validés ; l'agent tourne dans le DAG sur les 3 couches ; il détecte les 4
anomalies injectées + le cas sémantique réel ; chaque run a sa ligne `INCIDENTS` ; la récidive est
reconnue ; une anomalie refusée n'est plus resoumise.

---

# Phase 5 — HITL complet : pause, reprise, Apply borné

**Objectif** : la boucle complète proposition → décision humaine → application → vérification, avec les
garde-fous structurels. La deuxième jambe du projet.

> **Révision 2026-07-28** : la décision humaine a **3 issues** (`approved` / `amend_contract` /
> `rejected`), et un 4ᵉ garde-fou structurel s'ajoute : **l'agent n'invente jamais une valeur**.

### 5.1 Propose réel
- [ ] Construction de la proposition complète : anomalie, cause diagnostiquée, **SQL exact** de la
      correction, **impact estimé**, incidents similaires passés
- [ ] ⚠️ **L'impact est la ligne la plus importante** — sans elle l'humain ne peut pas juger. Exemple :
      « 1 ligne sur 351 » semble négligeable jusqu'à voir « panier moyen 42,30 → 65,00 (+53,7 %) ».
- [ ] `interrupt()` avec la proposition en payload ; état persisté (checkpointer)
- [ ] File des propositions en attente lisible **hors process** (jointure checkpointer ↔ `INCIDENTS`) —
      c'est ce que Streamlit affichera en phase 6

### 5.2 Garde-fou : ne jamais inventer une valeur ⬅️ *nouveau*
Face à une valeur hors bornes (8000 dans une colonne à [1–100]), l'agent **ne peut pas savoir** s'il
s'agit de 80,00 € en centimes, d'une faute de frappe, ou d'une vraie grosse commande. Proposer
« remplacer 8000 par 80 », c'est **fabriquer de la donnée qui n'a jamais existé**.

- [ ] Corrections **autorisées** : isoler en quarantaine · mettre à NULL + marquer · exclure des agrégats
      Gold (la valeur brute reste intacte en Bronze pour audit)
- [ ] Correction **interdite** : substituer une valeur devinée — rejet dans `apply` **même après
      approbation humaine**, exactement comme les mots-clés destructeurs
- [ ] Proposition par défaut sur un outlier : *isoler + exclure de l'agrégat*, jamais *remplacer*

### 5.3 Reprise, Apply borné, Amend
- [ ] Injection de la décision : `approved` / `amend_contract` / `rejected` + **identité du décideur +
      horodatage** → stockés dans `INCIDENTS`
- [ ] `apply` réel : transaction SQL ; vérifications **même après approbation** :
  - [ ] la requête ne touche que la table diagnostiquée
  - [ ] rejet des mots-clés destructeurs (`DROP`, `TRUNCATE`, `DELETE` sans `WHERE`…)
  - [ ] rejet de toute substitution de valeur devinée (§5.2)
  - [ ] comptage lignes affectées avant/après conservé dans le log
- [ ] `amend` réel ⬅️ *nouveau* : la donnée est juste, **le contrat avait tort** → écrit
      `contracts/<table>.v2.yaml`, journalise le diff de clause, **n'écrit rien dans les données**
- [ ] Distinguer les deux « non » dans l'UI et dans `INCIDENTS` :
      *« c'est normal et ça le restera »* → `amend_contract` (permanent) ·
      *« exceptionnel, rien à changer »* → `rejected` (silence par signature)
- [ ] `validate` réel : re-profilage → la métrique anormale est-elle revenue dans la normale ?
      échec → `validation_status = "failed_manual_review"`, **pas de re-tentative automatique**

### 5.4 Les tests de preuve (livrables, pas hygiène)
- [ ] **P3** : aucun chemin vers `apply` sans `human_decision == "approved"`
      (la branche `amend` ne doit **jamais** y mener)
- [ ] **P4** ⬅️ *nouveau* : une proposition qui substitue une valeur devinée est **rejetée par `apply`**
      même avec `human_decision == "approved"`
- [ ] **Pause/reprise** : interruption + redémarrage du process + reprise correcte
- [ ] **Apply borné** : requête hors table → rejet ; mot-clé destructeur → rejet
- [ ] **Amend n'écrit pas** : après `amend_contract`, aucune ligne de données modifiée (vérifié par
      comptage avant/après) ; seul le fichier de contrat change de version

### 5.5 Bout en bout
- [ ] Scénario **approbation** sur le cas sémantique : détection → diagnostic → proposition → approbation
      (CLI) → application (normalisation ville en Silver) → validation → journal
- [ ] Scénario **refus** : l'incident est journalisé, **aucune écriture** sur les données (vérifié) ;
      au run suivant la même signature **n'est plus resoumise**
- [ ] Scénario **amendement** : une valeur hors contrat légitime → contrat v2 → au run suivant, plus
      aucune alerte sur cette clause

**☑ Phase terminée quand** : les 5 tests de preuve passent ; les trois scénarios bout en bout
(approbation, refus, amendement) se déroulent sans terminal ouvert sur Snowflake.

---

# Phase 6 — Observabilité & validation Streamlit

**Objectif** : rendre visible ce que l'agent fait et pourquoi, et donner à l'humain son poste de décision.
**→ À la fin de cette phase, le projet est soutenable.**

### 6.1 Les vues
- [ ] **Dashboard BI** : agrégats Gold (ventes par ville/jour…) — l'écran où l'on *voit* les chiffres
      faux avant correction, puis corrigés après
- [ ] **Incidents** : historique complet depuis `INCIDENTS` (filtres : couche, table, statut, période)
- [ ] **Décision** : pour un incident — anomalie, raisonnement du LLM, cause racine, SQL proposé, impact,
      antécédents
- [ ] **Validation HITL** : propositions en pause, diff avant/après estimé, **impact chiffré**, boutons
      **✅ Approuver / 📝 Modifier le contrat / ❌ Refuser** → reprend réellement le graphe interrompu
- [ ] **Signatures en silence** ⬅️ *nouveau (2026-07-28)* : la liste de tout ce que l'agent ne signale
      plus (signature, qui a refusé, quand), **réactivable d'un clic**. C'est le garde-fou anti-cécité :
      sans cet écran, l'agent devient progressivement muet sans que personne s'en aperçoive.
- [ ] **Contrats** : consultation des `contracts/*.yaml` et de leur historique de versions

### 6.2 Intégration & démo
- [ ] Le clic Approuver/Refuser passe par le même mécanisme que `scripts/decide.py` (une seule voie de
      reprise, testée)
- [ ] Identité du validateur recueillie (même simple : champ nom) → `decided_by`
- [ ] Rejouer le **fil rouge complet à la souris** : casser (injection) → détecter → proposer → approuver →
      corriger → vérifier → journal — sans terminal

**☑ Phase terminée quand** : le scénario §9 du cahier est jouable entièrement à la souris ; le clic
débloque réellement le graphe ; les chiffres du dashboard BI changent après correction.

---

# Phase 7 — 🌟 Cause racine (lineage), puis extensions

**Objectif** : d'abord la cause racine (le différenciant le plus rentable), puis les extensions **dans
l'ordre**, chacune optionnelle. Tout ici est coupable si le temps manque.

### 7.1 Cause racine (O8)
- [ ] Parser `dbt/target/manifest.json` → graphe de dépendances des modèles
- [ ] Tool `lineage_impact` : « quels modèles aval dépendent de cette colonne ? » + chemin amont
- [ ] `diagnose` : sur une anomalie Gold, le contexte contient le chemin amont → le diagnostic désigne
      la transformation Silver responsable (la normalisation manquante)
- [ ] `propose` : l'**impact estimé** (n tables aval) affiché au validateur
- [ ] Streamlit : chemin Bronze → Silver → Gold surligné sur la vue Décision

### 7.2 Extensions (dans l'ordre)
- [ ] **E1 — Mémoire vectorielle** : Chroma + embeddings des incidents tranchés ; tool
      `search_past_incidents` (similarité) en complément du match SQL exact
- [ ] **E2 — Journal GitHub (MCP)** : nœud `github_log` après `log` — 1 issue par incident ; panne
      GitHub ⇒ file locale, le run ne doit jamais échouer
- [ ] **E3 — CI GitHub Actions** : `make check` (lint + tests, LLM mocké, sans clé API) à chaque push
- [ ] **E4 — Streaming** : Redpanda + producteur (remplace le rejeu) + consommateur micro-batch → même
      schéma RAW, l'aval inchangé

**☑ Phase terminée quand** (cause racine seule) : sur le fan-out en Gold, l'agent désigne la
normalisation manquante en Silver, et la proposition affiche l'impact aval.

---

# Phase 8 — Benchmark chiffré

**Objectif** : prouver la valeur. Sans cette phase, le projet est une démo ; avec, c'est une contribution.

### 8.1 Harness
- [ ] `benchmarks/run.py` : même fenêtre rejouée, deux bras — (a) baseline dbt tests (figée en phase 2),
      (b) agent — confrontés à `ground_truth.yaml`
- [ ] Chaque mesure répétée **≥ 3 fois** (LLM non déterministe) → moyenne + écart-type
- [ ] Une commande unique reproduit chaque chiffre

### 8.2 Métriques
- [ ] **Précision** et **rappel** (vs `ground_truth.yaml`) — la précision se calcule à partir des
      incidents `rejected` : c'est pour ça que même un faux positif doit être journalisé (§4.4)
- [ ] **Anomalies sémantiques détectées** (invisibles à la baseline) — inclut le cas réel `sao paulo`
- [ ] **MTTR** : délai détection → cause identifiée (agent vs estimation manuelle documentée)
- [ ] **Taux d'approbation** des propositions (qualité des diagnostics)
- [ ] **Gain mémoire** : T1 (J60) vs T2 (J85) sur l'anomalie récidivante

### 8.3 Rapport
- [ ] Tableau comparatif + synthèse
- [ ] Section **limites, écrite par nous** : échantillon, anomalies synthétiques injectées vs réelles,
      non-déterminisme, MTTR manuel estimé, validateur unique, risque de sur-ajustement au ground truth

**☑ Phase terminée quand** : amélioration mesurable sur ≥ 2 métriques dont le sémantique ; chiffres
reproductibles en une commande ; section limites honnête rédigée.

---

# Phase 9 — Documentation, ADR, soutenance

**Objectif** : qu'un tiers puisse reprendre le projet, et que le jury comprenne les choix.

### 9.1 Documentation finale
- [ ] README final : schémas à jour (dont `agent_graph.png` réel), installation, exécution du fil rouge
- [ ] Relire tous les ADR (001 → 010) — ils ont été écrits au fil de l'eau, ici on ne fait que relire
- [ ] Démo de généricité : brancher un dataset inconnu du jury en direct (nouveau `datasets/*.yaml`
      + découverte) — la preuve la plus forte que l'agent n'est pas cousu main pour Olist
- [ ] Section limites connues & perspectives (extensions non réalisées, OpenMetadata)
- [ ] Ce fichier `PROGRESS.md` à jour — il raconte l'histoire réelle du projet

### 9.2 Soutenance
- [ ] Support structuré autour du **fil rouge** : un seul incident démontre O1→O8
- [ ] Démo live : injection en direct d'une anomalie → cycle complet à la souris dans Streamlit
- [ ] **Répéter la démo ≥ 3 fois** ; enregistrer une vidéo plan B
- [ ] Préparer les réponses aux questions anticipées ([`DESIGN.md`](docs/DESIGN.md)) : « pourquoi pas
      dbt test seul ? » (§1) · « votre agent n'est qu'un système de suggestion ? » (§5.3) · « et si
      l'humain approuve sans lire ? » (taux d'approbation mesuré)

**☑ Phase terminée quand** : un tiers rejoue le fil rouge en suivant uniquement le README ; la démo tient
dans le temps imparti, testée en conditions réelles.

---

## Journal de bord

> Une ligne par séance de travail significative — c'est ce qui permettra de raconter le projet en
> soutenance (et de remplir le rapport de stage sans effort de mémoire).

| Date | Phase | Fait | Décisions / blocages |
|------|:-:|------|----------------------|
| 2026-07-20 | — | Refonte v4 de la documentation (HITL pur) ; décision source hybride Olist | ADR 008 et 009 à rédiger en phase 0 |
| 2026-07-20 | 0 | Repo GitHub `hodamounaouir/PFA` + structure + 1er commit poussé ; env Python 3.11 (uv), Makefile, .gitignore, .env.example | Identité git = compte perso |
| 2026-07-21 | 0 | ✅ **Phase 0 terminée** : base `DATA_QUALITY` (RAW/STAGING/MARTS/OPS) via script rejouable, auto-suspend 60 s ; clé Groq validée ; Olist (9 CSV) sur le serveur ; `check_access.py` tout vert ; ADR 001/008/009 | Trial Snowflake perso (22 j restants) ; Kaggle API remplacée par téléchargement manuel ; source O1 n°2 = API REST FastAPI ; fil rouge `sao paulo` confirmé (85/15) |
| 2026-07-21 | 1 | ✅ **Phase 1 terminée** : exploration → `docs/dataset.md` ; fenêtre 2018-03-01→05-31 figée ; `replay.py` (92 j rejoués) ; `inject.py` + `ground_truth.yaml` (5 anomalies vérifiées + cas réel São Paulo) ; 12 tests verts (témoin, déterminisme, cohérence corrigé↔batchs) | 6 tables retenues ; ground_truth = config d'injection (source unique) ; plan modifiable jusqu'au benchmark, gelé ensuite |
| 2026-07-22 | 2 | 🚧 **2.1 Ingestion Bronze** : `ingestion/load.py` (brut→RAW, VARCHAR, idempotent, `OPS._SCHEMA_HISTORY`) ; fenêtre entière chargée (92 j transactionnels + référentiels au J1) ; idempotence prouvée ; dérive schéma J45 (`payment_value`→`amount`) confirmée conforme au corrigé | pyarrow ajouté (write_pandas) ; `--day` = ce qu'Airflow appellera en 2.3 ; backfill manuel ≠ incrémental auto |
| 2026-07-22 | 2 | 🚧 **2.2 dbt Silver+Gold** : projet dbt (6 vues `stg_` + 5 tables `fct_`), tests baseline figés attrapant les 4 anomalies faciles (13 PASS / 5 détections), preuve du trou sémantique (`fct_geolocation_by_city` : São Paulo en 3 lignes) | Fan-out ancré sur `geolocation_city` (pas `customer_city`, déjà ASCII) → mart démonstrateur dédié ; les 5 tests rouges = détections, pas des bugs (signal pour Airflow 2.3) |
| 2026-07-24 | 2 | 🚧 **2.3 scaffolding Airflow** : `Dockerfile` (venv isolé du pipeline), `docker-compose.yaml` (LocalExecutor + Postgres), DAG `medallion_pipeline` (8 tâches, `@daily`, `catchup=True`), `archive_baseline.py`, runbook Windows | Airflow tourne **sur le PC de Hoda** (pas de Docker sur le serveur) → modèle « code ici, exécution là-bas » ; tests dbt tolérants par code de sortie (rc=1 = détection = vert) ; `.gitattributes` force LF (CRLF Windows) |
| 2026-07-27 | 2 | ✅ **Phase 2 terminée** : DAG dépausé sur le PC → **92 runs verts** (backfill complet de la fenêtre) ; RAW/STAGING/MARTS peuplés ; `benchmarks/baseline_run.json` archivé (92 entrées, commit `8ffd7a1`) | **La baseline est figée** — plus aucune modification à partir d'ici, c'est le point de comparaison du benchmark (phase 8) |
| 2026-07-28 | 3–5 | 📐 **Révision de design (aucun code)** : l'agent doit être **générique**, Olist n'étant qu'un cas de test. Séance de conception → PROGRESS mis à jour (phases 3, 4, 5, 6, 8, 9) | **5 décisions** : (1) deux cycles — Découverte (contrats) + Surveillance (graphe) ; (2) zéro nom en dur, classification par **rôle de colonne** ; (3) le **contrat versionné** devient le 3ᵉ pilier de détection, construit sur J1→J44 (période propre) ; (4) graphe à **8 nœuds**, `propose` a 3 issues (+ `amend_contract`) ; (5) garde-fou **« ne jamais inventer une valeur »**. Piège identifié : un contrat auto-généré naïvement graverait `sao paulo`/`são paulo` comme valides → la découverte doit *critiquer*, pas seulement enregistrer. ADR 010 à rédiger. |
| 2026-08-02 | — | 🔧 **Incident d'infrastructure (hors projet)** : le dépôt vivait dans `/tmp`, que systemd nettoie tous les 10 jours. 23 objets git manquants, 4 commits sur 9 irrécupérables, ADR 001 et 008 effacés. Réparé par `git fetch --refetch` ; fichiers restaurés. | **Règle adoptée : rien ne dort dans `/tmp` plus d'une session**, on pousse à chaque étape terminée. Ce qui a détruit les fichiers, c'est six jours sans push — pas `/tmp` en soi. Copie de travail sur le PC + GitHub comme référence. |
| 2026-08-03 | 3 | ✅ **Phase 3 terminée** : `AgentState` + les 8 nœuds stubs + `agent/graph.py` (3.1) ; pause/reprise réelle — `interrupt()`, `SqliteSaver`, `scripts/decide.py` (3.2) ; `diagnose` appelle vraiment Groq, sortie forcée en JSON + Pydantic (3.3) ; tests du graphe — 4 chemins, preuve P3, sortie unique, reprise après mort du process (3.4) ; documentation remise en cohérence + ADR 010 (3.0) ; PNG du graphe généré depuis le code. **184 tests verts.** | **Méthode adoptée : la vérification par mutation** — on sabote le code exprès pour vérifier que les tests deviennent rouges ; un test qui ne peut pas échouer ne prouve rien. 9 sabotages joués, tous détectés. **Écart au plan assumé** : mode JSON natif de Groq au lieu de `PydanticOutputParser` (empêche le format invalide au lieu de le rattraper). **Incident** : trois helpers de test appelaient la vraie API sans qu'on le voie (suite passée de 6 à 172 s) → `tests/conftest.py` rend la règle « aucun test n'appelle un LLM » structurelle. **Bug tiers** : `Command(resume=None)` lève dans LangGraph 1.2.9. **Leçon** : les schémas écrits à la main dérivent — celui du graphe est désormais généré par `scripts/export_graph.py`. |
| 2026-08-03 | 4 | ✅ **4.0 Socle générique terminé** : `datasets/olist.yaml` (17 tables, 3 couches) ; `agent/registry.py` (chargement + validation stricte) ; `agent/connectors/` (fabrique + connecteur Snowflake) ; `tests/test_socle.py` — **28 tests, 224 verts au total**. 7 sabotages joués, tous détectés. | **Écart au plan assumé** : pas de classe abstraite (ADR 010, décision 7) — le projet n'a qu'un backend réel, et ce qui protège la propriété « l'agent ne connaît pas sa base » n'est pas l'héritage mais le test `test_aucun_sql_hors_des_connecteurs`, qui relit tout `agent/`. **Deux erreurs du plan corrigées** : Postgres avait été écarté par l'ADR 009, et l'API REST/FastAPI de O1 est une source d'*ingestion*, pas un connecteur d'agent. **Décision 8** : `OPS` (la mémoire de l'agent) n'est pas derrière le connecteur — sinon l'agent se découvrirait lui-même à chaque run, et la mémoire se fragmenterait en autant de bases que de datasets. **Reporté** : connecteur CSV (~1 j) pour démontrer la portabilité de backend au lieu de l'argumenter. |
| 2026-08-04 | 1 · 4 | ✅ **1.5 — fenêtre de référence propre + chargement incrémental** : `data/prepare.py` (3 règles déclarées) ; `semantic_variants` + rampes étalées dans `inject.py` ; `ground_truth.yaml` refondu (section `preparation`, `semantic_drift_j50`, `real_anomalies` supprimée) ; Bronze remis à zéro et rechargé **J1→J43** ; `dbt test` **18 PASS / 0 échec**. **250 tests verts**, 7 sabotages joués, tous détectés. | **Décision** : la référence est propre, les anomalies n'existent que dans les lots qui arrivent après — chaque jour chargé devient un événement. **Rouverture assumée de la phase 1** : dernier moment honnête, `detect` n'étant pas écrit. **Le fil rouge change de nature** : São Paulo passe d'anomalie *réelle et permanente* à anomalie *injectée et datée* (rampe 10/40/80 % sur `customer_city`) — on y gagne une mesure de sensibilité (« à partir de quelle ampleur l'agent voit-il ? ») au lieu d'un oui/non. **Trois erreurs rattrapées par la mesure** : `juiz de fora` figurait dans ma table de variantes sans avoir d'accent (remplacement à vide) ; du **mojibake** (`sa£o paulo`) se cachait sous les accents et mon invariant « cardinalité normalisée == brute » le déclarait propre à tort — remplacé par « aucune valeur restante n'est le doublon caché d'une autre » ; `TRUNCATE` aurait laissé la colonne `AMOUNT` du J45 dans le schéma. **Leçon de méthode (suite du 2026-08-03)** : mon 1ᵉʳ run de mutation était **contaminé** par un test déjà rouge — tous les sabotages passaient pour détectés. Le script vérifie désormais que la suite est verte *avant* de saboter ; en le corrigeant, deux vrais trous sont apparus (rien ne vérifiait que `replay` **appelle** la préparation ; une rampe pouvait déclarer un jour de début ≠ son premier palier). **Dette** : `baseline_run.json` à régénérer au fil du chargement. |
| 2026-08-03 | 4 | 🚧 **4.1.0 + 4.1.1** : [ADR 004](docs/adr/004-langgraph-vs-function-calling.md) rédigé ; `agent/connectors/ops.py` (la mémoire de l'agent) ; `agent/tools/read_schema_history.py` (1ᵉʳ `@tool`) ; `tests/test_tools.py` — **237 tests verts**. 6 sabotages joués, tous détectés. | **Contradiction apparente levée** : le cahier §5.6 demande des tools `@tool`, `DESIGN.md` §2 rejette l'agent ReAct. Les deux parlent de choses différentes — le **décorateur** (un format) et le **tool-calling** (une délégation de flux). Décision : `@tool` oui, `bind_tools` jamais, et un test l'impose. **Bug évité de justesse** : `_SCHEMA_HISTORY` stocke le nom du CSV (`orders`) et la casse du CSV (`order_id`) là où `INFORMATION_SCHEMA` rend `RAW.ORDERS`/`ORDER_ID` — comparés tels quels, 4.3 aurait vu **toutes** les colonnes renommées à chaque run. **Leçon de méthode** : mon 1ᵉʳ sabotage de `bind_tools` plantait à l'import, donc pytest signalait une *erreur* et non un *échec* — le script de mutation ne cherchait que « failed » et concluait « non détecté ». Un sabotage doit être **réaliste**, sinon c'est lui qu'on teste. |
| 2026-08-04 | 4 | 🚧 **4.1.2 ⭐ `top_values`** — le tool sans lequel aucune détection sémantique n'existe : `ConnecteurSnowflake.top_values()` (4ᵉ méthode du contrat), `connectors.fermer()`, `agent/tools/top_values.py` (2ᵉ `@tool`), [ADR 010](docs/adr/010-agent-generique.md) décision 9. **+17 tests, 262 verts.** 12 sabotages joués, tous détectés. | **Décision 9a** : une 4ᵉ méthode plutôt qu'un top-K remonté par `profile` — argument de **coût**, pas de style : `profile` fait *un* passage sur la table, un top-K coûte un `GROUP BY` **par colonne**. Contrepartie assumée : *quelles* colonnes méritent un top-K devient une décision d'appelant, et le vrai critère attend la caractérisation de 4.2. **Décision 9b — R2 change de nature** : jusqu'ici le modèle ne recevait que des chiffres, il n'y avait *rien* à fuiter ; ce tool rend de **vraies valeurs**. R2 tient (une valeur + sa fréquence est une *distribution*, pas une ligne) mais la garantie devient **conditionnelle** — elle ne vaut que sur des colonnes catégorielles. Trois mesures : une seule colonne nue dans la projection (testée sur le SQL émis), `coverage` rendu avec la réponse, et un tool qui **constate** au lieu de se censurer. Corollaire honnête : l'argument « il n'y a rien à fuiter » n'est plus disponible pour défendre Groq contre Cortex. **La symétrie du connecteur, tenue** : colonne absente → `None` (c'est **l'anomalie du J45** — lever tuerait le run sur l'incident qu'il cherche), `batch_column` fausse → exception (erreur de déclaration). **Piège évité** : sans `ORDER BY … , valeur ASC`, deux ex æquo se départagent au hasard et le K-ième rang bascule d'un run à l'autre — la détection deviendrait intermittente (même leçon qu'au repli des variantes en 1.5). **Leçon de méthode, 3ᵉ passage** : mon script de mutation cherchait « error » dans la sortie, or le venv crache un `ModuleNotFoundError: _virtualenv` sur stderr à chaque lancement — *tout* passait pour rouge, suite verte comprise, et le script se serait auto-validé. Il lit désormais le **code de retour**. Après la contamination du 2026-08-04 et le sabotage irréaliste du 2026-08-03 : c'est l'**instrument de mesure** qu'il faut éprouver en premier, à chaque fois. |
