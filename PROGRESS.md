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

---

## Tableau de bord

| Phase | Titre | Durée estimée | Statut |
|:-:|-------|:-:|:-:|
| 0 | Fondations & accès | 3–5 j | 🚧 en cours |
| 1 | Dataset hybride : Olist + rejeu + injection | 1–1,5 sem | ⬜ |
| 2 | Pipeline Medallion sans agent (baseline) | 2–3 sem | ⬜ |
| 3 | Squelette agent LangGraph (7 nœuds) | 1–2 sem | ⬜ |
| 4 | Agent réel + table `INCIDENTS` | 2 sem | ⬜ |
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
- [ ] Créer le repo Git ; structure de dossiers :
  ```
  ingestion/  dbt/  agent/  airflow/dags/  streamlit/  data/  benchmarks/  scripts/  tests/  docs/adr/
  ```
- [ ] Environnement Python isolé (`uv init` puis `uv add ...`), versions figées (`uv.lock` commité)
- [ ] `Makefile` : cibles `setup`, `test`, `lint`, `check`
- [ ] `.gitignore` : `.env`, `data/*.csv`, `dbt/target/`, checkpoints SQLite, `.venv/`
- [ ] `.env.example` commité (clés sans valeurs) ; `cp .env.example .env` en local

### 0.2 Accès externes
- [ ] **Snowflake** : trancher la question du trial (compte Tython ? trial différé ? second trial de secours ?)
      → consigner dans `docs/adr/001-snowflake-access.md`
- [ ] Créer la base + les schémas : `RAW` (bronze), `STAGING` (silver), `MARTS` (gold), `OPS` (tables techniques)
- [ ] **LLM** : créer la clé Groq (gratuite), valider un appel « hello world » depuis Python
- [ ] **Kaggle** : compte + `kaggle.json` pour télécharger Olist en ligne de commande
- [ ] Écrire `scripts/check_access.py` : teste Snowflake + LLM en une exécution, sortie ✅/❌ par service

### 0.3 Décisions à tracer maintenant
- [ ] `docs/adr/008-hitl-pur-vs-scoring.md` — la décision v4 (contexte encore frais)
- [ ] `docs/adr/009-source-hybride-olist.md` — données réelles rejouées + injection vs génération Faker
- [ ] Figer par écrit les **2 sources** de l'objectif O1 : (1) fichiers Olist (CSV), (2) une table Olist
      exposée via API REST locale ou PostgreSQL (pour la variété des connecteurs)

**☑ Phase terminée quand** : un tiers clone le repo, lance `make setup`, et `python scripts/check_access.py`
est tout vert ; les ADR 001/008/009 existent.

---

# Phase 1 — Dataset hybride : Olist + rejeu + injection

**Objectif** : des batchs quotidiens **réels** (Olist rejoué par date) + des anomalies **contrôlées et
documentées** (`ground_truth.yaml`). C'est le contrat de vérité du projet.

### 1.1 Acquisition & exploration d'Olist
- [ ] Télécharger le dataset Olist (Kaggle, ~120 Mo, 9 fichiers CSV)
- [ ] Explorer et documenter les 9 tables (notebook jetable ou `docs/dataset.md`) : clés, volumes,
      plages de dates, taux de nulls naturels
- [ ] Sélectionner le **sous-ensemble utile** (recommandé : `orders`, `order_items`, `order_payments`,
      `customers`, `products`, `geolocation`) — noter ce qu'on écarte et pourquoi
- [ ] **Vérifier le cas sémantique réel** : requête sur `geolocation_city` → confirmer les variantes
      (`são paulo` / `sao paulo` / `sao paulo - sp`…) et mesurer leur ampleur. C'est le futur fil rouge ;
      s'il est trop faible, le plan B est l'injection (1.3)

### 1.2 Simulateur de rejeu (`data/replay.py`)
- [ ] Découper les données par **date de commande** (`order_purchase_timestamp`) : 1 jour = 1 batch
- [ ] CLI : `python -m data.replay --day 2017-03-15` → écrit les fichiers du jour dans `data/incoming/`
      (le dossier que l'ingestion lira)
- [ ] Mode rattrapage : `--from ... --to ...` pour rejouer une plage (utile pour construire l'historique
      des profils vite)
- [ ] Choisir la **fenêtre de rejeu** du projet (recommandé : ~90 jours dans une période dense de 2017-2018)
      et la figer dans la config
- [ ] Les tables de référence (produits, clients) sont livrées au jour 1 puis en delta

### 1.3 Injecteur d'anomalies (`data/inject.py`)
- [ ] Architecture : une classe par type d'anomalie, activée par config `(jour, table, paramètres)` —
      l'injecteur **modifie le batch du jour après rejeu**, il ne génère rien
- [ ] Types à implémenter :
  - [ ] **Dérive de schéma** : renommage de colonne (ex. `payment_value` → `amount` au jour J45)
  - [ ] **Complétude** : passage à N % de nulls sur une colonne critique (ex. `customer_id` au jour J60)
  - [ ] **Doublons** : duplication de X % des lignes d'un batch (jour J75)
  - [ ] **Fichier tronqué** : batch coupé à 30 % de son volume (jour J80)
  - [ ] **Sémantique (plan B)** : introduction de variantes de casse sur une colonne catégorielle —
        seulement si le cas réel `sao paulo` (1.1) s'avère insuffisant
- [ ] **Récidive** : la même anomalie de complétude est réinjectée à J60 **et** J85 → c'est ce qui
      permettra de mesurer le gain mémoire (T1 vs T2) en phase 8
- [ ] `data/ground_truth.yaml` : pour chaque anomalie → jour, table, colonne, type, ampleur, dimension
      DAMA. **Écrit ici, jamais modifié après que l'agent tourne** (honnêteté du benchmark)

### 1.4 Verrous méthodologiques
- [ ] Rejeu + injection **déterministes** (`--seed 42` pour les choix aléatoires de lignes) : deux
      exécutions produisent exactement les mêmes batchs
- [ ] Test automatique : `ground_truth.yaml` et les anomalies effectivement présentes dans les fichiers
      coïncident (compteur par type)
- [ ] Vérifier que le cas sémantique provoque un **double comptage mesurable** dans un agrégat par ville
      (requête témoin conservée dans `tests/`)

**☑ Phase terminée quand** : `replay --from J1 --to J90` + injection produisent des batchs reproductibles ;
`ground_truth.yaml` est exhaustif ; le double comptage est prouvé par une requête.

---

# Phase 2 — Pipeline Medallion sans agent (baseline)

**Objectif** : Bronze → Silver → Gold de bout en bout, orchestré par Airflow, **sans une ligne d'IA**.
C'est aussi la **baseline du benchmark** — à figer.

### 2.1 Ingestion → Bronze
- [ ] `ingestion/load.py` : lit `data/incoming/`, charge **brut** dans Snowflake `RAW` (aucune
      transformation, aucun rejet)
- [ ] Métadonnées sur chaque ligne : `_ingested_at`, `_source`, `_batch_id`
- [ ] **Idempotence** : recharger le même batch ne duplique rien (clé sur `_batch_id`)
- [ ] Capture du schéma observé à chaque ingestion → table `OPS._SCHEMA_HISTORY`
      (nom des colonnes, types, ordre — c'est ce que lira `read_schema_history` en phase 4)

### 2.2 dbt : Silver puis Gold
- [ ] `dbt init` + profil Snowflake ; conventions de nommage (`stg_`, `fct_`, `dim_`)
- [ ] Modèles **Silver** : typage, dédoublonnage, normalisation *volontairement incomplète* —
      la casse des villes n'est **pas** normalisée (c'est le trou que l'agent doit trouver)
- [ ] Modèles **Gold** : ventes par jour, ventes par ville/état, délais de livraison, panier moyen
- [ ] **dbt tests baseline** : `not_null`, `unique`, `relationships`, `accepted_values` — les règles
      qu'un data engineer écrirait naturellement. **Figées et versionnées ici** (colonne « baseline » du
      benchmark)
- [ ] Vérifier par requête que la baseline **rate** le fan-out `sao paulo` (si elle l'attrape, le projet
      perd son sujet — ajuster les tests baseline en le documentant)

### 2.3 Orchestration Airflow
- [ ] Airflow en local (Docker Compose)
- [ ] DAG `medallion_pipeline` : `replay+inject` → `ingest_bronze` → `dbt run` (silver) → `dbt test` →
      `dbt run` (gold) → `dbt test` — paramétré par le jour rejoué
- [ ] Backfill des ~30 premiers jours (sans anomalie injectée) → construit l'historique dont `Detect`
      aura besoin
- [ ] Archiver le résultat des tests baseline confronté à `ground_truth.yaml` → `benchmarks/baseline_run.json`

**☑ Phase terminée quand** : le DAG est vert de bout en bout sur la fenêtre rejouée ; les 3 couches sont
peuplées et interrogeables ; la baseline rate le cas sémantique (prouvé) ; `baseline_run.json` est archivé.

---

# Phase 3 — Squelette agent LangGraph (7 nœuds)

**Objectif** : le graphe tourne de START à END avec des stubs ; la mécanique **pause/reprise** est validée.
On teste la tuyauterie, pas l'intelligence.

### 3.1 Le graphe
- [ ] `agent/state.py` : `AgentState` (TypedDict) — copier §5.2 du cahier, dont `logs: Annotated[list, add]`
- [ ] `agent/nodes/` : les 7 nœuds en stub (valeurs en dur) : `profile`, `detect`, `diagnose`,
      `propose`, `apply`, `validate`, `log`
- [ ] `agent/graph.py` : assemblage + les **2 conditional edges** :
      `detect → (diagnose | log)` et `propose → (apply | log)`
- [ ] Export PNG du graphe (`draw_mermaid_png()`) → `docs/img/agent_graph.png` (README + soutenance)

### 3.2 Pause & reprise (le mécanisme critique)
- [ ] Checkpointer `SqliteSaver` branché à la compilation
- [ ] `propose` appelle `interrupt()` avec la proposition (stub) comme payload
- [ ] Script CLI `scripts/decide.py <thread_id> approve|reject` : injecte la décision
      (`Command(resume=...)`) → le graphe reprend
- [ ] **Test clé** : lancer un run → interruption → **tuer le process** → relancer → la décision reprend
      le graphe exactement après `propose`

### 3.3 Premier vrai appel LLM
- [ ] `diagnose` : appel Groq réel + `PydanticOutputParser` → sortie forcée
      `{root_cause, proposed_fix, explanation}`
- [ ] Gestion d'échec de parsing : l'état porte `diagnosis = None` → le run se termine en
      « à traiter manuellement » (pas d'exception qui tue le graphe)

### 3.4 Tests
- [ ] Les 3 chemins du graphe (rien d'anormal / refusé / approuvé) — 3 tests, LLM mocké
- [ ] **Test de preuve P3** : instrumenter `apply` → prouver qu'aucune exécution ne l'atteint sans
      `human_decision == "approved"` (parcours exhaustif des chemins)
- [ ] Test pause/reprise après redémarrage du process

**☑ Phase terminée quand** : les 3 chemins passent en test ; la reprise post-redémarrage marche ; le test
de preuve P3 passe ; le PNG du graphe est généré.

---

# Phase 4 — Agent réel + table `INCIDENTS`

**Objectif** : les stubs deviennent réels — l'agent lit vraiment Snowflake, détecte vraiment, journalise
vraiment, et commence à se souvenir.

### 4.1 Les tools (un par un, testés isolément)
- [ ] `profile_table` : volumes, taux de nulls par colonne, cardinalités, min/max/moyenne, top-K valeurs,
      fraîcheur — en SQL agrégé uniquement
- [ ] `read_schema_history` : lit `OPS._SCHEMA_HISTORY`
- [ ] `run_sql` : **lecture seule** — rejet par liste de mots-clés d'écriture + journalisation de chaque requête
- [ ] `generate_dq_rule` : produit un dbt test YAML rattaché à une dimension DAMA
- [ ] `write_log` : écrit dans `OPS.INCIDENTS`

### 4.2 Profile & Detect réels
- [ ] `profile` : appelle `profile_table` + **persiste le profil du jour** dans `OPS._PROFILES`
- [ ] `detect` — quatre familles, toutes déterministes :
  - [ ] dérive de **schéma** : diff du schéma du jour vs `_SCHEMA_HISTORY`
  - [ ] dérive **statistique** : z-score du profil du jour vs moyenne/écart-type des N derniers jours
        (`_PROFILES`) — volume, taux de nulls, cardinalité
  - [ ] candidats **sémantiques** : normalisation (casse/accents/espaces) des top-K valeurs
        catégorielles → clusters de collision (attrape `sao paulo` / `são paulo`)
  - [ ] intégration des **échecs dbt test** du run comme anomalies déjà confirmées
- [ ] Seuils de détection dans un petit fichier de config (`agent/config.py`) — ce sont des réglages de
      détection, pas des règles de décision (la décision, c'est l'humain)

### 4.3 La table `INCIDENTS` et la mémoire
- [ ] DDL `OPS.INCIDENTS` (schéma §5.5 du cahier) — append-only
- [ ] `log` réel : une ligne par run, **quel que soit le chemin** (y compris « rien d'anormal »)
- [ ] Tool `read_past_incidents` : SQL sur `INCIDENTS` — filtre `human_decision IS NOT NULL` (R5),
      match par table + type d'anomalie
- [ ] `diagnose` réel : prompt = profil + anomalies + métadonnées + incidents passés ; sortie parsée
      Pydantic ; garde-fou sur le SQL proposé (table concernée uniquement, pas de mot-clé destructeur —
      première ligne de défense, `apply` re-vérifiera)

### 4.4 Règles dynamiques & branchement Airflow
- [ ] ≥ 3 règles dbt générées (format, complétude, cohérence) écrites sur disque et **vertes** une fois
      réintégrées dans dbt
- [ ] Tâches Airflow `check_bronze` / `check_silver` / `check_gold` : invoquent l'agent avec
      `(layer, table, batch_id)` après chaque couche

### 4.5 Validation sur les anomalies réelles
- [ ] Rejouer la fenêtre avec injections : l'agent détecte le renommage (J45), les nulls (J60), les
      doublons (J75), la troncature (J80)
- [ ] **Le moment clé** ⭐ : l'agent signale le cluster `sao paulo` que la baseline rate
- [ ] Sur la récidive (J85) : `diagnose` **cite l'incident de J60** dans son contexte

**☑ Phase terminée quand** : l'agent tourne dans le DAG sur les 3 couches ; il détecte les 4 anomalies
injectées + le cas sémantique réel ; chaque run a sa ligne `INCIDENTS` ; la récidive est reconnue.

---

# Phase 5 — HITL complet : pause, reprise, Apply borné

**Objectif** : la boucle complète proposition → décision humaine → application → vérification, avec les
garde-fous structurels. La deuxième jambe du projet.

### 5.1 Propose réel
- [ ] Construction de la proposition complète : anomalie, cause diagnostiquée, **SQL exact** de la
      correction, impact estimé, incidents similaires passés
- [ ] `interrupt()` avec la proposition en payload ; état persisté (checkpointer)
- [ ] File des propositions en attente lisible **hors process** (jointure checkpointer ↔ `INCIDENTS`) —
      c'est ce que Streamlit affichera en phase 6

### 5.2 Reprise & Apply borné
- [ ] Injection de la décision : `approved` / `rejected` + **identité du décideur + horodatage** →
      stockés dans `INCIDENTS`
- [ ] `apply` réel : transaction SQL ; vérifications **même après approbation** :
  - [ ] la requête ne touche que la table diagnostiquée
  - [ ] rejet des mots-clés destructeurs (`DROP`, `TRUNCATE`, `DELETE` sans `WHERE`…)
  - [ ] comptage lignes affectées avant/après conservé dans le log
- [ ] `validate` réel : re-profilage → la métrique anormale est-elle revenue dans la normale ?
      échec → `validation_status = "failed_manual_review"`, **pas de re-tentative automatique**

### 5.3 Les 3 tests de preuve (livrables, pas hygiène)
- [ ] **P3** : aucun chemin vers `apply` sans `human_decision == "approved"`
- [ ] **Pause/reprise** : interruption + redémarrage du process + reprise correcte
- [ ] **Apply borné** : requête hors table → rejet ; mot-clé destructeur → rejet

### 5.4 Bout en bout
- [ ] Scénario complet sur le cas sémantique : détection → diagnostic → proposition → approbation (CLI) →
      application (`UPPER` / normalisation ville en Silver) → validation → journal
- [ ] Scénario refus : l'incident est journalisé, **aucune écriture** sur les données (vérifié)

**☑ Phase terminée quand** : les 3 tests de preuve passent ; les deux scénarios bout en bout (approbation
et refus) se déroulent sans terminal ouvert sur Snowflake.

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
- [ ] **Validation HITL** : propositions en pause, diff avant/après estimé, boutons
      **✅ Approuver / ❌ Refuser** → reprend réellement le graphe interrompu

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
- [ ] **Précision** et **rappel** (vs `ground_truth.yaml`)
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
- [ ] Relire tous les ADR (001 → 009) — ils ont été écrits au fil de l'eau, ici on ne fait que relire
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
|  |  |  |  |
