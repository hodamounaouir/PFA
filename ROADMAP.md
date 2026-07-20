# Roadmap d'exécution — Plateforme de Qualité de Données Auto-Adaptative

> Compagnon opérationnel du `CAHIER_DES_CHARGES.md` v4.
> Le cahier dit **quoi** et **pourquoi**. Ce document dit **dans quel ordre** et **quand c'est fini**.

**Règle du jeu** : une phase se termine quand son *Definition of Done* est vrai — pas quand le temps imparti
est écoulé. Si une phase déborde, on coupe dans le contenu de la phase, pas dans son DoD.

---

## Vue d'ensemble

| # | Phase | Durée | Couvre | Bloquante ? |
|---|-------|-------|--------|-------------|
| 0 | Fondations & accès | 3–5 j | — | 🔴 oui |
| 1 | Jeu de données + anomalies injectées | 1 sem | L4 | 🔴 oui |
| 2 | Pipeline Medallion sans agent | 2–3 sem | O1, L1 | 🔴 oui |
| 3 | Squelette agent LangGraph (7 nœuds) | 1–2 sem | O2, L2 | 🔴 oui |
| 4 | Agent branché au pipeline + `INCIDENTS` | 2 sem | O2, O3, O7 | 🔴 oui |
| 5 | HITL complet : pause, reprise, Apply borné | 1–2 sem | O5, L6 | 🔴 oui |
| 6 | Observabilité Streamlit | 1–2 sem | O4, L3 | 🔴 démo |
| 7 | 🌟 Cause racine (lineage) puis extensions E1→E4 | 1–2 sem | O8, E* | 🟢 non |
| 8 | Benchmark chiffré | 1–2 sem | O6, L5 | 🔴 oui |
| 9 | Documentation, ADR, soutenance | 1 sem | L8, L9 | 🔴 oui |

**Total** : ~12–17 semaines.

**Point de bascule** : à la fin de la **phase 6**, tu as un projet *soutenable* (pipeline + agent +
HITL + démo à la souris). La phase 7 est du bonus. Si le temps manque, tu coupes dans 7 —
jamais dans 0→6, 8, 9.

---

## Deux écarts par rapport au planning §11 du cahier (assumés)

1. **Le jeu de données remonte en phase 1.** Raison : tu ne peux pas construire le pipeline ni tester
   l'agent sur des données qui ne contiennent pas les anomalies à trouver. Le **dataset** (L4) vient
   tôt ; le **benchmark** (L5) reste tard, en phase 8.

2. **La mémoire (O7) arrive dès la phase 4, pas en bonus.** Depuis la v4, la mémoire du noyau est une
   simple requête SQL sur `INCIDENTS` — elle coûte quelques lignes de code une fois la table créée.
   Seul le rappel **vectoriel** (E1) reste en extension.

---

## ⚠️ À régler dès maintenant : la fenêtre Snowflake

Le trial Snowflake est de **~30 jours / 400 $ de crédits** (à revérifier au moment de l'inscription).
Le projet dure **~4 mois**. Le compte va donc expirer **au milieu du projet**.

Trois options, à trancher en phase 0 et à consigner dans un ADR :
- **(a)** Compte Snowflake fourni par Tython → le régler avec l'entreprise **dès la première semaine**.
- **(b)** N'ouvrir le trial qu'en phase 2, et **ne pas le griller** en phase 0–1 (développer l'ingestion
  contre un PostgreSQL/DuckDB local, basculer sur Snowflake au dernier moment).
- **(c)** Prévoir un second compte trial en secours (accepté pour un POC, à documenter honnêtement).

Ne laisse pas ce point ouvert : une expiration en pleine phase 7 coûte une semaine.

---

# Phase 0 — Fondations & accès
**Durée** : 3–5 j · **Couvre** : rien de visible, tout le reste en dépend

### Objectif
Un dépôt qui s'installe en une commande, et tous les accès obtenus. Zéro ligne de logique métier.

### Tâches
- [ ] Créer le repo Git + structure de dossiers :
  ```
  ingestion/        # scripts Python multi-sources
  dbt/              # projet dbt (models/bronze, silver, gold)
  agent/            # graphe LangGraph, nodes, tools
  airflow/dags/     # DAGs
  streamlit/        # UI
  data/             # jeu de test généré + ground_truth.yaml
  tests/            # tests unitaires
  docs/adr/         # décisions d'architecture
  ```
- [ ] Environnement Python isolé (`uv` ou `poetry`), `requirements` figés
- [ ] Gestion des secrets : `.env` + `.env.example`, `.gitignore` vérifié
- [ ] **Trancher la question Snowflake** (voir ci-dessus) → `docs/adr/001-snowflake-access.md`
- [ ] Obtenir la clé LLM (Groq recommandé — gratuit, rapide) et valider un appel « hello world »
- [ ] Choisir **les 2 sources** de l'O1 et les figer par écrit (ex. fichiers CSV Olist + une table Olist
      exposée via API REST locale ou PostgreSQL, pour la variété des connecteurs)
- [ ] `docs/adr/008-hitl-pur-vs-scoring.md` : tracer la décision v4 (suppression du scoring — le contexte
      est encore frais, c'est maintenant qu'il faut l'écrire)
- [ ] `docs/adr/009-source-hybride-olist.md` : données réelles rejouées + injection vs génération Faker

### Definition of Done
- Un tiers clone le repo, lance `make setup`, et obtient un environnement fonctionnel.
- Un script `scripts/check_access.py` valide en une exécution : connexion Snowflake OK, appel LLM OK.
- Les 2 sources sont nommées et documentées.

### Piège
Ne pas commencer à coder l'ingestion ici. Cette phase est courte et administrative — sa valeur est de
te faire découvrir les problèmes d'accès maintenant plutôt qu'en phase 4.

---

# Phase 1 — Dataset hybride : Olist rejoué + anomalies injectées
**Durée** : 1–1,5 sem · **Couvre** : L4 · **Montage hybride (ADR 009) : données réelles, anomalies contrôlées**

### Objectif
Des batchs quotidiens **réels** (dataset Olist rejoué par date de commande) + des anomalies
**documentées et paramétrables** injectées à des jours choisis. C'est le contrat de vérité du projet :
tout ce que l'agent doit trouver d'*injecté* est défini ici — et le fil rouge sémantique
(`sao paulo`/`são paulo`) est, lui, **réellement présent dans les données**.

### Tâches
- [ ] Télécharger et explorer le dataset **Olist** (Kaggle, 9 tables réelles, ~100k commandes) ;
      sélectionner le sous-ensemble utile (`orders`, `order_items`, `order_payments`, `customers`,
      `products`, `geolocation`) et vérifier l'ampleur réelle des variantes de villes
- [ ] **Simulateur de rejeu** `data/replay.py` : découpe par `order_purchase_timestamp`, 1 jour = 1 batch ;
      fenêtre de ~90 jours figée en config ; mode plage (`--from`/`--to`) pour construire l'historique
- [ ] Injecteur d'anomalies contrôlé (modifie le batch du jour **après** rejeu — ne génère rien),
      **une classe par type**, activée par config `(jour, table, paramètres)` :
  - Dérive de schéma (colonne renommée au jour J45)
  - Complétude (nulls anormaux sur colonne critique au jour J60 — **réinjectée à J85** pour le gain mémoire)
  - Doublons (lignes dupliquées au jour J75)
  - Fichier tronqué (jour J80)
  - **Sémantique** : le cas réel `sao paulo` / `são paulo` / `sao paulo - sp` est déjà dans Olist ⭐ ;
    injection en plan B seulement s'il s'avère trop faible
- [ ] **Fichier de vérité terrain** `data/ground_truth.yaml` : pour chaque anomalie injectée →
      jour, table, colonne, type, ampleur, dimension DAMA
- [ ] Rejeu + injection **déterministes** (`--seed 42`) ; test automatique de cohérence
      `ground_truth.yaml` ↔ contenu réel des batchs

### Definition of Done
- `python -m data.replay --from J1 --to J90 --seed 42` produit des batchs **reproductibles**.
- `ground_truth.yaml` liste exhaustivement les anomalies injectées.
- Le cas `sao paulo`/`são paulo` provoque un **double comptage vérifiable** dans un agrégat par ville
  (requête témoin conservée dans `tests/`).

### Pourquoi maintenant
Le `ground_truth.yaml` est ce qui rendra le benchmark de la phase 8 calculable (précision/rappel
n'ont aucun sens sans vérité terrain). Le construire tard, c'est risquer de l'adapter inconsciemment
aux résultats de l'agent — et le benchmark ne vaut alors plus rien.

---

# Phase 2 — Pipeline Medallion sans agent
**Durée** : 2–3 sem · **Couvre** : O1, L1 · **C'est aussi la baseline du benchmark**

### Objectif
Bronze → Silver → Gold qui tourne de bout en bout sur 2 sources, orchestré par Airflow, **sans une
seule ligne d'IA**.

### Tâches
- [ ] **Ingestion** Python → Bronze : les 2 sources, chargement **brut** (pas de transformation),
      + colonnes de métadonnées (`_ingested_at`, `_source`, `_batch_id`)
- [ ] Capture de l'historique de schéma à l'ingestion → table `bronze._schema_history`
      (c'est ce que lira le tool `read_schema_history` en phase 4)
- [ ] **dbt** : init du projet, profil Snowflake, modèles Silver (nettoyage, typage, dédoublonnage)
- [ ] **dbt** : modèles Gold (agrégats métier — dont les ventes par ville du scénario)
- [ ] **dbt tests baseline** : les règles statiques classiques (`not_null`, `unique`, `accepted_values`,
      `relationships`). ⚠️ **C'est la baseline du benchmark — à figer et versionner ici.**
- [ ] **Airflow** : un DAG `medallion_pipeline` = ingest → dbt run silver → dbt test → dbt run gold → dbt test
- [ ] Vérifier que la baseline **rate bien** l'anomalie sémantique `sao paulo`/`são paulo` (c'est le point de
      départ de toute la démonstration — si elle l'attrape, le projet perd son sujet)

### Definition of Done
- `airflow dags trigger medallion_pipeline` : vert de bout en bout sur les 2 sources.
- Les 3 couches sont peuplées dans Snowflake et interrogeables.
- Les dbt tests baseline passent — **et laissent passer le fan-out `sao paulo`/`são paulo`**, prouvé par une requête.
- Le résultat des tests baseline sur `ground_truth.yaml` est archivé (`benchmarks/baseline_run.json`)
  → c'est la colonne « baseline » du tableau de la phase 8.

### Piège
Résister à l'envie d'ajouter l'agent « juste pour voir ». Cette phase doit rester une **référence propre** :
c'est contre elle que tu mesureras tout le reste.

---

# Phase 3 — Squelette agent LangGraph (7 nœuds)
**Durée** : 1–2 sem · **Couvre** : O2, L2 (partiel)

### Objectif
Le graphe tourne de START à END avec des nodes **stubs**. On valide la mécanique LangGraph (y compris
la pause/reprise), pas l'intelligence.

### Tâches
- [ ] `AgentState` (TypedDict) — copier §5.2 du cahier, y compris `logs: Annotated[list, add]`
- [ ] Les 7 nodes en version stub (valeurs codées en dur, aucun LLM sauf `Diagnose`) :
      `Profile` · `Detect` · `Diagnose` · `Propose` · `Apply` · `Validate` · `Log`
- [ ] **Conditional edges** — il y en a exactement deux :
      `Detect` → (`Diagnose` si anomalies, sinon `Log`) · `Propose` → (`Apply` si approuvé, sinon `Log`)
- [ ] **Checkpointer** (`SqliteSaver`) + `Propose` avec `interrupt()` : valider dès maintenant qu'une
      exécution **se met en pause, survit à un redémarrage du process, et reprend** avec une décision
      injectée (approbation simulée en CLI — Streamlit arrive en phase 6)
- [ ] `Diagnose` : premier vrai appel LLM (Groq) + `PydanticOutputParser` pour forcer une sortie structurée
      (`root_cause`, `proposed_fix`, `explanation`)
- [ ] Export du graphe en PNG (`graph.get_graph().draw_mermaid_png()`) → il ira dans le README et la soutenance
- [ ] Tests unitaires des nodes avec **LLM mocké** (prépare la CI de l'extension E3)

### Definition of Done
- Le graphe s'exécute de START à END sur un état factice, **sur les trois chemins** : rien d'anormal →
  Log ; anomalie + refus → Log ; anomalie + approbation → Apply → Validate → Log (3 tests).
- Une exécution interrompue sur `Propose` **reprend après redémarrage du process** (test dédié).
- **Le test de preuve P3 passe** : aucun chemin n'atteint `Apply` sans `human_decision == "approved"`.
- Le PNG du graphe est généré.

### Piège
Le LLM n'est appelé **que** dans `Diagnose` (§5.1 du cahier). Si tu te surprends à en appeler un dans
`Detect` ou ailleurs, tu casses la propriété qui rend le projet défendable : *le graphe contrôle le flux,
le LLM ne fait que raisonner*.

---

# Phase 4 — Agent branché au pipeline + table `INCIDENTS`
**Durée** : 2 sem · **Couvre** : O2 (réel), O3, O7

### Objectif
Les stubs deviennent réels. L'agent lit vraiment Snowflake, détecte vraiment, journalise vraiment —
et commence à se souvenir.

### Tâches
- [ ] **Tools LangChain** (`@tool`), un par un, chacun testé isolément :
  - `profile_table` — stats agrégées : nulls, cardinalité, distribution, top valeurs
  - `read_schema_history` — lit la table de la phase 2
  - `run_sql` — **lecture seule**, avec garde-fou anti-écriture et journalisation
  - `generate_dq_rule` — produit un dbt test (YAML) rattaché à une dimension DAMA
  - `write_log`
- [ ] `Profile` réel : appelle `profile_table` + persiste le profil du jour dans `_profiles`
- [ ] `Detect` réel, **trois familles** :
  - dérive de **schéma** (diff vs `schema_history`)
  - dérive **statistique** (z-score vs l'historique `_profiles` — volume, taux de nulls…)
  - anomalie **sémantique** (clustering de valeurs proches sur une colonne catégorielle → détecte
    `sao paulo` vs `são paulo`). ⚠️ **Le morceau le plus délicat du projet.**
  - \+ intégration des échecs `dbt test` comme anomalies déjà confirmées
- [ ] **Table `INCIDENTS`** (schéma §5.5 du cahier) + `Log` réel : une ligne par run, quel que soit le chemin
- [ ] **Mémoire (O7)** : tool `read_past_incidents` (SQL — incidents avec décision humaine uniquement)
      + injection dans le contexte de `Diagnose`
- [ ] `Diagnose` réel : le LLM reçoit **stats + métadonnées + incidents passés**, jamais les lignes brutes
- [ ] **Génération dynamique de règles** : ≥ 3 types (format, cohérence, complétude) → fichiers dbt test
      écrits sur disque
- [ ] **Airflow** : ajouter la tâche `agent_qualite` déclenchée **à chaque couche** (Bronze, Silver, Gold)

### Definition of Done
- L'agent tourne dans le DAG Airflow et produit un diagnostic sur les 3 couches.
- Il **détecte le `sao paulo`/`são paulo`** que la baseline de la phase 2 laisse passer. ⭐ *Le moment clé du projet.*
- Il génère ≥ 3 règles dbt qui, réintégrées dans dbt, **passent au vert**.
- Chaque run écrit sa ligne dans `INCIDENTS` — y compris les runs « rien d'anormal » (vérifié par requête).
- Sur une anomalie déjà tranchée par un humain, `Diagnose` **cite l'incident passé** dans son contexte.

### Piège
La détection sémantique n'a pas besoin d'être générale. Vise **la classe d'anomalies de ton
`ground_truth.yaml`**, et documente honnêtement la limite en « limites connues ». Un détecteur
modeste et lucide vaut mieux qu'un détecteur ambitieux et faux.

---

# Phase 5 — HITL complet : pause, reprise, Apply borné, Validate
**Durée** : 1–2 sem · **Couvre** : O5, L6

### Objectif
La boucle complète proposition → décision humaine → application → vérification, avec les garde-fous
structurels. C'est la deuxième jambe du projet (§2.2 du cahier) — et la partie qui impressionne un jury.

### Tâches
- [ ] `Propose` réel : construit la proposition complète — anomalie, cause, correction exacte (SQL),
      **impact estimé**, incidents similaires — puis `interrupt()`
- [ ] File des propositions en attente : lisible hors du process (via le checkpointer + `INCIDENTS`),
      pour que Streamlit (phase 6) puisse les afficher
- [ ] Reprise : injection de la décision (`approved` / `rejected` + identité du décideur + horodatage)
      → le graphe repart exactement après `Propose`
- [ ] `Apply` réel et **borné** : transaction SQL ; la requête ne peut toucher que la table diagnostiquée ;
      mots-clés destructeurs (`DROP`, `TRUNCATE`, `DELETE` sans `WHERE`…) rejetés **même après approbation**
- [ ] `Validate` réel : re-profilage de la table, comparaison de la métrique anormale avant/après ;
      échec → `validation_status = "failed_manual_review"` (pas de re-tentative automatique)
- [ ] Log enrichi : décision, décideur, horodatage, statut de validation, durée totale

### Definition of Done
- **Les 3 tests de preuve passent** (ce sont des livrables, pas de l'hygiène) :
  1. aucun chemin d'exécution n'atteint `Apply` sans `human_decision == "approved"` ;
  2. une exécution se met en pause sur `interrupt` et reprend correctement après décision ;
  3. `Apply` rejette toute requête hors table diagnostiquée ou contenant un mot-clé destructeur.
- Le scénario complet (détection → proposition → approbation CLI → application → validation → journal)
  se déroule de bout en bout sur le cas `sao paulo`/`são paulo`.
- Un refus produit un incident journalisé **sans aucune écriture** sur les données.

### Pourquoi ici
À la fin de cette phase tu as O1→O5 + O7 : le cœur complet. Il ne manque que l'interface (phase 6)
pour que ce soit démontrable à la souris.

---

# Phase 6 — Observabilité Streamlit
**Durée** : 1–2 sem · **Couvre** : O4, L3

### Objectif
Rendre visible ce que l'agent fait et pourquoi — et donner à l'humain son poste de décision. Sans cette
phase, la démo est un `print` dans un terminal.

### Tâches
- [ ] Vue **Dashboard BI** : les agrégats Gold (ventes par ville, etc.) — la valeur du pipeline lui-même,
      et l'écran où le jury *voit* les chiffres faux puis corrigés
- [ ] Vue **Incidents** : historique complet depuis `INCIDENTS` — statut, couche, table, décision, durée
- [ ] Vue **Décision** : pour un incident — anomalie, raisonnement du LLM, cause racine, correction
      proposée, impact estimé, incidents similaires passés
- [ ] Vue **Validation HITL** : les propositions en pause, le diff avant/après proposé, boutons
      Approuver / Rejeter → reprend le graphe interrompu
- [ ] Soigner le **fil rouge du §9 du cahier** : la démo de soutenance passera par ces écrans

### Definition of Done
- Le scénario §9 complet est jouable **à la souris**, sans terminal.
- Un validateur voit le diagnostic, l'impact et les antécédents avant de cliquer.
- Le clic « Approuver » débloque réellement le graphe et la correction s'applique.
- **→ Point de bascule : le projet est soutenable.**

---

# Phase 7 — 🌟 Cause racine (lineage), puis extensions
**Durée** : 1–2 sem · **Couvre** : O8, puis E1→E4 · **Bonus — coupable si retard**

### Objectif
D'abord la cause racine (le différenciant le plus rentable) ; ensuite, seulement si le temps le permet,
les extensions dans l'ordre E1 → E4.

### Tâches — cause racine (O8)
- [ ] **Lineage interne minimal** : parser `manifest.json` de dbt (le graphe de dépendances y est déjà)
- [ ] Tool `lineage_impact` : « quels modèles Gold dépendent de cette colonne Silver ? »
- [ ] Intégration dans `Diagnose` : sur une anomalie Gold, le contexte LLM contient le chemin amont →
      le diagnostic désigne la transformation responsable
- [ ] Intégration dans `Propose` : l'**impact estimé** (n tables aval) affiché au validateur
- [ ] Afficher le chemin de cause racine dans Streamlit (Bronze → Silver → Gold surligné)

### Tâches — extensions (dans l'ordre, chacune optionnelle)
- [ ] **E1 — Mémoire vectorielle** : Chroma + tool `search_past_incidents` (rappel par similarité
      sémantique ; ne stocke toujours que les incidents avec décision humaine)
- [ ] **E2 — Journalisation GitHub (MCP)** : nœud `GitHubLog` après `Log` — 1 issue par incident ;
      si GitHub est indisponible, le run **ne doit pas échouer** (file d'attente locale)
- [ ] **E3 — CI GitHub Actions** : `dbt build` + `pytest` (LLM mocké) + lint
- [ ] **E4 — Streaming** : Redpanda + producteur/consommateur → Bronze en continu, l'aval inchangé

### Definition of Done (cause racine)
- Sur le fan-out `sao paulo`/`são paulo` en Gold, l'agent désigne **la normalisation manquante en Silver**.
- La proposition affiche le nombre de tables Gold impactées.

---

# Phase 8 — Benchmark chiffré
**Durée** : 1–2 sem · **Couvre** : O6, L5 · **NON coupable**

### Objectif
Prouver la valeur. Sans cette phase, le projet est une démo technique ; avec, c'est une contribution.

### Tâches
- [ ] Harness d'exécution : même dataset, deux bras — **(a)** baseline dbt tests (figée en phase 2),
      **(b)** agent LangGraph
- [ ] Calculer contre `ground_truth.yaml` (phase 1) :
  - **Précision** — anomalies signalées réellement vraies
  - **Rappel** — anomalies réelles détectées
  - **Anomalies sémantiques détectées** — invisibles à la baseline
  - **MTTR** — détection → cause identifiée (manuel vs agent)
  - **Taux d'approbation** — propositions approuvées telles quelles par l'humain
  - **Gain mémoire** — T1 vs T2 (même anomalie, 2ᵉ passage)
- [ ] Répéter chaque run **≥ 3 fois** : un LLM n'est pas déterministe, il faut une moyenne et un écart-type
- [ ] Rédiger le rapport : tableau comparatif + synthèse + **limites**

### Definition of Done
- Amélioration mesurable sur **≥ 2 métriques** dont les anomalies sémantiques (§13 du cahier).
- Chaque chiffre est reproductible via une commande unique.
- La section « limites » est écrite et **honnête** (taille d'échantillon, non-déterminisme du LLM,
  anomalies synthétiques ≠ réelles, validateur unique).

### Piège
Un jury attaque toujours le benchmark. Le rapport doit dire lui-même où il est faible — sinon quelqu'un
d'autre le dira à ta place, et ça coûte beaucoup plus cher.

---

# Phase 9 — Documentation, ADR, soutenance
**Durée** : 1 sem · **Couvre** : L8, L9 · **NON coupable**

### Objectif
Qu'un tiers puisse reprendre le projet, et que le jury comprenne les choix.

### Tâches
- [ ] **README** : schéma d'architecture (pipeline + graphe LangGraph), installation, exécution du scénario §9
- [ ] **ADR** — un fichier par décision structurante, format contexte / options / décision / conséquences :
  - Airflow vs Dagster · LangGraph vs function calling simple · Snowflake vs DuckDB
  - Choix du LLM · **HITL pur vs scoring d'autonomie** (008 — rédigé en phase 0, relu ici)
  - *(les rédiger au fil de l'eau depuis la phase 0, pas ici — ici on ne fait que relire)*
- [ ] Section **limites connues & perspectives** (dont extensions non réalisées et OpenMetadata / E5)
- [ ] **Support de soutenance** structuré autour du **fil rouge §9** : un seul incident démontre O1→O8
- [ ] **Répéter la démo au moins 3 fois**, avec un plan B enregistré (vidéo) si le live tombe en panne

### Definition of Done
- Un tiers clone, installe, et rejoue le scénario §9 **en suivant uniquement le README**.
- Chaque décision structurante a son ADR.
- La démo tient dans le temps imparti, testée en conditions réelles.

---

## Ce qu'il faut protéger si le temps manque

Dans l'ordre où on sacrifie :

1. **E4** (streaming) — c'est le premier luxe
2. **E2 + E3** (GitHub MCP, CI) — remplaçables par le journal `INCIDENTS` + un `pytest` lancé à la main
3. **E1** (mémoire vectorielle) — la mémoire SQL du noyau démontre déjà O7
4. **Phase 7 / cause racine** — en dernier recours ; la proposition perd l'impact estimé, à documenter
5. Réduire la **phase 6** à deux écrans (Décision + Validation)

**Jamais sacrifiables** : 0 → 6, 8, 9. Un projet sans benchmark (8) ou sans doc (9) perd plus de
points qu'un projet sans extension.
