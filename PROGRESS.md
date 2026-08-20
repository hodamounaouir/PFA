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
      *(fait 2026-07-21 : `llama-3.3-70b-versatile` répond via le SDK `groq` ; **remplacé le 2026-08-17
      par `openai/gpt-oss-120b`** — Groq a décommissionné toute la famille Llama, cf. journal de bord)*
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
      `llama-3.3-70b-versatile` — **`openai/gpt-oss-120b` depuis le 2026-08-17** —, `temperature=0`.)*
      ⭐ **La règle R1 s'est payée d'elle-même** : le fournisseur ayant supprimé le modèle, la migration
      a coûté **une ligne**, parce qu'un seul fichier nomme le modèle. Une frontière réseau unique n'est
      pas qu'une propriété d'audit, c'est aussi ce qui rend un fournisseur remplaçable.
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
- [x] **4.1.3** Statistiques robustes : **médiane + MAD**, pas moyenne + écart-type *(sinon l'anomalie
      du J60 entre dans l'historique et fait paraître la récidive du J85 moins grave)*. ⚠️ Sur Bronze
      tout est VARCHAR : `AVG` échouerait — `TRY_CAST`, ou stats numériques réservées à Silver/Gold.
  - [x] **Portée tranchée avant d'écrire** : 4.1.3 mesure la médiane des **valeurs d'une colonne dans
        un lot**. La médiane d'une **métrique à travers les jours** (le taux de nulls sur 30 jours) est
        une *comparaison*, elle a besoin de `OPS._PROFILES` qui n'existe qu'en 4.3 — même outil
        statistique, deux séries, et c'est `detect` qui portera la seconde. Sans ce partage, 4.1.3 se
        serait codée contre une table absente.
  - [x] **Le contrat se lit en deux familles** ([ADR 010](docs/adr/010-agent-generique.md), décision
        10a) : méthodes *de table* (un balayage) et méthodes *de colonne* (une requête par colonne,
        donc à la demande). Généralise la décision 9a et répond d'avance à « jusqu'où le contrat
        grossit-il ? » — 4.1.4 y ajoutera la fraîcheur.
  - [x] **La mesure constate, elle ne se corrige pas** (décision 10b) : un MAD nul est rendu tel quel.
        Le plancher qui évitera la division par zéro est un réglage de **détection**, il appartient à
        4.3. *Une mesure qui se corrige elle-même ment sur ce qu'elle a vu.*
  - [x] ⚠️ **Piège Snowflake** : `TRY_CAST` **n'accepte qu'une source texte** — l'appliquer à une
        colonne déjà `NUMBER` lève. Le type est lu dans `INFORMATION_SCHEMA` (qu'on interroge déjà pour
        résoudre la casse) et le cast n'est posé que sur du texte.
  - [x] ⭐ **`numeric_rate`, une mesure non prévue au plan** : compter ce que `TRY_CAST` n'a pas su lire
        donne la part des valeurs renseignées qui sont encore des nombres. 1,0 = colonne saine ; 0,7 =
        un tiers du format a cassé. Une **dérive de format**, obtenue pour rien.
  - [x] `min`/`max` **numériques**, là où ceux de `profile` sont lexicographiques sur Bronze
        (`"8000" < "90"`) — c'est ce qui rend enfin exploitable le cas « une ligne à 8000 dans une
        colonne à [1–100] ».
  - [x] `agent/tools/_connecteur.py` : le socle commun des tools qui lisent la base, écrit à la
        **deuxième** occurrence et non à la première. Ce qui compte n'est pas les douze lignes
        économisées, c'est que le message d'erreur d'une table non déclarée et la garantie de fermeture
        existent à un seul endroit — donc qu'un troisième tool ne puisse pas les oublier à moitié.
- [x] **4.1.4** Fraîcheur *(2026-08-17)* — `agent/freshness.py`
  - [x] ⭐ **Aucune requête.** Le critère de 4.1.5 avait déjà tranché qu'une colonne `temporal` ne
        reçoit pas de mesure dédiée parce que ses `min`/`max` **sont** la fraîcheur : il ne manquait
        que l'interprétation. Elle est donc gratuite là où `top_values` et `robust_stats` coûtent une
        requête par colonne — et il y a **40 colonnes temporelles sur 128** dans le dataset.
  - [x] ⭐ **La référence est le lot, pas l'horloge.** Comparer à `now()` n'aurait aucun sens sur un
        dataset rejoué de 2018 : tout paraîtrait vieux de sept ans. La question utile est *ce lot
        contient-il ce qu'il prétend contenir ?* Effet secondaire décisif : la mesure devient
        **reproductible** — rejouer le J45 dans deux ans rendra le même retard, ce qu'une fraîcheur
        mesurée à l'horloge aurait rendu instable au benchmark.
  - [x] Trois faits tirés de deux bornes : `retard_jours`, `amplitude_jours` (un lot journalier qui
        couvre 91 jours est un rechargement, pas un lot), `dates_futures`.
  - [x] **`dates_futures` est un fait, pas un décompte** : `max` dit qu'il en existe, pas combien. Les
        compter demanderait la requête que l'étape existe pour éviter — et « il y en a » suffit à
        alerter tout en restant exact.
  - [x] ⭐ **Détectable sans détecteur** : les trois mesures rejoignent `METRIQUES_COLONNE`, donc
        `OPS._PROFILES`, donc la famille statistique. Un `dates_futures` constant à 0 qui passe à 1
        déclenche une `rupture_de_constante` sans qu'une ligne de détection ait été écrite pour lui.
  - [x] Les **trous** restent hors de portée d'un tool : ils ne se voient pas dans un lot mais d'un lot
        à l'autre — c'est une comparaison à un historique, donc le travail de la famille statistique.
- [x] **4.1.5** `profile_table` : l'assembleur — agrégats du connecteur + top-K + stats robustes, en
      une seule fiche. C'est le point où 4.1 devient consommable par 4.3.
      *(⚠️ min/max sont indispensables : une seule ligne aberrante — 8000 dans une colonne à [1–100] —
      ne déplace presque pas la moyenne mais fait exploser le max. Déjà livrés en 4.0.)*
  - [x] **L'assembleur porte le critère** ([ADR 010](docs/adr/010-agent-generique.md), décision 11,
        tranchée par le porteur du projet) : `profile_table("olist", "RAW.ORDERS", "2018-04-29")` et
        rien d'autre. Écarté : faire lister les colonnes par l'appelant — honnête, mais le problème
        remontait d'un cran et 4.3 aurait inventé sa règle dans un nœud, sans test dédié. La règle vit
        dans **une seule fonction**, `_mesure_pour()`, que 4.2 remplacera.
  - [x] ⭐ **Le critère ne lit aucun nom de type SQL.** La voie évidente (`DATA_TYPE` depuis
        `INFORMATION_SCHEMA`) est écartée pour une raison fatale : **en Bronze tout est VARCHAR**, donc
        un critère fondé sur le type déclaré n'y trouverait *aucune* colonne numérique — aucune
        statistique robuste sur la couche où les anomalies sont injectées. 4.1.3 aurait été livrée
        inutilisable là où elle sert le plus. Le critère ne lit que des **faits mesurés** : `min`/`max`
        lisibles comme des nombres → `robust_stats` ; cardinalité ≤ 50 % des lignes → `top_values`.
        Bénéfice second : aucun dialecte de base n'entre dans une couche qui doit l'ignorer (décision 2).
  - [x] ⚠️ **Le piège silencieux de l'assemblage** : `profile` rend `max="90"` (lexicographique sur
        Bronze), `robust_stats` rend `max=8000.0` (numérique). Fusionner sous la même clé ferait
        croire à une borne qui n'a pas été mesurée ainsi, et la comparaison de 4.3 porterait sur deux
        grandeurs différentes selon la couche. → `numeric_min`/`numeric_max` vivent **à côté**.
  - [x] `profile_table` appelle les **méthodes du connecteur**, jamais les autres tools : passer par
        `top_values.invoke()` rouvrirait une connexion Snowflake par colonne (1–2 s chacune). Testé.
  - [x] **Imprécisions assumées, listées** : un code postal est « lisible comme un nombre » et recevra
        une médiane vide de sens ; une colonne de dates peu variée peut recevoir un top-K. C'est la
        distinction *identifiant* vs *numérique* vs *temporel* que le classement par rôle de 4.2
        tranchera. Deux valeurs ne font pas une preuve — mais `numeric_rate` mesure ensuite à quel
        point la supposition était juste : on suppose à bas prix, on mesure honnêtement.
  - [ ] ⏭️ **À surveiller** : chaque méthode de colonne résout son propre schéma (elle doit rester
        appelable seule), donc profiler une table coûte une requête `INFORMATION_SCHEMA` par colonne
        mesurée. Remède connu et local — mémoriser le schéma sur l'instance de connecteur — **non
        implémenté** : mesurer sur le vrai Snowflake avant d'optimiser vaut mieux que deviner, et 4.5
        est le moment où le coût réel apparaîtra.
- [x] **4.1.6** `run_sql` : **lecture seule** *(2026-08-17)* — le garde-fou vit dans
      `agent/sql_guard.py`, celui-là même que la règle R4 d'`apply` réutilisera en phase 5. *Une règle
      écrite deux fois finit par diverger, et le jour où elle diverge c'est la version la plus laxiste
      qui gagne.*
  - [x] ⭐ **Une liste blanche, et pas seulement la liste noire prévue au plan.** Une liste noire ne
        protège que de ce qu'on a pensé à y mettre : `COPY INTO`, `PUT`, `CALL` écrivent sans porter
        aucun des verbes évidents, et une version future du moteur en ajoutera d'autres. La liste
        blanche inverse la charge — ce qui n'est pas explicitement autorisé est refusé, **y compris ce
        qui n'existe pas encore**. La liste noire est gardée **en plus**, pour ce qui se cache après un
        verbe autorisé.
  - [x] **Troisième barrière, celle qu'on oublie** : une seule instruction. `SELECT 1; DROP TABLE x`
        franchit les deux premières sans peine.
  - [x] ⭐ **On valide, PUIS on se connecte.** Contrôler après avoir ouvert la session laisserait une
        trace de connexion pour une requête qu'on n'avait pas le droit de poser — et le jour où le
        contrôle a un trou, la requête serait déjà partie. Un test l'impose.
  - [x] ⚠️ **Le seul endroit du projet qui rend des lignes brutes**, par nécessité : investiguer, c'est
        regarder des lignes. D'où la règle absolue — *le résultat de `run_sql` n'entre jamais dans le
        contexte du LLM*. Il va à l'écran d'un humain. Le journal, lui, trace la requête et le volume,
        **jamais les valeurs** : sinon il deviendrait une copie de la base par accumulation.
  - [x] **Qui l'appelle** : pas le modèle (ADR 004 exclut `bind_tools`), mais un humain — terminal
        aujourd'hui, écran de décision en phase 6. C'est ce qui rend la journalisation utile : elle
        trace ce qu'une *personne* a regardé pour trancher.
- [x] **4.1.7** DDL `OPS.INCIDENTS` + `write_log` — ~~le DDL est monté depuis 4.4~~ *(livré avec la
      phase 4.4 le 2026-08-17 : le DDL et le tool sont arrivés ensemble, puisque `write_log` se serait
      codé à l'aveugle sans la table)*
- [x] **4.1.8** `generate_dq_rule` : produit un dbt test YAML rattaché à une dimension DAMA
      *(terminé le 2026-08-17)* — c'est le tool qui fait que l'agent **durcit le pipeline** au lieu de
      seulement réparer la donnée : une anomalie attrapée une fois devient une règle vérifiée à chaque
      run, sans LLM et sans humain.
  - [x] ⭐ **Aucun SQL n'entre dans `agent/`, et ce n'était pas gagné.** La collision sémantique est la
        seule règle du projet qu'aucun test dbt standard ne sait exprimer — elle demande une requête.
        Plutôt que de l'écrire dans le tool (ce que le garde-fou du socle aurait refusé, à raison),
        elle devient un **test générique maison** écrit une fois à la main dans
        `dbt/tests/generic/no_semantic_collisions.sql`, et l'agent n'émet que le YAML qui l'appelle.
        C'est la bonne frontière et non un contournement : le SQL qu'exécute **dbt** vit dans le
        projet dbt, celui qu'exécute **l'agent** derrière le connecteur.
  - [x] **Vérifié sur la vraie base, dans les deux sens** : le test attrape la grappe
        `sao paulo`/`são paulo`/`SAO  PAULO` sur des données sales, rend **0 grappe** sur le million de
        lignes de `STG_GEOLOCATION` (fenêtre propre), et ne fusionne **pas** `arco verde` /
        `arcoverde` — la décision 13c tient jusque dans le SQL.
  - [x] ⭐ **L'agent propose la règle, il ne l'installe pas.** La sortie est un *fragment* à relire.
        Écrire directement dans `_staging.yml` reviendrait à laisser l'agent modifier les tests qui
        décident si le pipeline est vert — c'est-à-dire changer la définition de « ça marche ». Même
        raisonnement qu'à la **décision 14** pour le registre.
  - [x] ⚠️ **Conséquence pour le benchmark, à ne pas oublier en 4.5/8** : les règles réintégrées
        portent `tags: [generated]`, et le bras « baseline » devra s'exécuter avec
        `--exclude tag:generated`. Sans ça la baseline attraperait des anomalies **grâce à l'agent**,
        et la comparaison mesurerait l'agent contre lui-même.
  - [x] **La liste d'`accepted_values` vient du contrat, jamais des valeurs observées** : l'écart porte
        les intruses dans `observe` et la liste signée dans `reference`. Générer depuis `observe`
        graverait l'anomalie comme règle — le pipeline validerait ce qu'il aurait dû refuser.
  - [x] **Bronze est une *source* dbt, pas un modèle** : le YAML n'a pas la même forme (`sources:`), et
        se tromper produit un fragment que dbt refuse d'analyser.
  - [x] **Ce qui ne se traduit en aucun test est rendu `None`** : une table absente, une dérive de
        volume. dbt ne sait pas dire « il y a moins de lignes que d'habitude » — c'est une comparaison
        à un historique, pas une propriété du lot. Générer une règle bancale produirait un test qui
        échoue sans rien dire, et on apprendrait à l'ignorer.

**✅ Le §5.6 du cahier est complet** *(2026-08-17)* : `profile_table` · `read_schema_history` ·
`top_values` · `robust_stats` · `run_sql` · `generate_dq_rule` · `read_past_incidents` · `write_log`.
Seul `lineage_impact` manque, et il appartient à la phase 7.

**Chemin critique vers la détection** : 4.1.1 ✅ · 4.1.2 ✅ · 4.1.3 ✅ · 4.1.5 ✅ — **franchi le
2026-08-04**. `detect` (4.3) a désormais de quoi attraper les 4 anomalies injectées **et** le cas
São Paulo. `run_sql`, `write_log` et `generate_dq_rule` ne bloquent rien.

### 4.2 Cycle Découverte : caractérisation & contrats ⬅️ *nouveau*
- [x] **4.2.1** `agent/characterize/` : **classer chaque colonne par rôle inféré** — c'est le moteur de
      généricité *(terminé le 2026-08-04, [ADR 010](docs/adr/010-agent-generique.md) décision 12)*
  - [x] **Le rôle se déduit des faits, jamais du type déclaré** (décision 12a) — même principe qu'en
        4.1.5, et l'argument est ici *a fortiori* : en Bronze tout est VARCHAR, donc un classement
        fondé sur `DATA_TYPE` y verrait six colonnes de texte libre et rien d'autre. Cinq faits
        suffisent, tous rendus par `profile` : lignes, cardinalité, nulls, `min`, `max`. Effet
        secondaire décisif : **classer ne coûte aucune requête**, alors que c'est le classement qui
        engage les requêtes coûteuses.
  - [x] ⭐ **L'ordre des tests est la décision** (décision 12b). Une colonne satisfait souvent
        plusieurs signatures : `order_purchase_timestamp` est unique à 99 % et sans nul, donc
        *identifiant* au sens strict. Le classer ainsi ferait perdre fraîcheur, dates futures, trous
        et monotonie — pour ne gagner qu'un contrôle d'unicité sur une colonne qui n'identifie rien.
        Règle : **le rôle le plus exigeant gagne**. D'où `temporal` → `identifier` → `numeric` →
        `categorical` → `free_text`, et trois tests qui l'imposent nommément.
  - [x] **Une clé presque unique reste un identifiant** (décision 12c) : `RATIO_UNICITE_MIN = 0.99`,
        pas 1,0. À 1,0, une clé primaire portant trois doublons deviendrait du texte libre et
        **perdrait son contrôle d'unicité** — au moment précis où elle le viole.
  - [x] **Branché dans `profile_table`** : le critère provisoire disparaît, remplacé par
        `MESURE_PAR_ROLE`. Le rôle est **rangé dans la fiche**, pas seulement consommé — c'est lui que
        le contrat et `detect` reliront.
  - [x] ⭐ **Décision 12d, ajoutée le 2026-08-17 après la 1ʳᵉ découverte réelle** : *une grandeur
        continue n'identifie rien*. `REVENUE` et `AVG_ORDER_VALUE` (43 jours de mart) étaient classés
        **identifiants** — sur 43 lignes un montant flottant ne se répète jamais et n'est jamais nul,
        donc il satisfait *exactement* la signature d'une clé. Les conditions 12b/12c étaient pourtant
        écrites contre ce cas : elles ne suffisaient pas. Coût de l'erreur : la colonne recevait
        `unique` et **perdait ses bornes** — l'agent aurait vérifié l'unicité du chiffre d'affaires au
        lieu de ses aberrations, sur le mart qu'un jury regarde en premier. Signal retenu : **la partie
        fractionnaire**, pas un plancher de lignes — « presque unique » ne veut rien dire sur un petit
        lot, « porte des décimales » veut dire la même chose partout, et un plancher aurait retiré
        `unique` aux petites tables de référence au moment précis où elles le violent (12c).
        **Limite résiduelle dite honnêtement** : un comptage *entier* qui se trouverait tout distinct
        reste indiscernable d'une clé — le fait mesuré manque, c'est la validation humaine qui tranche.
  - [x] **Régression corrigée** : une colonne de dates peu variée ne reçoit plus de top-K.
  - [x] `test_aucun_nom_de_colonne_n_intervient` : le garde-fou de généricité du module. S'il rougit,
        c'est qu'une heuristique de nommage s'est glissée dans le classement.

  | Rôle | Reconnu à | Contrôles qui en découlent |
  |---|---|---|
  | identifiant | cardinalité ≈ nb lignes, non-null, **et pas de décimale** | unicité, nulls, format |
  | clé étrangère | valeurs ⊂ identifiants d'une autre table | intégrité référentielle, orphelins |
  | catégoriel | texte, cardinalité faible | valeurs nouvelles/disparues, **collisions sémantiques**, distribution |
  | numérique | type numérique, cardinalité élevée | bornes, moyenne/σ, outliers, négatifs/zéros |
  | temporel | type date/timestamp | fraîcheur, dates futures, trous, monotonie |
  | texte libre | texte, cardinalité élevée | nulls + longueurs **seulement** (surtout pas de valeurs acceptées) |

- [x] **4.2.5** `scripts/discover.py <dataset>` : introspection → profilage de la **fenêtre de
      référence** → caractérisation → proposition de contrat → validation humaine
      *(terminé le 2026-08-04)*
  - [x] ⚠️ **Écart au plan assumé : la pause est un fichier, pas un `interrupt()`.** Un checkpoint
        garderait une **copie** du contrat pendant que l'humain édite le **fichier** — à la reprise, le
        graphe réécrirait la sienne et **effacerait les corrections**. Silencieux, et il détruit
        exactement ce que l'étape sert à produire. Le fichier est donc la seule source de vérité ; la
        pause est sa présence sur disque en `status: proposed`. Elle survit à un redémarrage mieux
        qu'un checkpoint, se relit en pull request et se compare d'une version à l'autre. **La
        propriété qui comptait est conservée** — `charger()` ne rend jamais un contrat non validé.
  - [x] ⭐ **La découverte profile la table ENTIÈRE, à rebours de la surveillance.** Celle-ci filtre
        par lot (sinon 30 % de nulls sur un jour ne pèsent plus que 0,3 % sur 92) ; celle-là cherche
        ce qui est *normal*, et un contrat bâti sur une seule journée serait absurdement étroit — les
        valeurs légitimes absentes ce jour-là deviendraient des violations dès le lendemain. **La
        dilution est l'ennemi de l'une et la condition de l'autre.**
  - [x] **Valider exige de signer** (`--by`) : un contrat sans signataire ne prouve rien six mois plus
        tard. Même traçabilité que `decided_by` dans le cycle de surveillance.
  - [x] **Valider un contrat critiqué exige `--accept-warnings`** : signer une collision sémantique
        est une décision, pas une formalité. Sans ce garde-fou, le cas d'école se validerait d'un
        `--approve` distrait et la découverte aurait critiqué pour rien.
  - [x] **Une table qui échoue n'arrête pas les autres** : découvrir 17 tables ne doit pas mourir sur
        la troisième. L'échec est **rapporté avec sa cause**, pas avalé.
- [x] **4.2.2** `agent/contracts/proposer.py` : d'un profil à un contrat proposé — **avec la critique
      intégrée** *(terminé le 2026-08-04, [ADR 010](docs/adr/010-agent-generique.md) décision 13)*
  - [x] **Écart au plan assumé** : 4.2.2 (proposer) et 4.2.3 (critiquer) livrées **ensemble**. Livrer
        la proposition seule aurait produit un générateur qui grave `são paulo` comme valeur légitime —
        un artefact que la décision 3 interdit, et qui risquait d'être utilisé entre deux commits.
        *Une étape intermédiaire connue pour être fausse n'est pas une étape.*
  - [x] ⭐ **La découverte retire la clause, elle ne l'assortit pas d'un avertissement** (décision 13a).
        *Un avertissement se survole, une clause absente ne peut pas être approuvée par distraction.*
        Trois refus : collision sémantique observée, **top-K tronqué**, colonne de texte libre.
  - [x] ⚠️ **Le refus le plus sournois n'était pas prévu** : `top_values` rend les K valeurs les plus
        *fréquentes*. Si elles couvrent 60 % des lignes, les 40 % restants sont légitimes et absents de
        la liste — un contrat construit là-dessus **crierait dès le lendemain sur des données saines**,
        et on apprendrait à ignorer ses alertes. C'est `coverage` (introduit en 4.1.2 pour une raison
        de confidentialité) qui rend ce refus possible.
  - [x] ⭐ **Corrigé le 2026-08-17 — le refus doit porter sur une preuve *absente*, pas sur une preuve
        *non demandée*.** La 1ʳᵉ découverte réelle a refusé `accepted_values` à `CUSTOMER_STATE` (99 %
        de couverture, **27** états face à `TOP_K_DEFAUT = 20`) et à `PRODUCT_CATEGORY_NAME` (86 %, 73
        catégories). Le raisonnement de 13a était juste, mais il s'appliquait à un manque que
        l'assembleur avait lui-même créé. Nouveau seuil `CARDINALITE_ENUMERABLE_MAX = 100` et
        `_k_pour()` dans `profile_table` : **sous le seuil on demande `k = distinct`**, la couverture
        atteint 1, la clause devient démontrable. `distinct` étant déjà dans le profil, décider ne coûte
        **aucune requête** et mesurer n'élargit qu'un `LIMIT` sur un `GROUP BY` déjà payé.
        Effet : avertissements **16 → 8**, `accepted_values` **10 → 18**. Les 8 avertissements restants
        sont exactement les vraies longues traînes (`CUSTOMER_CITY` 43 %, `GEOLOCATION_CITY` 39 %,
        `PRODUCT_ID` 7 %, `SELLER_ID` 24 %) — celles-là ne s'énumèrent pas, et le refus y est fondé.
        **R2 n'y perd rien** : une colonne de moins de cent modalités est catégorielle par n'importe
        quelle mesure, soit le régime où « une distribution, pas une ligne » est le plus solide.
  - [x] **Symétrique** (décision 13b) : `unique` est proposé sur un identifiant qui porte déjà des
        doublons, `no_semantic_collisions` sur une colonne qui en porte — avec un avertissement chiffré.
        Un contrat dit ce qui *devrait* être vrai ; escamoter la clause répondrait à la place de
        l'humain à la seule question qui compte : **nettoie-t-on, ou accepte-t-on ?**
  - [x] **Règle dégagée** : *ce qui relève du constat est proposé, y compris quand il dérange ; ce qui
        relève de la preuve est retiré quand la preuve manque.*
  - [x] `agent/characterize/collisions.py` : le repli (casse/accents/espaces multiples), **sans
        importer `data/prepare.py`** — `agent/` ne doit rien devoir à l'outillage du benchmark.
  - [x] **Le repli ne supprime pas les espaces** (décision 13c) : `sãopaulo` y échappe, et c'est
        assumé — les supprimer fusionnerait `arco verde` et `arcoverde`, **deux communes distinctes**.
        Sans coût sur le corrigé : les 18 variantes du J50 sont toutes accentuelles.
  - [x] `numeric_min`/`numeric_max` gravés, **jamais** `min`/`max` (lexicographiques sur Bronze).
  - [ ] ⏭️ **À surveiller** : `not_null` est proposé sur toute colonne sans nul observé — un saut
        assumé (c'est lui qui attrapera le J60 dès le 1ᵉʳ jour), mais la 1ʳᵉ clause à produire des faux
        positifs si la validation humaine devenait un tampon.
- [x] **4.2.4** `contracts/<dataset>/<TABLE>.v<N>.yaml` **versionnés dans git** ;
      `agent/contracts/loader.py` les écrit et les recharge *(terminé le 2026-08-04)*
  - [x] ⭐ **`charger()` ne rend que du validé** — garantie structurelle du même rang que R3. Un
        contrat `proposed` décrit ce que la machine a *observé* ; s'il pouvait être appliqué, la
        validation humaine deviendrait décorative et le système se donnerait à lui-même la permission
        qu'il est censé demander.
  - [x] **Mais un contrat en attente reste visible** (`lister()`) : « aucun contrat » et « un contrat
        qui attend une signature » sont deux situations différentes, et les confondre serait un état
        silencieux.
  - [x] **Écrire n'écrase jamais une décision** : rejouer une découverte sur une proposition est
        normal (le fichier est remplacé) ; le faire sur un contrat **validé** est refusé — ça
        détruirait le travail d'un humain. L'amendement passe par une version suivante (phase 5).
  - [x] **Le nom du fichier n'est pas l'identité** : `table` et `version` vivent dans le *contenu*, et
        le chargeur vérifie la correspondance. Sans ça, un `git mv` malheureux ferait appliquer les
        clauses de `RAW.ORDERS` à `RAW.CUSTOMERS`, silencieusement.
  - [x] ⚠️ **`allow_unicode=True`** : sans lui, `são paulo` s'écrit `s\xE3o paulo` dans le fichier. Le
        contrat deviendrait illisible **précisément** sur le cas que le projet existe pour montrer — et
        un humain ne peut pas valider ce qu'il ne peut pas lire.
  - [x] **Lecture et écriture dans le même module** : le format n'existe qu'à un endroit, donc il ne
        peut pas se désynchroniser entre celui qui écrit et celui qui relit (même leçon que le schéma
        du graphe, dessiné à la main puis dérivé, aujourd'hui généré depuis le code).

- [x] **Documentation des contrats** *(2026-08-17)* : [`docs/CONTRATS.md`](docs/CONTRATS.md) — une fiche
      par table (rôle, volume de référence, clés, clauses, avertissements conservés), **générée** par
      `scripts/export_contracts_doc.py`. Même raison qu'au diagramme du graphe en 3.1, et plus forte
      encore : un contrat n'est pas stable — les 17 fiches sont en `proposed`, elles passeront
      `approved` à la signature puis `v2` au premier amendement. Une fiche recopiée à la main serait
      fausse **dès la première signature**, et une documentation qui se trompe sur le *statut* d'un
      contrat affirme qu'une règle s'applique alors qu'elle attend une décision humaine.
      Le générateur ne connaît pas Olist : couche et grain se déduisent du registre et des rôles.
      **À relancer après toute découverte, signature ou amendement.**

### 4.3 Profile & Detect réels
- [x] **`profile` réel** *(2026-08-17)* : appelle `profile_table`, charge l'historique dans l'état et
      **persiste le profil du jour** dans `OPS._PROFILES`.
  - [x] ⭐ **L'exclusion du lot courant est portée par le SQL, pas par l'ordre des appels.** Le plan
        disait « lire l'historique avant d'y écrire » : l'ordre suffit au premier passage et **casse au
        rejeu** — un lot déjà profilé hier serait relu aujourd'hui comme s'il était du passé, et sa
        médiane se rapprocherait de lui jusqu'à ce que l'anomalie devienne la norme. Airflow rejoue une
        tâche en cas d'échec, donc le cas n'est pas théorique. `lire_historique(avant=lot)` tient quel
        que soit l'appelant, y compris celui auquel on n'a pas pensé.
  - [x] ⚠️ **La clé de l'historique est le lot du *run*, pas `profil["batch_id"]`.** Un mart Gold n'a
        pas de colonne de lot : ce champ y vaut toujours `None`, si bien qu'en le prenant pour clé
        chaque run aurait écrasé le précédent — **Gold, la couche où les chiffres faux se voient,
        aurait été la seule sans historique** donc sans dérive statistique possible.
  - [x] `_PROFILES` en **format long** (dataset, table, lot, colonne, métrique, valeur) : la
        comparaison devient un `GROUP BY` avec `MEDIAN()` — donc du SQL qui reste dans le connecteur —
        et ajouter une métrique ne demande aucun DDL. `column_name` vaut `NULL` pour une métrique de
        table plutôt qu'un nom sentinelle, qui entrerait en collision le jour où une vraie colonne le
        porterait. **Idempotent** (`DELETE` puis `INSERT`, comme l'ingestion en 2.1).
  - [x] Ce qui est **délibérément absent** de l'historique : `top` (une liste, pas une mesure), `role`,
        `type`, et les `min`/`max` **lexicographiques** — ces derniers parce qu'ils ne répondent pas à
        la même question que `numeric_min`/`numeric_max` (piège de 4.1.5). Chaque question a déjà son
        lieu : la dérive de schéma dans `_SCHEMA_HISTORY`, les valeurs du jour dans le profil du jour.
  - [x] **`detect` ne fera aucune entrée-sortie** : c'est `profile` qui lui apporte la référence dans
        `state["profile_history"]`. Ses cinq familles doivent être déterministes et reproductibles au
        benchmark (phase 8), donc éprouvables sur de simples dictionnaires — un détecteur qui ouvre une
        connexion est un détecteur qu'on ne peut pas rejouer à l'identique.
  - [x] **Une table absente ne fait pas lever** : profil vide et journal explicite, c'est la famille
        *inventaire* qui la constatera. Même symétrie que le connecteur en 4.0.
    - [x] **La table `_PROFILES` est créée paresseusement par qui s'en sert**, même convention
        qu'`ingestion/load.py` pour `_SCHEMA_HISTORY` : rejouer l'infrastructure sur un second trial ne
        demande aucune étape de plus. Testé sur les deux chemins après qu'un sabotage soit passé.
- [x] `agent/config.py` : `FENETRE_HISTORIQUE_LOTS = 30`, `HISTORIQUE_MIN_LOTS = 15` — des **lots** et
        non des jours calendaires, sinon une interruption du pipeline raccourcirait l'historique en
        silence.
- [x] ⚠️ **Garde-fou de test structurel, jumeau de celui du LLM** : brancher le `profile` réel a fait
      passer la suite de 16 s à **5 minutes avec 82 échecs** — elle ne testait plus l'agent, elle
      testait le réseau. C'est l'incident de la phase 3.3 rejoué sur une autre couture. `conftest.py`
      installe désormais un double par défaut (`PROFIL_FACTICE`, `MEMOIRE_FACTICE`) **et** une barrière
      qui fait échouer bruyamment toute ouverture de connexion Snowflake. *Une règle qu'on peut oublier
      n'est pas une règle — deux fois de suite.*
- [x] **`detect` — les cinq familles** *(2026-08-17)*, toutes déterministes, toutes génériques,
      toutes **sans entrée-sortie** : `agent/detect/`, un module par famille, orchestrées par le nœud :
  - [x] **inventaire** ⬅️ *ajouté le 2026-08-03* : la liste des tables **déclarées** dans
        `datasets/<dataset>.yaml` confrontée à celles **réellement présentes** (`list_tables()`).
        C'est la seule famille qui s'exerce **avant** de profiler quoi que ce soit — et la seule qui
        puisse constater qu'il n'y a rien à profiler. Trois écarts à produire :
    - [x] **table déclarée absente** — l'incident le plus grave qui puisse arriver. Sans cette famille,
          le connecteur lèverait et le run planterait : personne ne saurait *pourquoi*, et l'anomalie
          serait masquée par un bug apparent. L'agent doit la **constater**, pas trébucher dessus.
    - [x] **table nouvelle non déclarée** — elle n'est pas surveillée, et personne ne le sait
    - [x] **hypothèse de renommage** : une table déclarée a disparu **et** une table nouvelle porte un
          schéma identique. `detect` n'énonce que le fait (« A absente, B nouvelle, schémas
          identiques ») ; c'est `diagnose` qui formule « probablement un renommage », et l'humain qui
          tranche. Répartition habituelle : le code constate, le LLM suppose, l'humain décide.
  - [x] dérive de **schéma** : diff du schéma du jour vs `_SCHEMA_HISTORY`, **contrat en repli**
        (l'historique ne couvre que Bronze) — et `lire_schema(avant=lot)` ajouté, sans quoi la
        comparaison porterait sur le schéma d'aujourd'hui, déjà écrit par l'ingestion
  - [x] **violation de contrat** ⬅️ *nouveau* : confrontation aux clauses du YAML (bornes, unicité,
        nulls interdits, valeurs acceptées, cohérence normalisée)
  - [x] dérive **statistique** : écart du profil du jour vs les N derniers lots (`_PROFILES`)
  - [x] **collisions sémantiques** : normalisation (casse/accents/espaces) des top-K valeurs de
        **toute colonne classée catégorielle** → clusters de collision (attrape `sao paulo`/`são paulo`)
  - [x] intégration des **échecs dbt test** du run comme anomalies déjà confirmées *(fait en 4.5)* —
        `agent/dbt_results.py` lit `run_results.json` **et** `manifest.json`, `agent/detect/dbt.py`
        traduit. ⚠️ **Ce n'est pas une famille de détection** : elle ne constate rien, elle porte le
        verdict d'un outil qui a déjà tranché dans la forme commune — ce qui lui donne accès au
        diagnostic, à la signature, à la mémoire et au journal. C'est aussi ce qui **referme la boucle
        de 4.1.8** : l'agent génère des règles dbt, dbt les exécute, et leurs échecs reviennent à
        l'agent. Le manifest est indispensable — découper `not_null_stg_customers_customer_id` serait
        ambigu dès qu'un modèle s'appellerait `customers_customer`.
- [x] ⭐ **Aucune famille ne fait d'entrée-sortie**, et c'est structurel. Deux raisons : le benchmark
      (phase 8) doit rejouer la détection à l'identique ; et une famille qui interroge la base *pendant
      qu'elle raisonne* compare des choses mesurées à des instants différents — l'écart n'aurait alors
      de sens ni pour le lot, ni pour aujourd'hui. C'est `profile` qui rassemble les cinq références.
- [x] ⭐ **`no_semantic_collisions` n'est PAS vérifié par la famille contrat.** Un même fait produirait
      deux écarts — donc deux propositions pour une seule anomalie, et un taux d'approbation faussé au
      benchmark. Surtout : São Paulo doit être vu sur une table **sans contrat signé**, sinon la
      détection du fil rouge dépendrait d'une signature humaine.
- [x] **Une famille qui lève n'emporte pas les autres** : cinq détecteurs indépendants, l'échec est
      journalisé (`familles_en_echec`) et non avalé. *Un agent silencieusement aveugle est pire qu'un
      agent partiellement aveugle.*
- [x] **L'inventaire ne relève les schémas que des tables présentes et non déclarées** : les seules
      qu'on ne connaît pas, donc les seules qui puissent étayer un renommage. Dans le cas normal il
      n'y en a aucune et l'inventaire ne coûte qu'une requête — contre une par table à chaque run.
- [x] ✅ **Question tranchée le 2026-08-17** ([ADR 010](docs/adr/010-agent-generique.md), décision 14) :
      **le registre n'est pas amendable par l'agent.** Ni élargissement d'`amend_contract`, ni 4ᵉ issue
      — **le graphe ne change pas** (8 nœuds, 3 issues). Un renommage se signale toujours, mais il
      recouvre deux situations que la machine ne peut pas distinguer et que l'humain tranche d'un
      regard :
  - [ ] **vrai renommage métier** → `rejected` : l'agent n'écrit rien, l'humain met
        `datasets/<dataset>.yaml` à jour lui-même, en git.
  - [ ] **renommage accidentel** → `approved` : `apply` **restaure le nom d'origine** en base.
  - [ ] ⭐ **P6 tient par construction** : restaurer un nom n'est pas *inventer* une valeur — le nom
        d'origine est écrit dans le registre, l'agent le **lit**. C'est l'inverse du cas « 8000 dans
        une colonne à [1–100] », où aucune source ne dit ce que la valeur aurait dû être.
  - [ ] **Le fondement** : le contrat est *descriptif devenu normatif* (la machine propose, l'humain
        signe), le registre est *normatif d'emblée* — il déclare un **périmètre**. Un agent qui
        réécrit son propre périmètre de surveillance décide de ce qu'il surveille, soit l'autorité
        exacte que le projet lui refuse.
  - [ ] ⚠️ **Deux conséquences à traiter** : (a) `apply` émettra du **DDL** pour la première fois
        (§5.3) ; (b) `rejected` fait taire la signature — si l'humain oublie de corriger le registre,
        l'agent se tait sur une table qu'il ne voit plus, d'où l'écran « signatures en silence » de la
        phase 6.
- [x] **Statistiques robustes** : médiane + MAD plutôt que moyenne + écart-type — sinon l'anomalie du J60
      entre dans l'historique, gonfle σ, et la récidive du J85 paraît *moins* grave (contamination de
      la référence). ⭐ **Écart au plan assumé : aucun plancher sur le MAD.** Les métriques n'ont pas
      la même échelle (`null_rate` dans [0, 1], `row_count` dans [0, 10⁶]) : aucun plancher absolu n'a
      de sens, et un plancher relatif vaudrait zéro précisément quand la médiane vaut zéro — le cas
      visé. Surtout, **un MAD nul n'est pas un problème à corriger, c'est une information** : la
      métrique n'a jamais bougé, donc si elle bouge aujourd'hui aucun score n'est nécessaire pour le
      dire. Ce cas produit un écart `rupture_de_constante`, rapporté par son écart **brut**. Inventer
      une variabilité non observée, c'est ce que la décision 10b interdit déjà à la mesure.
- [x] **Démarrage à froid** : pas de détection statistique avant N lots (`HISTORIQUE_MIN_LOTS = 15`),
      et il se constate **par série** — une colonne apparue il y a trois jours n'a pas d'historique
      même si la table en a trente.
      Chez Olist c'est confortable : 1ʳᵉ injection au J45, donc 44 jours propres pour apprendre.
- [x] Seuils de détection dans `agent/config.py` — ce sont des réglages de **détection**, pas des règles
      de décision (la décision, c'est l'humain)

### 4.4 La table `INCIDENTS` et la mémoire (dans les deux sens)
- [x] DDL `OPS.INCIDENTS` (schéma §5.5 du cahier) — **append-only**, plus une colonne `signatures`
      ⚠️ *ajout au cahier assumé* : les signatures sont dérivables du JSON `anomalies`, mais seulement
      en Python après lecture. Les stocker à part rend possibles deux choses qui ne l'étaient pas —
      retrouver un incident **par signature** en SQL (la mémoire de `diagnose`, O7), et **lister les
      signatures qu'un humain a fait taire**, c'est-à-dire l'écran anti-cécité de la phase 6.
- [x] `log` réel : une ligne par run, **quel que soit le chemin** (y compris « rien d'anormal » et
      « refusé » — un faux positif est une **donnée de mesure** pour la précision en phase 8)
- [x] **Signature d'anomalie** (`agent/incidents.py`) — `(table, colonne, type, ordre de grandeur)`.
  - [x] ⭐ **L'ordre de grandeur est une octave, pas une décade.** `floor(log10)` mettrait 30 % et
        85 % de nulls dans le même seau — or c'est exactement la distinction qu'exige la granularité
        critique ci-dessous. `floor(log2)` change de seau **quand l'ampleur double** : 0,30 et 0,35
        restent silencieux, 0,85 reparle. L'échelle est logarithmique donc **sans unité** — elle vaut
        pour un taux comme pour un décompte, sur n'importe quel dataset.
  - [x] **`ampleur` devient un champ de premier rang de l'écart**, pas un détail : chaque famille
        nomme la sienne (un taux, un décompte, un score `z`), parce qu'elle seule sait ce qui chez elle
        veut dire « plus grave ». L'aller chercher après coup dans `details` demanderait au lecteur de
        connaître un format par famille — ce que la forme commune existe pour éviter. C'est elle qui
      définit ce que veut dire « la même anomalie ». Granularité critique : trop large = l'agent devient
      aveugle (« plus jamais de nulls sur `customer_id` » le ferait taire même à 90 %).
- [x] Tool `read_past_incidents` : SQL sur `INCIDENTS`, filtre `human_decision IS NOT NULL` (R5),
      match par signature. **La mémoire sert dans les deux sens** :
  - [x] `approved` → l'agent **retrouve la solution** : au J85 il cite l'incident du J60 et propose
        la même correction (c'est l'objectif O7, mesuré T1 vs T2 en phase 8)
  - [x] `rejected` → l'agent **se tait** : filtre appliqué entre `detect` et `diagnose`, l'écart est
        journalisé mais pas soumis. Il **reparle si l'ampleur change franchement** (30 % → 85 % de nulls
        n'est plus la même signature).
- [x] Garde-fou anti-cécité : `filtrer()` rend **deux listes** (retenus, tus) plutôt qu'une liste
      amputée — un appelant qui ne recevrait que les retenus ne pourrait pas journaliser les autres, et
      l'agent deviendrait muet sans que personne s'en aperçoive, invisible **parce qu'**il ne dit plus
      rien. Rien n'est supprimé, tout est en base — la liste des signatures en silence
      est requêtable (et affichée en phase 6, réactivable d'un clic)
- [x] `diagnose` réel : prompt = profil + anomalies + métadonnées + incidents passés ; sortie parsée
      Pydantic ; garde-fou sur le SQL proposé (table concernée uniquement, pas de mot-clé destructeur —
      première ligne de défense, `apply` re-vérifiera)
  - [x] ⚠️ **R2 change encore de nature** : `past_incidents` porte le JSON complet des anomalies
        passées, donc potentiellement des valeurs de données. `resumer()` énumère champ par champ ce
        qui sort, et `incidents_similaires()` restreint à ce qui partage une signature avec les écarts
        du jour. Même discipline que `construire_contexte()` pour le profil — on ne fait pas confiance
        à la forme stockée, on choisit.
  - [x] ⭐ **Le garde-fou SQL constate, il ne censure pas.** Le diagnostic est conservé tel quel et les
        alertes lui sont **attachées** (`alertes_sql`) : l'amputer priverait l'humain du raisonnement
        qui l'a produit, utile même quand le SQL proposé est mauvais. C'est `apply` qui refusera
        d'exécuter (phase 5) — le premier informe, le second protège.
  - [x] ⚠️ **`DELETE` n'est pas destructeur en soi** : c'est `DELETE` **sans `WHERE`** qui vide une
        table. Les confondre aurait refusé la correction la plus naturelle qui soit — supprimer les
        lignes dupliquées d'un lot.

### 4.5 Règles dynamiques & branchement Airflow
- [ ] ≥ 3 règles dbt générées (format, complétude, cohérence) écrites sur disque et **vertes** une fois
      réintégrées dans dbt
- [x] **Tâches Airflow `check_bronze` / `check_silver` / `check_gold`** *(2026-08-17)* : le DAG passe
      de 8 à **11 tâches**, toute la logique dans `scripts/check_layer.py`.
  - [x] ⭐ **Une pause n'est pas un échec — c'est LE point qui décide si le volet est utilisable.**
        `propose` appelle `interrupt()` : dès que l'agent trouve quelque chose, le run s'arrête. Si la
        tâche sortait alors en erreur, **le DAG serait rouge chaque fois que l'agent fait son
        travail** — et un pipeline rouge en permanence est un pipeline qu'on cesse de regarder, ce qui
        coûte bien plus cher que l'anomalie signalée. Le code de sortie ne répond qu'à *l'agent a-t-il
        pu tourner ?* ; ce qu'il a trouvé se lit dans `INCIDENTS`. Même convention qu'en 2.3 pour les
        tests dbt (`rc=1` = détection = vert).
  - [x] **Une table qui échoue n'emporte pas les autres** : dix-sept tables ne doivent pas mourir sur
        la troisième. L'échec est rapporté avec sa cause — même règle qu'en 4.2.5 et que dans `detect`.
  - [x] **Une couche vide échoue bruyamment** : ce n'est pas une anomalie de donnée mais une erreur de
        déclaration. La masquer ferait croire qu'une couche a été surveillée alors qu'aucune table n'y
        est déclarée.
  - [x] `thread_id` = `<dataset>|<table>|<jour>` — **reconstructible de tête**. Un identifiant
        aléatoire obligerait l'humain à le chercher dans un journal avant de pouvoir reprendre un run.
  - [x] **Rien à changer au `docker-compose.yaml`** : le repo entier est déjà monté
        (`../:/opt/airflow/project`), donc `agent_checkpoints.sqlite` vit des deux côtés à la fois et
        `scripts/decide.py` reprend depuis l'hôte sans configuration. Vérifié par lecture ; la seule
        réserve (permissions `AIRFLOW_UID` sous Linux) est notée dans `airflow/README.md`.
  - [ ] ⏭️ **Reste à exécuter sur le PC** — le DAG n'a pas encore tourné avec ces trois tâches. Le
        risque est faible (elles sont structurellement identiques aux huit qui ont fait 92 runs verts)
        mais il n'est pas nul : Airflow n'est pas une dépendance du projet, donc l'import du DAG n'est
        pas vérifiable ici. À grouper avec 4.6.

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
- [x] Construction de la proposition complète *(2026-08-17)* : anomalie, cause diagnostiquée, **SQL
      exact** de la correction, **impact estimé**, incidents similaires passés — `build_proposal()`
      existait depuis 3.2 ; 5.1 remplit le champ qui lui manquait.
- [x] ⚠️ **L'impact est la ligne la plus importante** — sans elle l'humain ne peut pas juger. Exemple :
      « 1 ligne sur 351 » semble négligeable jusqu'à voir « panier moyen 42,30 → 65,00 (+53,7 %) ».
      *Un humain qui ne peut pas juger n'approuve pas : il signe.* → `agent/impact.py`
  - [x] ⭐ **Aucune requête, et ce n'est pas de la paresse** : l'impact se calcule sur ce que `profile`
        a déjà mesuré. Un nœud qui interrogerait la base au moment de proposer comparerait un lot
        mesuré tout à l'heure à une base lue maintenant — l'écart affiché ne correspondrait alors ni à
        ce qui a été détecté, ni à ce que l'humain verrait s'il regardait lui-même. Même règle que
        `detect` (4.3) et la fraîcheur (4.1.4).
  - [x] ⭐ **Trois degrés de certitude, jamais un chiffre inventé** : `exact` (nulls, doublons, top-K),
        `minimum` (une borne dépassée prouve qu'une valeur sort, **jamais combien de lignes**),
        `inconnu`. Annoncer « 1 ligne » quand on veut dire « au moins 1 » ferait refuser une anomalie
        majeure sur la foi d'un chiffre qu'on a inventé.
  - [x] ⭐ **On ne somme jamais les lignes** : la même ligne peut porter un null *et* un doublon. Un
        total dépasserait la taille du lot dès que deux écarts se recouvrent, et « 420 lignes sur
        351 » détruirait la confiance dans tout le reste de la proposition. L'en-tête retient le
        **plus étendu**, les autres restent listés.
  - [x] **Des nombres, jamais un adjectif** : « impact modéré » ne veut rien dire et ne se conteste
        pas ; « 51 lignes sur 351 (14,5 %) » se vérifie, se discute et se compare au run d'hier. Une
        dérive se lit en variation — « 351 → 42 (−88 %) » dit en une ligne ce qu'un score `z` de −9,1
        ne dit à personne.
  - [x] ⚠️ **L'effet aval est annoncé comme non calculé**, pas tu : le « panier moyen +53,7 % » de
        l'exemple demande de remonter le lineage dbt, que PROGRESS place lui-même en **7.1**. Un impact
        qui l'omettrait en silence laisserait approuver une correction qui déplace un indicateur de
        moitié — le dire coûte un champ, le taire coûterait une mauvaise décision.
- [x] `interrupt()` avec la proposition en payload ; état persisté (checkpointer) *(acquis en 3.2)*
- [x] File des propositions en attente lisible **hors process** *(2026-08-17)* :
      `graph.propositions_en_attente()` + `scripts/decide.py --list`. Sans elle, un run mis en pause
      par Airflow à 3 h du matin n'existe pour personne — il faut déjà connaître son `thread_id` pour
      le retrouver, donc savoir qu'il existe.
  - [x] ⚠️ **Écart au plan** : la jointure avec `INCIDENTS` prévue n'a pas lieu d'être, parce qu'un run
        en pause **n'a pas de ligne dans `INCIDENTS`** — il n'a pas atteint `log`, qui est sa sortie.
        La file se lit dans le checkpointer seul ; la jointure vaudra pour les runs *terminés*.
  - [x] On passe par l'API du checkpointer (`saver.list`) et non par une requête sur sa base : le
        schéma interne de LangGraph n'est pas un contrat, et du SQL là serait du SQL hors connecteurs.
  - [x] ⚠️ **Piège attrapé** : itérer le générateur de `saver.list()` tout en appelant `get_state()`
        interroge la même connexion SQLite pendant qu'un curseur la consomme — la suite de tests ne
        finissait jamais, et le symptôme ne ressemblait pas à sa cause. La liste est matérialisée
        avant d'être parcourue.

### 5.2 Garde-fou : ne jamais inventer une valeur ⬅️ *nouveau*
Face à une valeur hors bornes (8000 dans une colonne à [1–100]), l'agent **ne peut pas savoir** s'il
s'agit de 80,00 € en centimes, d'une faute de frappe, ou d'une vraie grosse commande. Proposer
« remplacer 8000 par 80 », c'est **fabriquer de la donnée qui n'a jamais existé**.

- [x] Corrections **autorisées** *(2026-08-17, `agent/corrections.py`)* : isoler en quarantaine ·
      mettre à NULL + marquer · **normaliser** · exclure des agrégats Gold (la valeur brute reste
      intacte en Bronze pour audit)
  - [x] ⭐ **Une liste blanche de gestes, pas une liste noire d'interdits** — la leçon de 4.1.6 :
        une liste noire ne protège que de ce qu'on a pensé à y mettre. Ce qui ne ressemble à aucun des
        quatre gestes est refusé, **y compris ce qu'on n'a pas imaginé**.
  - [x] ⭐ **`normaliser` est ce qui sauve le fil rouge.** Sans lui, la règle « seul `NULL` peut être
        écrit » interdirait la correction que le projet existe pour montrer : `são paulo` →
        `sao paulo`. Ce qui distingue ce geste d'une invention est **vérifiable** — la valeur écrite
        est **déjà présente dans la colonne**. On ne crée rien, on choisit parmi ce qui existe ;
        `80` dans une colonne qui ne l'a jamais porté, lui, sort de nulle part.
  - [x] **Le vivier est ce qui a été *observé*, jamais ce que le contrat *admet*** : un contrat dit ce
        qui devrait être, pas ce qui est. Écrire une valeur admise mais jamais vue resterait une
        invention.
  - [x] ⚠️ **Refus qui surprend, et qui est pourtant le bon** : `SET city = LOWER(city)` est refusé.
        Il n'invente rien, mais ce n'est pas une correction — c'est une **transformation appliquée
        aussi aux lignes saines**, dont la place est dans le modèle Silver où elle sera relue,
        versionnée et testée. *L'agent corrige des lignes ; dbt transforme des colonnes.*
- [x] Correction **interdite** : substituer une valeur devinée — rejet dans `apply` **même après
      approbation humaine**, exactement comme les mots-clés destructeurs *(preuve P4, livrée)*
  - [x] ⭐ **Le garde-fou s'applique APRÈS l'approbation, et c'est tout son intérêt** : un humain peut
        approuver sans lire, et une règle qui cède devant un « oui » ne protège de rien.
  - [x] **`apply` ne lève pas, il refuse et journalise** : ce n'est pas un bug de câblage mais un cas
        métier — le modèle a proposé quelque chose d'inacceptable. Lever ferait perdre la trace du
        refus au moment précis où elle est la plus instructive, et contredirait « `log` est la sortie
        unique ».
  - [x] **Le refus dit le recours** : `--fix`. Un refus sans issue laisse l'humain bloqué ; il doit
        apprendre dans le même message que son autorité, elle, n'est pas soumise à P6.
  - [x] ⭐ **P6 contraint l'agent, PAS l'humain** — décision prise dès l'en-tête d'`apply` en 3.1 et
        tenue ici : « l'agent ne peut pas savoir si 8000 valait 80 ; toi, tu peux avoir appelé le
        fournisseur ». Les deux autres garde-fous restent pour les deux : ils protègent de
        l'accident, pas du jugement.
- [x] Proposition par défaut sur un outlier : *isoler + exclure de l'agrégat*, jamais *remplacer* —
      la seule réponse qui ne suppose rien sur ce que la valeur aurait dû être : la donnée brute reste
      en Bronze pour l'audit, et l'agrégat cesse d'être faux. Les deux moitiés du problème, sans en
      inventer une. Affichée dans la proposition avec le **pourquoi** — *un refus qu'on ne comprend
      pas se contourne ; un refus expliqué se respecte, ou se conteste, ce qui est aussi bien.*
- [x] Les quatre gestes autorisés sont **montrés dans la proposition** (`gestes_autorises`), même quand
      la correction est acceptable : un humain qui les voit comprend en une ligne pourquoi l'agent ne
      propose jamais « remplacer par la bonne valeur », et n'a pas à le redemander.

### 5.3 Reprise, Apply borné, Amend
- [ ] Injection de la décision : `approved` / `amend_contract` / `rejected` + **identité du décideur +
      horodatage** → stockés dans `INCIDENTS`
- [ ] `apply` réel : transaction SQL ; vérifications **même après approbation** :
  - [ ] la requête ne touche que la table diagnostiquée
  - [ ] rejet des mots-clés destructeurs (`DROP`, `TRUNCATE`, `DELETE` sans `WHERE`…)
  - [ ] ⬅️ *ajouté le 2026-08-17 (ADR 010, décision 14)* : le **seul DDL autorisé** est la restauration
        d'un nom de table, et seulement contre un écart de famille `inventaire`. Les garde-fous
        ci-dessus sont écrits pour du DML ligne à ligne : un `ALTER TABLE … RENAME TO …` n'est attrapé
        par aucun d'eux, et il porte **deux** noms de table — donc « ne toucher que la table
        diagnostiquée » doit se formuler en termes de *l'écart* (A absente, B nouvelle), pas d'un nom
        unique. Test dédié : c'est la seule écriture de l'agent qui modifie un **schéma** et non un
        contenu.
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
- [x] **P4** ⬅️ *nouveau* : une proposition qui substitue une valeur devinée est **rejetée par `apply`**
      même avec `human_decision == "approved"` *(livré en 5.2, `tests/test_p6.py`)*
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
| 2026-08-04 | 4 | 🚧 **4.1.3 statistiques robustes** : `ConnecteurSnowflake.robust_stats()` (médiane + MAD + bornes numériques), `agent/tools/robust_stats.py` (3ᵉ `@tool`), `agent/tools/_connecteur.py` (socle commun des tools qui lisent la base), [ADR 010](docs/adr/010-agent-generique.md) décision 10. **+15 tests, 277 verts.** 12 sabotages joués, tous détectés. | **Portée tranchée AVANT d'écrire** : « médiane + MAD » était ambigu — des *valeurs d'une colonne dans un lot*, ou d'une *métrique à travers les jours* ? Les deux sont nécessaires, mais la seconde a besoin de `OPS._PROFILES` (4.3) et **est** une comparaison, donc le travail de `detect`. 4.1.3 = la première ; sans ce partage, elle se codait contre une table absente. **Décision 10a** : le contrat se lit en deux familles — méthodes *de table* (un balayage) et *de colonne* (une requête par colonne). Généralise 9a et répond d'avance à « jusqu'où le contrat grossit-il ? ». **Décision 10b** : un MAD nul est rendu tel quel, le plancher anti-division-par-zéro appartient à `detect`. *Une mesure qui se corrige elle-même ment sur ce qu'elle a vu* — et le lecteur ne peut plus distinguer « constante » de « varie très peu ». **Piège Snowflake** : `TRY_CAST` **n'accepte qu'une source texte**, l'appliquer à une colonne déjà `NUMBER` lève ; le type vient d'`INFORMATION_SCHEMA`, qu'on interroge déjà pour la casse. Deux autres : `MEDIAN(...) OVER ()` pour avoir la médiane *avant* de la soustraire (MAD en un balayage au lieu de deux requêtes), et `SUM` sur zéro ligne qui rend `NULL` et non `0` — `int(None)` aurait tué le run censé signaler le lot vide. **⭐ Mesure non prévue au plan** : en traitant la contrainte « Bronze est VARCHAR » au lieu de la contourner, compter ce que `TRY_CAST` n'a pas su lire donne `numeric_rate` — 1,0 = colonne saine, 0,7 = un tiers du format cassé. Une détection de **dérive de format**, obtenue pour rien. **Erreur de ma part, corrigée** : j'avais posé comme invariant R2 « la sous-requête ne projette pas la colonne nue ». Faux — sur une colonne déjà numérique elle la projette forcément, et le test est parti rouge sur du code juste. La sous-requête ne quitte jamais la base ; la frontière R2 est la projection **externe**. Le docstring du test garde la trace. |
| 2026-08-04 | 4 | ✅ **4.1.5 `profile_table` — chemin critique franchi** : l'assembleur (agrégats + top-K + stats robustes en une fiche), le critère provisoire dans `_mesure_pour()`, [ADR 010](docs/adr/010-agent-generique.md) décision 11. **+19 tests, 296 verts.** 10 sabotages joués : **7/10 au premier tour**, 10/10 après correction. | **Décision 11, tranchée par le porteur du projet** : l'assembleur porte le critère, pour être appelable seul. Écarté : faire lister les colonnes par l'appelant — honnête, mais le problème remontait d'un cran et 4.3 aurait inventé sa règle dans un nœud, sans test dédié. **⭐ La consigne a dû être reformulée, et c'est le vrai enseignement de l'étape** : « texte + faible cardinalité / numérique » lu littéralement (via `DATA_TYPE`) donnait un tool **inutilisable sur Bronze**, où tout est VARCHAR par construction — aucune colonne numérique reconnue, donc aucune statistique robuste sur la couche où les anomalies sont injectées. Le critère ne lit donc **aucun nom de type**, seulement des faits mesurés : bornes lisibles comme des nombres → `robust_stats`, cardinalité ≤ 50 % → `top_values`. L'intention est conservée, seul le signal change — et les bornes disent la vérité là où le type ment. Bénéfice second : aucun dialecte SQL n'entre dans une couche censée l'ignorer (décision 2). **Piège silencieux attrapé** : `profile` rend `max="90"` (lexicographique) et `robust_stats` `max=8000.0` (numérique) — fusionner sous la même clé aurait fait comparer deux grandeurs différentes selon la couche. `numeric_min`/`numeric_max` vivent à côté. **Leçon de méthode, la plus coûteuse jusqu'ici** : 3 sabotages sur 10 sont passés inaperçus, et les trois pointaient des trous réels. (1) aucun cas n'avait `min` numérique et `max` non — le `and` n'était jamais éprouvé ; (2) le garde-fou « ne pas annoncer une mesure qui n'a pas abouti » existait dans le code sans aucun test — *un garde-fou non testé est du poids mort* ; (3) **le pire** : mon espion n'enregistrait que le nom de la colonne, pas le lot, donc « le lot n'est plus transmis » ne faisait rougir personne — c'est-à-dire précisément la dilution que tout le projet redoute (30 % de nulls sur un batch → 0,3 % noyés dans 92 jours). Un test qui regarde le bon appel mais pas les bons arguments ne prouve rien. **Point ouvert assumé** : chaque méthode de colonne résout son propre schéma, donc une requête `INFORMATION_SCHEMA` par colonne mesurée ; remède local connu (mémoriser le schéma sur l'instance de connecteur), **non implémenté** — mesurer sur le vrai Snowflake avant d'optimiser, en 4.5. |
| 2026-08-04 | 4 | 🚧 **4.2.1 caractérisation par rôle** — le moteur de généricité : `agent/characterize/` (6 rôles + `unknown`), branché dans `profile_table` en remplacement du critère provisoire, [ADR 010](docs/adr/010-agent-generique.md) décision 12. **+33 tests, 329 verts.** 13 sabotages joués : **10/13 au premier tour**, 13/13 après correction. | **Décision 12a** : le rôle se déduit des faits, jamais du type déclaré — l'argument de 4.1.5 vaut ici *a fortiori*, en Bronze tout est VARCHAR et un classement fondé sur `DATA_TYPE` y verrait six colonnes de texte libre. Cinq faits suffisent, tous rendus par `profile` ; **classer ne coûte donc aucune requête**, alors que c'est le classement qui engage les requêtes coûteuses. **⭐ Décision 12b — l'ordre des tests EST la décision** : `order_purchase_timestamp` est unique à 99 % et sans nul, donc *identifiant* au sens strict ; le classer ainsi ferait perdre fraîcheur, dates futures, trous et monotonie pour ne gagner qu'un contrôle d'unicité sur une colonne qui n'identifie rien. Règle : le rôle le plus exigeant gagne. **Décision 12c** : `RATIO_UNICITE_MIN = 0.99` et non 1,0 — sinon une clé primaire portant trois doublons deviendrait du texte libre et perdrait son contrôle d'unicité **au moment précis où elle le viole**. **Laissé de côté, écrit plutôt que bricolé** : la clé étrangère n'est pas un fait de colonne (→ 4.2.2) ; un code non unique reste indiscernable d'une quantité, et c'est la validation humaine du contrat qui le tranchera — ajouter une heuristique de nommage ferait perdre `test_aucun_nom_de_colonne_n_intervient`, le garde-fou de généricité du module. **Leçon de méthode, en deux temps.** (1) Un sabotage était **équivalent** : « le test temporel passe après l'identifiant » déplaçait le calcul de `unicite` mais laissait l'ordre intact — il ne changeait rien, donc « non détecté » ne disait rien. Après le script contaminé (1.5) et le sabotage irréaliste (4.1.1), 3ᵉ variante : un sabotage doit changer le **comportement**, pas seulement le texte. (2) Les deux autres manqués étaient de vrais trous **que mon propre refactor avait créés** : les cas « une seule borne lisible » existaient en 4.1.5 — écrits après qu'un sabotage identique soit passé — et déplacer le critère vers `characterize/` les a supprimés avec l'ancien test. *Un refactor déplace le code, pas la couverture.* |
| 2026-08-04 | 4 | 🚧 **4.2.2 proposition de contrat** — `agent/contracts/proposer.py` + `agent/characterize/collisions.py`, [ADR 010](docs/adr/010-agent-generique.md) décision 13. **+24 tests, 353 verts.** 17 sabotages joués : **15/17**, puis 16/17, puis 17/17. | **Écart au plan assumé** : 4.2.2 (proposer) et 4.2.3 (critiquer) livrées **ensemble** — livrer la proposition seule aurait produit un générateur qui grave `são paulo` comme valeur légitime, artefact que la décision 3 interdit. *Une étape intermédiaire connue pour être fausse n'est pas une étape.* **⭐ Décision 13a — la découverte RETIRE la clause au lieu de l'assortir d'un avertissement** : *un avertissement se survole, une clause absente ne peut pas être approuvée par distraction*. C'est la réponse à la question de jury que `DESIGN.md` anticipe (« et si l'humain approuve sans lire ? »). **Troisième refus non prévu, et le plus sournois** : un top-K tronqué (`coverage < 1`) ne donne pas `accepted_values` — les K valeurs les plus *fréquentes* laissent dehors des valeurs légitimes, et le contrat **crierait dès le lendemain sur des données saines**. C'est `coverage`, introduit en 4.1.2 pour une raison de confidentialité, qui rend ce refus possible. **Décision 13b, symétrique** : `unique` et `no_semantic_collisions` sont proposées même quand elles sont déjà violées, avec avertissement chiffré — escamoter la clause répondrait à la place de l'humain à « nettoie-t-on, ou accepte-t-on ? ». **Règle dégagée** : *ce qui relève du constat est proposé, y compris quand il dérange ; ce qui relève de la preuve est retiré quand la preuve manque.* **Décision 13c** : le repli ne supprime pas les espaces — `sãopaulo` y échappe, mais les supprimer fusionnerait `arco verde` et `arcoverde`, deux communes distinctes ; sans coût, les 18 variantes du J50 sont toutes accentuelles. **Leçon de méthode — trois tests qui ne pouvaient pas échouer, en deux étapes.** (1) `assert contrat["status"] == PROPOSE` comparait la constante **à elle-même** : passer `PROPOSE` à `"approved"` — donc déclarer le contrat validé sans qu'aucun humain n'ait tranché — laissait le test vert. Corrigé par une chaîne en dur + un test qui fige tout le vocabulaire (il sortira vers les YAML, `INCIDENTS` et les écrans de la phase 6). (2) « le texte libre ne reçoit jamais de valeurs acceptées » utilisait une colonne **sans valeurs** : il n'y avait rien à fuiter, la propriété tenait par construction et non par vérification — sans effet aujourd'hui, mais le tableau des rôles prévoit de mesurer les longueurs du texte libre. (3) **Le plus retors** : le test de déterminisme des grappes comparait deux appels **du même processus**, or Python fixe sa graine de hachage au démarrage — un ensemble s'y parcourt toujours pareil. Le sabotage a été détecté à un tour puis manqué au suivant : *l'instabilité du score était elle-même le diagnostic*. Corrigé (deux grappes, ordre d'entrée ≠ ordre attendu, grappe à 4 écritures) et **vérifié rouge sous 8 graines de hachage**. Une suite verte à 90 % de chances est pire qu'une suite rouge : elle passe en local et casse en CI. |
| 2026-08-04 | 4 | 🚧 **4.2.4 contrats sur disque** : `agent/contracts/loader.py` (écrire, relire, versionner), `contracts/<dataset>/<TABLE>.v<N>.yaml` versionnés dans git. **+14 tests, 367 verts.** 10 sabotages joués, **10/10 du premier coup**. | **⭐ `charger()` ne rend que du validé** — garantie structurelle du même rang que R3. Un contrat `proposed` décrit ce que la machine a *observé* ; s'il pouvait être appliqué par `detect`, la validation humaine deviendrait décorative et le système se donnerait à lui-même la permission qu'il est censé demander. **Mais l'attente reste visible** (`lister()`) : « aucun contrat » et « un contrat qui attend une signature » sont deux situations différentes, et les confondre serait un état silencieux — le même défaut que ceux que la mutation traque. **Trois protections du travail humain** : (1) écrire n'écrase jamais un contrat validé — rejouer une découverte sur une proposition est normal, sur une décision c'est refusé, l'amendement passe par une version suivante (phase 5) ; (2) le **nom du fichier n'est pas l'identité** — `table` et `version` vivent dans le contenu et sont confrontés au nom, sans quoi un `git mv` malheureux appliquerait les clauses de `RAW.ORDERS` à `RAW.CUSTOMERS` silencieusement ; (3) **`allow_unicode=True`** — sans lui `são paulo` s'écrit `s\xE3o paulo`, et le contrat deviendrait illisible **précisément** sur le cas que le projet existe pour montrer. On ne valide pas ce qu'on ne peut pas lire, donc le test relit le fichier brut et non l'objet rechargé. **Choix de structure** : lecture et écriture dans le même module — le format n'existe qu'à un endroit, donc il ne peut pas se désynchroniser entre celui qui écrit et celui qui relit (même leçon que le schéma du graphe, dessiné à la main puis dérivé, aujourd'hui généré depuis le code). |
| 2026-08-04 | 4 | ✅ **4.2.5 cycle Découverte — phase 4.2 terminée** : `scripts/discover.py` (profiler → proposer → écrire → signer), 4 sous-commandes. **+14 tests, 381 verts.** 11 sabotages joués : **9/11**, puis 11/11. | **⚠️ Écart au plan assumé : la pause est un fichier, pas un `interrupt()`.** Un checkpoint garderait une **copie** du contrat pendant que l'humain édite le **fichier** ; à la reprise, le graphe réécrirait la sienne et **effacerait les corrections** — silencieux, et il détruit exactement ce que l'étape sert à produire. Le fichier devient la seule source de vérité ; la pause est sa présence sur disque en `status: proposed`. Elle survit à un redémarrage mieux qu'un checkpoint, se relit en pull request, se compare d'une version à l'autre. La propriété qui comptait est conservée — `charger()` ne rend jamais un contrat non validé — et un test édite le YAML entre proposition et validation pour prouver que la correction survit. **⭐ La découverte profile la table ENTIÈRE, à rebours de la surveillance** : celle-ci filtre par lot (sinon 30 % de nulls sur un jour ne pèsent plus que 0,3 % sur 92), celle-là cherche ce qui est *normal* — un contrat bâti sur une seule journée serait absurdement étroit, et les valeurs légitimes absentes ce jour-là deviendraient des violations dès le lendemain. **La dilution est l'ennemi de l'une et la condition de l'autre.** **Deux garde-fous sur la signature** : `--by` obligatoire (un contrat sans signataire ne prouve rien six mois plus tard, même traçabilité que `decided_by`), et `--accept-warnings` pour signer ce que la découverte a critiqué — sans quoi le cas São Paulo se validerait d'un `--approve` distrait et toute la critique de 4.2.2 aurait servi à rien. **Une table qui échoue n'arrête pas les autres** : l'échec est rapporté avec sa cause, pas avalé. **Leçon de méthode — un sabotage a révélé du code mort.** Le contrôle « déjà validé » de `approuver()` a été retiré sans qu'aucun test ne rougisse : le refus vient en réalité d'`ecrire()`, qui seul touche au disque. La redondance ne portait rien et donnait l'illusion d'une garantie qui vit ailleurs — **supprimée** plutôt que protégée par un test de plus, et le sabotage réaligné sur le garde-fou réel. Second manqué, vrai trou : aucun test n'avait deux versions d'une même table, alors que `approuver()` prend la plus récente — chemin non atteignable aujourd'hui (la découverte n'écrit que des v1) mais que l'amendement empruntera en phase 5. *Du code que personne n'éprouve finit par être faux le jour où quelqu'un s'y fie.* |
| 2026-08-17 | — | 🔧 **Remise en service des accès, aucun code métier.** Le trial Snowflake du 21 juillet a expiré → **second trial** ouvert (plan B de l'[ADR 001](docs/adr/001-snowflake-access.md)), `.env` mis à jour, `check_access.py` **tout vert**. Quatre correctifs : `CREATE WAREHOUSE IF NOT EXISTS` dans `setup_snowflake.py` ; modèle Groq migré ; `check_access.py` importe le nom du modèle et **vérifie la réponse** ; `.gitignore` élargi à `.env*`. **387 tests verts, lint vert.** | **Le trial expire vers le 2026-09-16** — à surveiller. **Trou dans la promesse « tout est rejouable »** : `setup_snowflake.py` faisait `ALTER WAREHOUSE` sans jamais le **créer**. Sur l'ancien compte il préexistait ; sur un compte neuf le script échouait **dès sa première instruction** — c'est-à-dire précisément le jour où il devait servir. *Un script de reconstruction qui n'a jamais reconstruit depuis zéro n'est pas rejouable, il est seulement idempotent.* **Modèle décommissionné sans préavis utile** : `llama-3.3-70b-versatile` rend un 404 `model_not_found`, toute la famille Llama a disparu de GroqCloud. Trois candidats essayés **dans les conditions réelles du projet** (mode JSON natif + `temperature=0`) plutôt que choisis sur catalogue : `gpt-oss-120b` ✅ et `gpt-oss-20b` ✅ rendent les trois clés attendues, `qwen3.6-27b` ❌ échoue en `json_validate_failed`. Retenu : **`openai/gpt-oss-120b`**, même gamme que le 70b remplacé. ⭐ **R1 s'est payée d'elle-même** : la migration a coûté **une ligne**, parce qu'un seul fichier nomme le modèle. La frontière réseau unique n'est pas qu'une propriété d'audit — c'est ce qui rend un fournisseur remplaçable. **Piège du modèle de raisonnement** : `gpt-oss-120b` dépense ses tokens dans un champ `reasoning` séparé avant d'écrire ; les `max_tokens=5` qui suffisaient à Llama partaient **entièrement** dans la réflexion et `content` revenait **vide** (`finish_reason="length"`). `diagnostiquer()` n'est pas touché (il ne plafonne pas les tokens, vérifié), mais un plafond ajouté plus tard casserait le diagnostic en silence. **Opportunité notée pour la phase 6** : ce champ `reasoning` est exactement ce que l'écran « raisonnement du LLM » veut afficher. **Leçon de méthode, la même qu'en mutation mais hors des tests** : `check_access.py` affichait **✅ sur une réponse vide** — il ne vérifiait que l'absence d'exception. *Un contrôle qui ne peut pas échouer ne prouve rien*, et celui-ci gardait la porte d'entrée du projet (« si `check_access` n'est pas vert, arrêtez-vous là »). Il compare désormais la réponse à `"OK"` et **importe** `MODELE` au lieu de le recopier — sans quoi il aurait continué à valider le modèle mort après la correction d'`agent/llm.py`. **Incident de sécurité évité** : ma sauvegarde `.env.bak-crlf` n'était **pas** couverte par `.gitignore` (`.env` ne matche que `.env`) et apparaissait en untracked — à un `git add -A` de commiter le mot de passe. Élargi en `.env*` + `!.env.example`. *Le CRLF, lui, venait de l'édition sous Windows : `python-dotenv` le tolère, mais `make dbt-*` **source** le `.env` en shell et aurait collé un `\r` à chaque variable — panne dbt incompréhensible, trois étapes plus loin.* |
| 2026-08-17 | 1 · 2 · 4 | ✅ **Infrastructure reconstruite de zéro + 1ʳᵉ exécution réelle du cycle Découverte.** Second trial → `setup_snowflake.py` → rejeu **J1→J43** → ingestion Bronze → `dbt run` **11/11** → `dbt test` **18 PASS / 0 échec** → `discover olist` : **17 contrats proposés, 16 avertissements, 0 échec** en 2 min 54. `contracts/olist/` n'est plus vide. Puis **décision 12d** dans `agent/characterize/roles.py` + régénération des 17 YAML. **+22 tests, 409 verts.** 3 sabotages joués, 3/3 détectés. | **La reconstruction complète a validé le plan B de l'ADR 001** : partir d'un compte vide et retrouver `18 PASS / 0 échec` prouve que rien n'a jamais été fait à la main dans la console. Invariants de la §1.5 revérifiés sur la base neuve : `AMOUNT` absente du schéma **et** de `_SCHEMA_HISTORY`, 5 marqueurs `.injected` tous hors fenêtre (J45/J60/J75/J80/J85), **écart de cardinalité normalisée = 0**, 5 942 villes. **⭐ La découverte a tenu sa promesse la plus difficile** : `CUSTOMER_CITY` reçoit `no_semantic_collisions` mais **pas** `accepted_values` — couverture 43 %, la preuve manque, la clause est retirée (décision 13a) au lieu d'être assortie d'un avertissement qu'on survolerait. Sur 128 colonnes : `accepted_values` n'apparaît que **10 fois sur 26 colonnes catégorielles**. **Ce que seule l'exécution réelle pouvait révéler — et c'est le vrai apport de la séance.** (1) **Deux mesures Gold classées identifiants** : `REVENUE` et `AVG_ORDER_VALUE`. Les conditions « unique **et** jamais nul » étaient écrites *exactement* contre ce cas (le commentaire du code le disait) et ne suffisaient pas — sur 43 lignes, un montant flottant les satisfait toutes les deux. Elles recevaient `unique` et **perdaient leur `between`** : la détection d'aberration disparaissait de la métrique la plus visible du projet, soit le cas « 8000 dans une colonne à [1–100] » neutralisé sur le mart de démonstration. Corrigé par la **décision 12d** (la partie fractionnaire disqualifie l'identifiant) ; après régénération : identifiants 12 → 10, `between` 42 → 44, et les 10 identifiants restants sont **tous** de vraies clés. (2) **Non corrigé, laissé ouvert** : `TOP_K_DEFAUT = 20` refuse `accepted_values` à `CUSTOMER_STATE` (99 % de couverture, 27 états) et à `PRODUCT_CATEGORY_NAME` (86 %, 73 catégories). Ici la preuve **existe**, elle n'a pas été demandée — `distinct` est déjà dans le profil, donc `k = distinct` sur cardinalité modeste la rendrait prouvable sans une requête de plus. Sur `CUSTOMER_CITY` (1 552 villes) le refus resterait, et c'est correct. **Leçon de méthode** : ces deux défauts étaient invisibles en test unitaire parce qu'ils ne naissent pas d'une erreur de logique mais d'un **régime de données** — 43 lignes, 27 modalités — qu'aucune fixture écrite à la main n'avait reproduit. *Un moteur de généricité ne se valide pas sur des cas choisis ; il se valide sur un vrai schéma en entier.* **Coût mesuré, point ⏭️ de 4.1.5 enfin chiffré** : 2 min 54 pour 17 tables et 128 colonnes, dont 1 000 163 lignes de `GEOLOCATION` — la requête `INFORMATION_SCHEMA` par colonne ne justifie aucune optimisation. |
| 2026-08-17 | 4 | 🚧 **`TOP_K` adaptatif — le 2ᵉ défaut révélé par la découverte réelle est corrigé.** `CARDINALITE_ENUMERABLE_MAX = 100` (`top_values`) + `_k_pour()` (`profile_table`), puis 3ᵉ régénération des 17 contrats. **+10 tests, 419 verts.** 4 sabotages joués, **4/4 détectés**. | **Le refus doit porter sur une preuve *absente*, pas *non demandée*.** La décision 13a retire `accepted_values` quand le top-K est tronqué — raisonnement juste, mais il s'appliquait à un manque que l'assembleur créait lui-même : 27 états brésiliens et 73 catégories produit ne tenaient pas dans un `k` fixé à 20. Sous le seuil on demande désormais `k = distinct` ; `distinct` étant déjà dans le profil, **décider ne coûte aucune requête** et mesurer n'élargit qu'un `LIMIT` sur un `GROUP BY` déjà payé. **Résultat mesuré** : avertissements **16 → 8**, `accepted_values` **10 → 18** — les 27 états et les 73 catégories sont maintenant énumérés dans les 3 couches, tandis que `CUSTOMER_CITY` (43 %), `GEOLOCATION_CITY` (39 %), `PRODUCT_ID` (7 %) et `SELLER_ID` (24 %) restent refusées, à juste titre. **Pourquoi 100** : au-delà, une énumération cesse d'être une clause qu'un humain relit et devient un export — la limite est ce qu'un validateur peut *tenir*, pas ce que la base peut rendre. **R2 y gagne plutôt qu'elle n'y perd** : une colonne de moins de cent modalités est catégorielle par n'importe quelle mesure, c'est-à-dire le régime où « une distribution, pas une ligne » est le plus défendable. **Leçon de méthode — le mouchard ne regardait pas le bon argument.** `ConnecteurComplet.top_values()` enregistrait `(colonne, batch_column, batch_id)` mais **pas `k`**, alors que son propre commentaire promettait « tous les arguments ». Tant que `k` était une constante c'était sans conséquence ; devenu une décision, il fallait le voir — sans quoi `_k_pour()` aurait pu être parfaitement juste et n'être jamais appelé. C'est **mot pour mot** la faille de 4.1.5 (« un test qui regarde le bon appel mais pas les bons arguments ne prouve rien »), et elle est revenue par un chemin neuf : non pas un test oublié, mais un test dont la portée a été *dépassée par le code*. Sabotage n°1 (retour à la constante) : détecté par ce seul test. |
| 2026-08-17 | 4 · 5 | 📐 **Question ouverte de 4.3 tranchée** ([ADR 010](docs/adr/010-agent-generique.md), **décision 14**) + `docs/CONTRATS.md` et son générateur `scripts/export_contracts_doc.py`. **+22 tests, 441 verts.** 4 sabotages joués, 4/4 détectés. | **Le registre n'est pas amendable par l'agent** — et le graphe **ne change pas** (8 nœuds, 3 issues). Ni l'élargissement d'`amend_contract`, ni la 4ᵉ issue : les deux partaient du principe qu'un renommage est *une* situation, alors qu'il en recouvre **deux** que la machine ne peut pas distinguer et que l'humain tranche d'un regard — *vrai renommage métier* → `rejected`, l'humain corrige `datasets/<dataset>.yaml` en git ; *renommage accidentel* → `approved`, `apply` restaure le nom d'origine. **Le fondement, et il vaut au-delà de ce cas** : le contrat est *descriptif devenu normatif* (la machine propose, l'humain signe), donc un nœud peut légitimement le faire évoluer ; le registre est *normatif d'emblée* — il déclare un **périmètre**. Un agent qui réécrit son propre périmètre de surveillance décide de ce qu'il surveille, soit exactement l'autorité que le projet lui refuse, au même titre que l'écriture sans approbation. **⭐ P6 tient par construction** : restaurer un nom n'est pas *inventer* une valeur — le nom d'origine est **lu** dans le registre, pas deviné. C'est le contraire du cas « 8000 dans une colonne à [1–100] », où aucune source ne dit ce que la valeur aurait dû être ; ici la source existe, et c'est le registre. **Trois conséquences consignées plutôt qu'oubliées** : (a) `apply` émettra du **DDL** pour la première fois — les garde-fous de 5.3 sont écrits pour du DML ligne à ligne, un `ALTER TABLE … RENAME` n'est attrapé par aucun d'eux et porte **deux** noms de table, donc « ne toucher que la table diagnostiquée » doit se formuler en termes de l'*écart* et non d'un nom ; (b) `rejected` fait taire la signature, donc un registre non corrigé rend l'agent muet sur une table qu'il ne voit plus — couvert par l'écran « signatures en silence » de la phase 6, réactivable d'un clic ; (c) `INCIDENTS` ne distingue pas les deux « non », la requête de la phase 8 devra joindre sur la **famille** de l'écart et pas sur la seule décision. **Bénéfice second, non négligeable** : `README`, `CAHIER_DES_CHARGES`, `ARCHITECTURE`, `DESIGN` et le diagramme n'ont rien à changer — la remise en cohérence de la phase 3.0 tient, et `amend` garde un seul métier. **Documentation des contrats** : `docs/CONTRATS.md` (17 fiches) est **généré**, pas écrit — un contrat n'est pas stable (`proposed` → `approved` → `v2`), et une fiche recopiée serait fausse dès la première signature, en affirmant qu'une règle s'applique alors qu'elle attend une décision humaine. **Deux bugs introduits puis corrigés dans le générateur, tous deux invisibles à l'exécution** : un `<details>` entouré de lignes vides **interrompait le tableau Markdown** (GitHub aurait rendu les colonnes suivantes en texte brut) et les ancres retiraient les underscores, cassant 11 liens de sommaire sur 17. Le script annonçait un succès dans les deux cas. *Une sortie qu'on ne relit pas dans son format de destination n'est pas vérifiée.* |
| 2026-08-17 | 4 | 🚧 **Phase 4.3 commencée — `profile` réel + `OPS._PROFILES`** : `agent/config.py`, la mémoire des profils (format long, idempotente), le nœud branché sur `profile_table`, et le garde-fou « aucun test n'ouvre de connexion ». **+19 tests, 460 verts.** 7 sabotages joués : **6/7 au premier tour**, 7/7 après correction. | **⭐ L'exclusion du lot courant est portée par le SQL, pas par l'ordre des appels.** Le plan posait « lire l'historique avant d'y écrire » comme impératif ; l'ordre suffit au premier passage et **casse au rejeu** — un lot déjà profilé hier serait relu aujourd'hui comme du passé, sa médiane se rapprocherait de lui, et l'anomalie deviendrait la norme à force d'être réessayée. Airflow rejoue une tâche en cas d'échec : le cas n'est pas théorique. Une garantie portée par la requête tient quel que soit l'appelant, y compris celui auquel on n'a pas pensé. **⚠️ Bug attrapé à l'écriture, pas au test** : j'avais pris `profil["batch_id"]` pour clé d'archivage. Un mart Gold n'a pas de colonne de lot, ce champ y vaut toujours `None` — chaque run aurait donc écrasé le précédent, et **Gold, la couche où les chiffres faux se voient, aurait été la seule sans historique** ni dérive statistique. La clé est le lot du **run** : ce qu'elle désigne, c'est *quand la mesure a été prise*, et que le profil couvre un jour ou toute la table est une propriété de la mesure, pas de sa date. **Choix de format** : long (dataset, table, lot, colonne, métrique, valeur) — la comparaison devient un `GROUP BY` avec `MEDIAN()`, donc du SQL qui reste sous la couture, et ajouter une métrique ne demande aucun DDL (ce qui compte : 4.1.3 en a déjà produit une non prévue au plan). `column_name` à `NULL` pour une métrique de table plutôt qu'un nom sentinelle, qui entrerait en collision le jour où une vraie colonne le porterait. **Ce qui n'entre pas dans l'historique, et pourquoi** : `top` (une liste, pas une mesure), `role`, `type`, et les `min`/`max` **lexicographiques** — ces derniers ne répondent pas à la même question que `numeric_min`/`numeric_max` (piège de 4.1.5), et les comparer d'un jour à l'autre sur Bronze n'aurait pas de sens. Chaque question a déjà son lieu ; on n'en duplique aucune. **Décision de découpage** : `detect` ne fera **aucune entrée-sortie** — c'est `profile` qui charge la référence dans l'état. Ses cinq familles doivent être déterministes et reproductibles au benchmark, donc éprouvables sur de simples dictionnaires : un détecteur qui ouvre une connexion est un détecteur qu'on ne peut pas rejouer à l'identique. **Leçon de méthode, et c'est la même qu'en 3.3 à un an d'écart** : brancher le `profile` réel a fait passer la suite de **16 secondes à 5 minutes, avec 82 échecs**. Elle ne testait plus l'agent, elle testait le réseau — et elle aurait consommé les crédits d'un trial qui expire. En 3.3 c'était le LLM, ici c'est la base : même cause (une couture nouvelle qu'aucune barrière ne couvrait), même parade (un double par défaut dans `conftest.py` **plus** une barrière qui fait échouer bruyamment toute connexion réelle). *Une règle qu'on peut oublier n'est pas une règle* — il aura fallu se le prouver deux fois. **Sabotage manqué au premier tour, et vrai trou** : retirer la création paresseuse de `_PROFILES` du chemin d'écriture laissait la suite **verte**. Le garde-fou existait dans le code sans qu'aucun test ne le touche — or c'est lui qui fait qu'un compte neuf n'échoue pas au premier run sur un `Table does not exist`, c'est-à-dire exactement le scénario qu'on venait de vivre en rouvrant un trial. *Un garde-fou non testé est du poids mort*, troisième occurrence. Couvert désormais sur les **deux** chemins, lecture comprise. |
| 2026-08-17 | 4 | ✅ **`detect` et ses cinq familles** — `agent/detect/` (un module par famille), `agent/nodes/detect.py` (orchestration), `profile` charge désormais les cinq références, `lire_schema(avant=…)`. **+38 tests dédiés, 499 verts.** 8 sabotages joués, **8/8 détectés**. | **⭐ Aucune famille ne fait d'entrée-sortie, et c'est structurel.** Deux raisons, et la seconde est la vraie : le benchmark doit rejouer la détection à l'identique ; mais surtout une famille qui interroge la base *pendant qu'elle raisonne* compare des choses mesurées à des instants différents — l'écart qu'elle rapporterait n'aurait de sens ni pour le lot, ni pour aujourd'hui. `profile` rassemble donc les cinq références (profil, historique, contrat, schéma connu, inventaire) et `detect` n'est plus que des fonctions pures sur l'état. **⭐ Écart au plan assumé : aucun plancher sur le MAD.** Le plan en prévoyait un contre la division par zéro sur un historique constant. Refusé : les métriques n'ont pas la même échelle, donc aucun plancher absolu n'a de sens, et un plancher relatif vaudrait zéro précisément quand la médiane vaut zéro — le cas visé. Surtout, **un MAD nul est une information, pas un défaut** : la métrique n'a jamais bougé ; si elle bouge, aucun score n'est nécessaire pour le dire. D'où un type d'écart distinct, `rupture_de_constante`, rapporté par son écart brut. C'est la décision 10b (« une mesure qui se corrige elle-même ment sur ce qu'elle a vu ») appliquée à la détection. **⭐ `no_semantic_collisions` n'est pas vérifié par la famille contrat** : un même fait produirait deux écarts, donc deux propositions pour une seule anomalie et un taux d'approbation faussé au benchmark. Surtout, São Paulo doit être vu sur une table **sans contrat signé** — sinon la détection du fil rouge dépendrait d'une signature humaine. **Bug de conception attrapé en écrivant la famille schéma** : `lire_schema()` rendait « le dernier schéma observé », or l'ingestion écrit `_SCHEMA_HISTORY` **avant** que l'agent tourne — la comparaison aurait porté sur le schéma d'aujourd'hui contre lui-même, et le renommage du J45 serait passé inaperçu. Ajout de `lire_schema(avant=lot)`, exactement le même remède que l'exclusion du lot courant dans `lire_historique` : la garantie vit dans la requête, pas dans l'ordre des appels. **Faux positif permanent évité** : la clause `unique` compare `distinct` à `lignes − nulls`, sinon toute colonne unique portant des nulls paraîtrait en doublon à chaque run. **Robustesse** : une famille qui lève n'emporte pas les autres, l'échec est journalisé (`familles_en_echec`) — *un agent silencieusement aveugle est pire qu'un agent partiellement aveugle*. **Coût de l'inventaire borné** : les schémas ne sont relevés que pour les tables présentes et **non déclarées** — les seules qu'on ne connaît pas, donc les seules qui puissent étayer un renommage. Dans le cas normal il n'y en a aucune : une requête au lieu d'une par table à chaque run. **Leçon de méthode** : le sabotage « moyenne + écart-type au lieu de médiane + MAD » n'est attrapé que par **un seul test** — celui de la récidive J60→J85 sur un historique volontairement pollué par l'anomalie précédente. Sans lui, la contamination de la référence serait passée et l'objectif O7 (la mémoire mesurée T1 vs T2) se serait effondré au benchmark sans qu'aucun test ne rougisse. *Les propriétés qui comptent le plus sont souvent celles qu'un seul test protège — encore faut-il savoir lesquelles.* **Reste en 4.3** : l'intégration des échecs `dbt test`, qui est une entrée fournie par Airflow (4.5) et non une mesure que l'agent prend. |
| 2026-08-17 | 4 | ✅ **Phase 4.4 — `INCIDENTS` et la mémoire dans les deux sens** : `agent/incidents.py` (signature), `agent/detect/silence.py` (filtre), `agent/sql_guard.py`, `OPS.INCIDENTS`, les tools `write_log` et `read_past_incidents`, `log` réel, `diagnose` branché sur la mémoire. **+33 tests, 532 verts.** 8 sabotages joués, **8/8 détectés**. | **⭐ L'ordre de grandeur est une octave, pas une décade.** C'est le quatrième terme de la signature, et tout en dépend : trop large, un refus sur « 3 % de nulls le lundi » devient « plus jamais de nulls sur cette colonne » et l'agent se tait à 90 % ; trop étroite, la valeur exacte ne se répète jamais et le J85 ne retrouve pas le J60. `floor(log10)` mettrait 0,30 et 0,85 dans le même seau — exactement ce que PROGRESS interdisait. `floor(log2)` change de seau **quand l'ampleur double** : 0,30 et 0,35 restent silencieux, 0,85 reparle. Logarithmique donc **sans unité** : la même règle sur un taux dans [0, 1] et sur un décompte dans [0, 10⁶], donc sur n'importe quel dataset. **Conséquence de conception** : `ampleur` devient un champ de **premier rang** de l'écart et non un détail — chaque famille nomme la sienne (un taux, un ratio de doublons, un score `z`, un nombre de lignes), parce qu'elle seule sait ce qui chez elle veut dire « plus grave ». La chercher après coup dans `details` aurait demandé au lecteur de connaître un format par famille, ce que la forme commune existe pour éviter. **⭐ Le filtre rend deux listes, pas une liste amputée.** Un appelant qui ne recevrait que les écarts retenus ne pourrait pas journaliser les autres — et le garde-fou anti-cécité deviendrait un vœu pieux : l'agent se tairait progressivement, **invisible parce qu'il ne dit plus rien**. Les signatures tues sont dans le journal et dans `INCIDENTS`, réactivables d'un clic en phase 6. **Ajout au cahier assumé** : une colonne `signatures` dans `INCIDENTS`. Elles sont dérivables du JSON `anomalies`, mais seulement en Python après lecture ; les stocker rend possibles la recherche **par signature** en SQL (O7) et la liste des silences (phase 6). **⚠️ R2 change de nature pour la troisième fois** (après le top-K en 4.1.2 et les valeurs de contrat) : `past_incidents` porte le JSON complet des anomalies passées, donc potentiellement des valeurs. `resumer()` énumère champ par champ ce qui part au modèle, et un test vérifie qu'un `são paulo` planqué dans un incident passé ne franchit pas la barrière. **Le garde-fou SQL constate, il ne censure pas** : les alertes sont *attachées* au diagnostic plutôt que de l'amputer — priver l'humain du raisonnement le rendrait incapable de juger, alors même que le raisonnement reste utile quand seul le SQL est mauvais. C'est `apply` qui refusera d'exécuter : le premier informe, le second protège. **Piège évité** : `DELETE` n'est pas destructeur en soi, c'est `DELETE` **sans `WHERE`** — les confondre aurait refusé la correction la plus naturelle du projet, supprimer les doublons d'un lot. **Leçon de méthode — 4ᵉ occurrence du même piège** : `from agent.tools import write_log` rend le `StructuredTool` réexporté et non le module, d'où un `AttributeError: 'StructuredTool' object has no attribute 'serialiser'` qui ne ressemble pas à sa cause. Déjà rencontré dans `conftest.py`, `test_tools.py` et le lanceur de sous-processus. *Une commodité d'import qui coûte une erreur incompréhensible à chaque nouvelle occurrence n'est plus une commodité* — à reconsidérer si une cinquième arrive. |
| 2026-08-17 | 4 | ✅ **4.1.8 `generate_dq_rule` — le dernier tool du cahier** : `agent/tools/generate_dq_rule.py` (YAML pur) + `dbt/tests/generic/no_semantic_collisions.sql` (le test maison). **+19 tests, 551 verts.** 6 sabotages joués : **5/6 au premier tour**, 6/6 après correction. | **⭐ Le problème de conception de l'étape : faire sortir une règle SQL sans faire entrer de SQL dans `agent/`.** La collision sémantique est la seule règle du projet qu'aucun test dbt standard n'exprime — elle demande une requête, et le garde-fou du socle relit tout `agent/`. Trois issues étaient possibles : l'écrire dans le tool (refusé par le garde-fou, à raison), la mettre dans un fichier gabarit hors `.py` (le garde-fou ne la verrait plus — un contournement déguisé en solution), ou la sortir complètement de l'agent. C'est la troisième : un **test générique maison** écrit une fois à la main dans `dbt/tests/generic/`, que l'agent se contente d'appeler par son nom. La frontière est juste — le SQL qu'exécute **dbt** vit dans le projet dbt, celui qu'exécute **l'agent** derrière le connecteur, et aucun des deux n'a de raison d'habiter dans un tool. **Vérifié sur la vraie base et dans les deux sens** (un test qui ne peut pas échouer ne prouve rien) : `COLLATE(…, 'en-ci-ai')` replie bien casse **et** accents, la grappe `sao paulo`/`são paulo`/`SAO  PAULO` est attrapée, `STG_GEOLOCATION` rend **0 grappe** sur son million de lignes, et `arco verde`/`arcoverde` restent distincts — la décision 13c tient jusque dans le SQL. **⭐ L'agent propose la règle, il ne l'installe pas** : écrire directement dans `_staging.yml` reviendrait à le laisser modifier les tests qui décident si le pipeline est vert, donc changer la définition de « ça marche ». C'est exactement le raisonnement de la décision 14 sur le registre, appliqué aux critères de qualité. **⚠️ Piège de benchmark identifié maintenant plutôt qu'en phase 8** : les règles réintégrées portent `tags: [generated]` et le bras baseline devra s'exécuter avec `--exclude tag:generated` — sans quoi la baseline attraperait des anomalies **grâce à l'agent** et la comparaison mesurerait l'agent contre lui-même. **Piège évité** : `accepted_values` se construit sur `reference` (la liste signée) et non sur `observe` (les intruses) — l'inverse graverait l'anomalie comme règle. **Leçon de méthode** : le sabotage « le tri des tables disparaît » n'a **pas** été détecté au premier tour. Mon test de déterminisme n'utilisait qu'une seule table : le tri des *colonnes* le rendait vert, et le tri des *tables* n'était jamais éprouvé. *Un test de déterminisme qui ne fait varier qu'une dimension ne prouve la stabilité que de celle-là.* Corrigé par quatre tables sur trois couches, plus un test dédié à l'ordre externe. |
| 2026-08-17 | 4 | 🚧 **4.5 volet B — l'agent entre dans le DAG** : `scripts/check_layer.py`, `agent/dbt_results.py`, `agent/detect/dbt.py`, 3 tâches Airflow (8 → 11), runbook mis à jour. **+14 tests, 565 verts.** 7 sabotages joués, **7/7 détectés**. | **⭐ Une pause n'est pas un échec, et c'est LE point qui décide si le volet est utilisable.** `propose` appelle `interrupt()` : dès que l'agent trouve quelque chose, le run s'arrête en attendant un humain. Si la tâche Airflow sortait alors en erreur, **le DAG serait rouge chaque fois que l'agent fait son travail** — et un pipeline rouge en permanence est un pipeline qu'on cesse de regarder, ce qui coûte bien plus cher que l'anomalie signalée. Le code de sortie ne répond donc qu'à une question : *l'agent a-t-il pu tourner ?* Ce qu'il a trouvé se lit dans `INCIDENTS`, pas dans un code de retour. C'est exactement la convention adoptée en 2.3 pour les tests dbt (`rc=1` = détection = vert), et pour la même raison. **Choix d'architecture qui rend le volet développable sans Docker** : le DAG ne contient aucune logique — trois `BashOperator` de trois lignes, comme les huit qui existaient. Tout ce qui se raisonne vit dans `scripts/check_layer.py`, donc tout se teste sur le serveur, où Airflow n'est pas installé. La contrepartie est dite : l'**import** du DAG n'est pas vérifiable ici, seulement sa syntaxe Python. **La boucle de 4.1.8 se referme** : l'agent génère des règles dbt, dbt les exécute, et leurs échecs **reviennent** à l'agent via `agent/detect/dbt.py`. ⚠️ Cette « famille » n'en est pas une : elle ne détecte rien, elle traduit le verdict d'un outil qui a déjà tranché — mais lui donner la forme commune lui ouvre le diagnostic, la signature, la mémoire et le journal. La laisser dehors aurait réservé l'intelligence de l'agent aux anomalies qu'il trouve lui-même. **Le manifest dbt est indispensable, pas un confort** : on pourrait découper `not_null_stg_customers_customer_id`, mais rien n'y sépare le modèle de la colonne — un modèle nommé `customers_customer` rendrait le découpage ambigu **sans prévenir**. Le manifest le dit sans deviner. Et le nom de table vient du **registre** et non d'une table de schémas en dur : un dataset qui range son Silver ailleurs ne casse rien. **Rien à changer au compose** : le repo entier est déjà monté, donc `agent_checkpoints.sqlite` vit des deux côtés et `decide.py` reprend depuis l'hôte sans configuration — vérifié par lecture, avec la réserve `AIRFLOW_UID` notée dans le runbook. **Reste à exécuter sur le PC**, à grouper avec 4.6. |
| 2026-08-17 | 4 | ✅ **4.1.4 fraîcheur + 4.1.6 `run_sql` — le §5.6 est complet** : `agent/freshness.py`, `sql_guard.lecture_seule()`, `ConnecteurSnowflake.executer()`, `agent/tools/run_sql.py`. **+35 tests, 600 verts.** 8 sabotages joués, **8/8 détectés**. | **⭐ La fraîcheur ne coûte aucune requête, et c'est tout l'intérêt.** Le critère de 4.1.5 avait déjà tranché qu'une colonne `temporal` ne reçoit pas de mesure dédiée parce que ses `min`/`max` **sont** la fraîcheur ; il ne manquait que l'interprétation. Sur 40 colonnes temporelles (128 au total), une mesure dédiée aurait ajouté 40 requêtes par run. **⭐ La référence est le lot, pas l'horloge** : comparer à `now()` sur un dataset rejoué de 2018 ferait paraître tout vieux de sept ans, alors que la question utile est *ce lot contient-il ce qu'il prétend contenir ?* Effet secondaire décisif — la mesure devient **reproductible** : rejouer le J45 dans deux ans rendra le même retard, ce qu'une fraîcheur à l'horloge aurait rendu instable au benchmark. **`dates_futures` est un fait, pas un décompte** : `max` dit qu'il en existe, pas combien ; les compter demanderait la requête qu'on refuse de payer, et « il y en a » suffit à alerter tout en restant exact. **⭐ Détectable sans détecteur** : les trois mesures rejoignent `METRIQUES_COLONNE` donc `_PROFILES` donc la famille statistique — un `dates_futures` constant à 0 qui passe à 1 déclenche une `rupture_de_constante` sans qu'une ligne de détection ait été écrite pour lui. **⭐ `run_sql` : écart au plan assumé — une liste blanche, pas seulement la liste noire prévue.** Une liste noire ne protège que de ce qu'on a pensé à y mettre : `COPY INTO`, `PUT`, `CALL` écrivent sans porter aucun verbe évident, et une version future du moteur en ajoutera d'autres. La liste blanche inverse la charge — ce qui n'est pas explicitement autorisé est refusé, **y compris ce qui n'existe pas encore**. La liste noire est gardée en plus, pour ce qui se cache après un verbe autorisé (`SELECT 1; DROP TABLE x` commence bien par SELECT), et une troisième barrière refuse les instructions multiples. **⭐ On valide PUIS on se connecte** : contrôler après avoir ouvert la session laisserait une trace de connexion pour une requête interdite — et le jour où le contrôle a un trou, la requête serait déjà partie. Un test l'impose, et le sabotage inverse est détecté. **⚠️ `run_sql` est le seul endroit du projet qui rend des lignes brutes**, par nécessité — investiguer, c'est regarder des lignes. D'où la règle absolue : son résultat n'entre **jamais** dans le contexte du LLM, et son journal trace la requête et le volume mais jamais les valeurs, sinon il deviendrait une copie de la base par accumulation. **Le garde-fou n'est pas dupliqué** : `run_sql` et le futur `apply` (R4, phase 5) partagent `agent/sql_guard.py` — *une règle écrite deux fois finit par diverger, et le jour où elle diverge c'est la version la plus laxiste qui gagne.* |
| 2026-08-17 | 5 | ✅ **5.1 `propose` réel — l'impact estimé** : `agent/impact.py`, `graph.propositions_en_attente()`, `decide.py --list`. **+17 tests, 617 verts.** 7 sabotages joués, **7/7 détectés**. | **L'impact est le champ dont dépend la décision** : sans lui, l'humain n'approuve pas — *il signe*. C'est la faiblesse que `DESIGN.md` §5.3 anticipe (« et si l'humain approuve sans lire ? »), et elle ne se corrige pas par un garde-fou technique mais en donnant de quoi juger. **⭐ Aucune requête, et ce n'est pas de la paresse** : un nœud qui interrogerait la base au moment de proposer comparerait un lot mesuré tout à l'heure à une base lue maintenant — l'écart affiché ne correspondrait ni à ce qui a été détecté, ni à ce que l'humain verrait s'il regardait lui-même. Troisième application de la même règle après `detect` (4.3) et la fraîcheur (4.1.4). **⭐ Trois degrés de certitude, jamais un chiffre inventé.** `numeric_max = 8000` prouve qu'une valeur sort des bornes, **jamais combien de lignes** : l'impact rend donc « au moins 1 ligne » et non « 1 ligne ». La nuance coûte un champ ; l'omettre ferait refuser une anomalie majeure sur la foi d'un chiffre fabriqué. **⭐ On ne somme jamais les lignes** : la même ligne peut porter un null *et* un doublon, et un total dépasserait la taille du lot dès que deux écarts se recouvrent — « 420 lignes sur 351 » détruirait la confiance dans tout le reste de la proposition. L'en-tête retient le plus étendu, les autres restent listés. **Des nombres, jamais un adjectif** : « impact modéré » ne se conteste pas, « 51 lignes sur 351 (14,5 %) » se vérifie ; et une dérive se lit en variation — « 351 → 42 (−88 %) » dit en une ligne ce qu'un `z` de −9,1 ne dit à personne. Un test refuse explicitement les adjectifs dans le résumé. **⚠️ L'aval est annoncé comme non calculé, pas tu** : le « panier moyen +53,7 % » de l'exemple demande le lineage dbt, que PROGRESS place en 7.1. Un impact qui l'omettrait en silence laisserait approuver une correction déplaçant un indicateur de moitié. **Écart au plan sur la file d'attente** : la jointure prévue avec `INCIDENTS` n'a pas lieu d'être — un run en pause **n'a pas de ligne dans `INCIDENTS`**, puisqu'il n'a pas atteint `log`. La file se lit dans le checkpointer seul, via son API (`saver.list`) plutôt que par une requête sur sa base : le schéma interne de LangGraph n'est pas un contrat. **Piège coûteux attrapé** : itérer le générateur de `saver.list()` tout en appelant `get_state()` interroge la même connexion SQLite pendant qu'un curseur la consomme — **la suite de tests ne finissait jamais**, et le symptôme (un blocage) ne ressemblait pas à sa cause (un curseur). La liste est désormais matérialisée avant d'être parcourue. |
| 2026-08-17 | 5 | ✅ **5.2 — l'invariant P6, « ne jamais inventer une valeur »** : `agent/corrections.py`, refus dans `apply`, alerte dans `diagnose`, gestes montrés dans `propose`. **Preuve P4 livrée.** **+21 tests, 638 verts.** 7 sabotages joués, **7/7 détectés**. | **Le problème de conception : comment interdire l'invention sans interdire la correction du fil rouge ?** La règle naïve — « sur la colonne diagnostiquée, seul `NULL` peut être écrit » — aurait interdit `são paulo` → `sao paulo`, c'est-à-dire la correction que le projet existe pour montrer. **⭐ Le critère qui les sépare est vérifiable : la valeur écrite est-elle DÉJÀ présente dans la colonne ?** `sao paulo` y est (le top-K l'a mesurée) ; `80` n'y est pas. On ne crée rien, on choisit parmi ce qui existe. **Et le vivier est ce qui a été *observé*, jamais ce que le contrat *admet*** — un contrat dit ce qui devrait être, pas ce qui est ; écrire une valeur admise mais jamais vue resterait une invention. **Liste blanche de gestes plutôt que liste noire d'interdits** (leçon de 4.1.6) : isoler · mettre à NULL · normaliser · exclure. Ce qui ne ressemble à aucun des quatre est refusé, **y compris ce qu'on n'a pas imaginé**. **⚠️ Un refus surprend et reste le bon** : `SET city = LOWER(city)` n'invente rien, mais ce n'est pas une correction — c'est une transformation appliquée **aussi aux lignes saines**, dont la place est dans le modèle Silver où elle sera relue, versionnée et testée. *L'agent corrige des lignes ; dbt transforme des colonnes.* **⭐⭐ P4, la preuve : le refus survit à l'approbation.** Le garde-fou s'exécute **après** le « oui » humain, et c'est tout son intérêt — un humain peut approuver sans lire, et une règle qui cède devant une approbation ne protège de rien. Deux sabotages le visent (le garde-fou disparaît / la correction passe quand même) et tous deux sont détectés. **`apply` refuse mais ne lève pas** : ce n'est pas un bug de câblage mais un cas métier, et lever ferait perdre la trace du refus au moment où elle est la plus instructive — en contredisant au passage « `log` est la sortie unique ». Le message dit le **recours** (`--fix`) : un refus sans issue laisse l'humain bloqué. **⭐ P6 contraint l'agent, pas l'humain** — décision écrite dès l'en-tête d'`apply` en 3.1, tenue ici et éprouvée par un sabotage dédié : « l'agent ne peut pas savoir si 8000 valait 80 ; toi, tu peux avoir appelé le fournisseur ». Les deux autres garde-fous restent pour les deux : ils protègent de l'accident, pas du jugement. |
