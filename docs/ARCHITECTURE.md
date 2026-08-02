# Architecture

> **Ce document décrit *comment le système est structuré*** — composants, flux, responsabilités.
>
> - Le **quoi** et le **pourquoi fonctionnel** : [`CAHIER_DES_CHARGES.md`](../CAHIER_DES_CHARGES.md) (v4)
> - Le **pourquoi technique** et les arbitrages : [`DESIGN.md`](DESIGN.md)
> - L'**ordre de construction** : [`ROADMAP.md`](../ROADMAP.md)

**Statut** : architecture cible. Le projet est en phase 0 — voir l'[avancement](../README.md#avancement).

---

## 1. Principes directeurs

Six invariants. Tout le reste en découle, et **aucun n'est négociable** — une PR qui en casse un est
refusée, quelle que soit sa valeur par ailleurs.

| # | Principe | Conséquence concrète |
|---|----------|----------------------|
| **P1** | **Le graphe contrôle le flux, le LLM ne fait que raisonner** | Le LLM n'est appelé **que** dans `Diagnose`. Le routage et les décisions sont du code déterministe et testable. |
| **P2** | **Le LLM ne voit jamais les données brutes** | Il reçoit des **statistiques agrégées et des métadonnées**. L'accès aux échantillons passe par un tool en lecture seule, journalisé et masquable. |
| **P3** | **Aucune correction sans validation humaine** | Le graphe ne contient **aucun chemin** `Diagnose → Apply` : la seule arête entrante d'`Apply` vient de `Propose` avec `human_decision == "approved"`. La branche `amend_contract` n'y mène pas non plus. Prouvé par test. |
| **P4** | **`Apply` est borné, même après approbation** | Transaction SQL, table diagnostiquée uniquement, mots-clés destructeurs rejetés, `Validate` systématique après coup. |
| **P5** | **Le journal est append-only et complet** | `logs: Annotated[list, add]` + une ligne dans `INCIDENTS` pour **chaque** run, y compris « rien d'anormal » et « refusé ». `Log` est le **seul** nœud relié à END : la complétude du journal est topologique. |
| **P6** | **L'agent n'invente jamais une valeur** *(2026-07-28)* | Il peut isoler, mettre à NULL, exclure d'un agrégat — jamais deviner (`8000` → `80`). Une correction qui substitue une valeur devinée est rejetée par `Apply` **même après approbation humaine**. Contraint l'agent, pas l'humain (voir §6). |

---

## 2. Vue d'ensemble

```
┌─ Source ────────────────────────────────────────────┐
│  Rejeu Olist (dataset réel, 1 batch/jour)           │
│  + injection contrôlée d'anomalies                  │
│  (ground_truth.yaml — jamais lu par l'agent)        │
└───────────────────────┬─────────────────────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │ Ingestion Python │  brut + métadonnées, zéro transformation
              └────────┬─────────┘
                       ▼
   ╔═══════════════════════════════════════════════════╗
   ║                  SNOWFLAKE                        ║
   ║                                                   ║
   ║   BRONZE ──dbt──► SILVER ──dbt──► GOLD            ║
   ║   (brut)         (nettoyé)      (agrégats)        ║
   ║      │                                            ║
   ║      ├─ _schema_history (historique des schémas)  ║
   ║      ├─ _profiles (profils quotidiens des tables) ║
   ║      └─ INCIDENTS (journal + mémoire de l'agent)  ║
   ╚═══════════════════════════════════════════════════╝
                       ▲
                       │ lecture (profiling, SQL, INCIDENTS)
                       │ écriture : INCIDENTS toujours ;
                       │ correction uniquement après approbation humaine
                       │
   ┌───────────────────┴───────────────────────────────┐
   │            AGENT QUALITÉ (LangGraph)              │
   │                                                   │
   │  Profile ► Detect ► Diagnose(LLM) ► Propose ⏸     │
   │                       ► Apply ► Validate ► Log    │
   │                       └─ ou ► Amend ► Log         │
   │                                                   │
   │  Diagnose intègre : mémoire (INCIDENTS)           │
   │                     + cause racine (lineage dbt)  │
   │  Contrats : contracts/<table>.vN.yaml             │
   │  Persistance : Checkpointer (SqliteSaver)         │
   └────────────────────┬──────────────────────────────┘
                        │
                        ▼
                 ┌────────────────────────────┐
                 │ Streamlit                  │
                 │  dashboard BI (Gold)       │
                 │  historique incidents      │
                 │  validation HITL ✅ / ❌   │
                 └────────────────────────────┘

  ▲ Le tout orchestré par AIRFLOW : l'agent est déclenché à chaque couche.

  Extensions (hors noyau) : Chroma (RAG vectoriel) · GitHub via MCP (audit externe)
  · Kafka/Redpanda (streaming) — voir CAHIER_DES_CHARGES §3.3.
```

---

## 3. Composants

| Composant | Répertoire | Responsabilité | Ne fait **pas** |
|-----------|-----------|----------------|-----------------|
| **Rejeu + injection** | `data/` | Rejouer le dataset réel Olist jour par jour + injecter les anomalies documentées (`ground_truth.yaml`) | Ne génère rien ; n'est jamais lu par l'agent |
| **Ingestion** | `ingestion/` | Charger les sources en Bronze, brut, + métadonnées. Capturer l'historique de schéma. | Aucune transformation, aucun nettoyage |
| **dbt** | `dbt/` | Bronze → Silver → Gold. Exécuter les tests (statiques **et** générés par l'agent). | Aucune décision, aucune IA |
| **Agent** | `agent/` | Profiler, détecter, diagnostiquer, proposer, appliquer (si approuvé), vérifier, journaliser. | N'applique **jamais** sans approbation humaine |
| **Airflow** | `airflow/dags/` | Orchestrer : ingest → dbt → agent, à chaque couche. | Ne contient aucune logique métier |
| **Streamlit** | `streamlit/` | Rendre visible : BI, incidents, raisonnement. Recueillir la validation HITL. | Ne calcule rien — il affiche et débloque |
| **Table `INCIDENTS`** | Snowflake | Journal auditable + mémoire de l'agent + source du benchmark | N'est pas un cache : append-only |

---

## 4. Les couches Medallion

| Couche | Contenu | Rôle de l'agent |
|--------|---------|-----------------|
| **Bronze** | Ingestion brute, multi-sources, immuable | Détecte les dérives de schéma → **signale ou propose de bloquer** |
| **Silver** | Nettoyage, typage, dédoublonnage (dbt) | **Génère les règles manquantes** selon le profil observé |
| **Gold** | Agrégats métier (BI/ML) | Vérifie la **cohérence sémantique inter-tables** avant publication |

### Métadonnées d'ingestion

Chaque table Bronze porte des colonnes techniques, ajoutées par l'ingestion :

| Colonne | Rôle |
|---------|------|
| `_ingested_at` | Horodatage du chargement |
| `_source` | Identifiant de la source |
| `_batch_id` | Lot de chargement — permet de rejouer et d'isoler une livraison |

### `bronze._schema_history`

Table pivot du caractère auto-adaptatif. À chaque ingestion, le schéma observé est capturé.

C'est elle que lit le tool `read_schema_history`, et c'est le **diff entre deux livraisons** qui donne
la détection de dérive de schéma. Sans cette table, `Detect` n'a aucune référence temporelle et l'agent
ne peut rien dire de « ce qui a changé ».

### `_profiles`

À chaque run, `Profile` persiste le profil statistique du jour. `Detect` compare le profil courant à
l'historique de cette table (moyenne / écart-type sur N jours). Les premiers jours, sans historique,
`Detect` reste muet — l'agent doit « apprendre le normal » avant de détecter, c'est assumé.

### `INCIDENTS`

Une ligne par exécution de l'agent :

```
incident_id · run_ts · layer · table · batch_id · anomalies (JSON) ·
diagnosis (JSON) · proposed_fix (JSON) · human_decision · decided_by · decided_at ·
validation_status · duration_s
```

Trois rôles : **journal auditable** (relu dans Streamlit), **mémoire** (lue par `Diagnose` — uniquement
les incidents ayant reçu une décision humaine), **source du benchmark** (MTTR, taux d'approbation).

---

## 5. L'agent

### 5.1 État partagé

L'état circule entre les nodes. Un node lit l'état, retourne un état enrichi — il n'écrit nulle part
ailleurs.

Implémenté dans [`agent/state.py`](../agent/state.py) ; spécification complète et commentée au §5.2 du
[cahier des charges](../CAHIER_DES_CHARGES.md).

```python
class AgentState(TypedDict):
    dataset: str                      # nom du registre datasets/<dataset>.yaml
    layer: str                        # bronze | silver | gold (contexte Airflow)
    table: str
    batch_id: str
    contract: dict                    # contracts/<table>.yaml — « ce qui devrait être vrai »
    contract_version: Optional[str]   # "v1", "v2"… ; None si pas encore de contrat
    schema_history: list
    profile: dict                     # ← Profile
    anomalies: list                   # ← Detect
    past_incidents: list              # ← lus dans INCIDENTS (mémoire)
    diagnosis: Optional[dict]         # ← Diagnose (LLM) : root_cause, proposed_fix, explanation
    human_decision: Optional[str]     # ← Propose : "approved" | "amend_contract" | "rejected"
    decided_by: Optional[str]         # qui a tranché
    decided_at: Optional[str]         # quand (ISO 8601)
    fix_override: Optional[str]       # la correction réécrite par l'humain, si différente
    applied_fix: Optional[str]        # celle qui a réellement tourné
    validation: Optional[dict]        # ← Validate : success | failed_manual_review
    logs: Annotated[list, add]        # append-only
```

Détail structurant : **`logs: Annotated[list, add]`** — le réducteur `add` rend le journal *append-only
par construction*. Un node ne peut pas réécrire l'histoire, même par erreur (P5).

### 5.2 Les nodes

Huit nodes, câblés dans [`agent/graph.py`](../agent/graph.py).

| Node | LLM ? | Rôle |
|------|:-----:|------|
| `Profile` | ❌ | Statistiques agrégées via `profile_table` ; persiste dans `_profiles` |
| `Detect` | ❌ | Dérive de schéma (diff) + **violation de contrat** + dérives statistiques (médiane/MAD vs historique) + collisions sémantiques + échecs dbt test |
| `Diagnose` | ✅ | **Le seul appel LLM.** Stats + métadonnées + lineage dbt + incidents passés → diagnostic structuré (cause, correction proposée, explication) |
| `Propose` | ❌ | `interrupt()` — met le graphe en pause, attend la décision humaine (Streamlit). **3 issues** : `approved`, `amend_contract`, `rejected` |
| `Apply` | ❌ | Écrit dans les **données** — uniquement si `human_decision == "approved"`, en transaction, table diagnostiquée seulement |
| `Amend` | ❌ | Écrit dans le **contrat** (v1 → v2) — la donnée était juste, c'est la règle qui a vieilli. **N'écrit rien dans les données** |
| `Validate` | ❌ | Re-profile la table : l'anomalie a-t-elle disparu ? Échec → « à traiter manuellement » |
| `Log` | ❌ | Une ligne dans `INCIDENTS`, quel que soit le chemin parcouru. **Sortie unique du graphe** |

**Un seul node appelle le LLM.** C'est la propriété qui rend le système testable : les sept autres sont
du code déterministe, couverts par des tests unitaires sans mock.

**Un seul node écrit dans les données** — `Apply`, un sur huit. `Amend` écrit lui aussi, mais dans un
fichier de contrat versionné dans git, jamais dans une table. Les six autres lisent, mesurent,
raisonnent ou journalisent.

### 5.2 bis — Les deux arêtes conditionnelles

Ce sont les deux seules décisions de parcours du graphe, et elles sont du code déterministe :

| Arête | Fonction | Branches |
|-------|----------|----------|
| après `Detect` | `route_after_detect` | `anomalies` → `Diagnose` · `rien d'anormal` → `Log` |
| après `Propose` | `route_after_propose` | `approved` → `Apply` · `amend_contract` → `Amend` · `rejected` → `Log` · `sans décision` → `Log` |

Le défaut de `route_after_propose` est **`Log`, jamais `Apply`** : une décision absente, mal orthographiée
ou inventée par un client mal écrit retombe sur le journal. Un run qui finit à tort en « rien fait » se
rattrape ; une écriture faite à tort, non.

### 5.3 Les tools

Exposés au graphe via `@tool` (LangChain) :

| Tool | Accès | Garde-fou |
|------|-------|-----------|
| `profile_table` | lecture | Agrégats uniquement |
| `read_schema_history` | lecture | — |
| `run_sql` | **lecture seule** | Rejet des mots-clés d'écriture + journalisation systématique |
| `generate_dq_rule` | écriture fichier | Produit un dbt test YAML rattaché à une dimension DAMA |
| `lineage_impact` | lecture | Parse le `manifest.json` de dbt |
| `read_past_incidents` | lecture | Ne retourne que les incidents **ayant reçu une décision humaine** |
| `write_log` | écriture | Append-only |

---

## 6. Le contrôle humain (HITL)

Il n'y a **pas de niveau d'autonomie** : 100 % des corrections passent par un humain. La garantie tient
en trois mécanismes :

1. **Topologie du graphe** (P3) — `Apply` n'est atteignable que depuis `Propose` approuvé. Il n'existe
   pas de branche automatique : la question « dans quels cas l'agent agit-il seul ? » a une réponse
   structurelle — jamais.
2. **La pause est réelle** — `Propose` appelle `interrupt()` ; l'état est persisté par le **checkpointer**
   (`SqliteSaver`). Le processus peut mourir, la machine redémarrer : la proposition attend. Quand un
   humain clique « Approuver » dans Streamlit, le graphe **reprend là où il s'était arrêté**.
3. **La décision est éclairée** — la proposition affichée contient l'anomalie, la cause diagnostiquée, la
   correction exacte, l'impact estimé (tables aval via lineage) et les incidents similaires passés.
   Approuver n'est pas un acte de foi.

### Les deux « non » ne sont pas le même non

L'humain a **trois** réponses, pas deux. La distinction entre les deux refus est ce qui empêche le
contrat de vieillir :

| Réponse | Ce que ça veut dire | Effet |
|---------|---------------------|-------|
| `approved` | la donnée est fausse | `Apply` corrige les données |
| `amend_contract` | *« c'est normal et ça le restera »* — la donnée est juste, la règle a vieilli | `Amend` passe le contrat en v2 ; **aucune écriture sur les données** |
| `rejected` | *« exceptionnel, rien à changer »* | `Log` seul ; la signature est mise en silence, la règle est conservée |

Confondre les deux ferait soit vieillir le contrat (il crie à chaque évolution normale du métier,
l'équipe s'habitue à ignorer les alertes, l'agent meurt), soit rendre l'agent aveugle (une règle
amendée à tort le fait taire sur une vraie anomalie — silencieusement).

Garde-fou anti-cécité : rien n'est supprimé, tout est en base. La liste des signatures en silence est
requêtable, affichée dans Streamlit, et **réactivable d'un clic**.

### Ce qui contraint l'agent mais pas l'humain

P6 (« ne jamais inventer une valeur ») s'applique à l'agent seul. Il ne peut pas savoir si `8000` valait
`80` ; l'humain, lui, peut avoir appelé le fournisseur. L'humain a l'autorité pour affirmer une valeur —
via `fix_override`, qui trace que la correction appliquée n'était pas celle proposée. Les garde-fous P4
(table unique, mots-clés destructeurs) restent actifs dans les deux cas : ils protègent contre
l'accident, pas contre le jugement.

Ce qui est **testé** (les preuves, pas de simples tests d'hygiène) :

- **P3** — aucun chemin d'exécution n'atteint `Apply` sans `human_decision == "approved"` ; la branche
  `amend_contract` n'y mène pas.
- **P4** — une proposition qui substitue une valeur devinée est rejetée par `Apply` même approuvée.
- Une exécution se met en pause sur `interrupt` et reprend correctement après décision.
- `Apply` refuse toute requête hors de la table diagnostiquée (et les mots-clés destructeurs).
- Après `amend_contract`, **aucune ligne de données n'a bougé** (comptage avant/après).
- Les quatre chemins du graphe passent tous par `Log` avant END.

---

## 7. Flux d'une exécution

```
Airflow déclenche agent_qualite(layer, table, batch_id)
   │
   ├─ Profile ......... profile_table → stats agrégées → _profiles
   ├─ Detect .......... diff schéma + z-score vs historique + clustering sémantique
   │                    + échecs dbt test → anomalies
   │
   ├─ (aucune anomalie) ──────────────────────────────► Log ──► END
   │
   ├─ Diagnose ........ LLM(stats + métadonnées + lineage + incidents passés)
   │                    └─ PydanticOutputParser → cause, correction, explication
   ├─ Propose ......... interrupt() ⏸  … l'humain décide dans Streamlit … ▶ reprise
   │
   ├─ (rejected) ─────────────────────────────────────► Log ──► END
   │
   ├─ (amend_contract) ─► Amend ─ contracts/<table>.v2.yaml
   │                              aucune écriture sur les données ──► Log ──► END
   │
   ├─ (approved) ─► Apply ... transaction, table diagnostiquée uniquement
   ├─ Validate ........ re-profilage ; succès, ou « échec — à traiter manuellement »
   └─ Log ............. INSERT INTO INCIDENTS ──► END
```

---

## 8. Orchestration

```
DAG: medallion_pipeline

  ingest ──► dbt run silver ──► dbt test ──► dbt run gold ──► dbt test
     │              │                             │
     ▼              ▼                             ▼
  agent_qualite  agent_qualite               agent_qualite
   (Bronze)        (Silver)                    (Gold)
```

L'agent est déclenché **à chaque couche**, avec un contexte (`layer`, `table`, `batch_id`) différent.
Airflow ne contient aucune logique de qualité : il déclenche, il ne décide pas. Les résultats des
`dbt test` sont transmis à l'agent comme signaux d'entrée (anomalies déjà confirmées).

---

## 9. Résilience

| Panne | Comportement attendu |
|-------|----------------------|
| LLM indisponible / réponse non parsable | Incident journalisé « diagnostic impossible — à traiter manuellement ». **Jamais d'action sur un diagnostic incertain.** |
| Correction appliquée sans l'effet attendu | `Validate` le constate → « échec — à traiter manuellement ». Pas de re-tentative automatique. |
| Checkpointer corrompu / proposition perdue | Le run suivant re-détecte l'anomalie (elle est toujours là) et re-propose. |
| Streamlit indisponible | Les propositions attendent dans le checkpointer ; rien n'est appliqué, rien n'est perdu. |

La logique : **en cas de doute, l'agent s'arrête et laisse la main à l'humain.** Il n'existe aucun
scénario de panne où une correction s'applique sans décision humaine.

---

## 10. Sécurité & données sensibles

- **Le LLM voit des agrégats, pas des lignes** (P2). Le prompt de `Diagnose` est construit à partir du
  `profile`, pas de la table.
- **Option zéro-fuite** : Snowflake Cortex — les données ne quittent jamais Snowflake. C'est l'argument
  décisif si Tython refuse tout appel externe.
- **`run_sql` est en lecture seule**, avec garde-fou anti-écriture et journalisation de chaque requête.
- **`Apply` est le seul point d'écriture de correction**, borné (transaction, table unique) et
  postérieur à l'approbation humaine.
- **Secrets** : `.env` (jamais commité) + `.env.example` (commité, sans valeurs).

---

## 11. Décisions structurantes

Chaque décision a son ADR dans [`adr/`](adr/), au format *contexte / options / décision / conséquences* :

| ADR | Décision |
|-----|----------|
| `000` | Décisions v3 (journal historique) |
| `001` | Accès Snowflake — gestion de la fenêtre de trial |
| `002` | Airflow vs Dagster |
| `003` | Snowflake vs DuckDB |
| `004` | LangGraph vs function calling simple |
| `005` | Choix du LLM |
| `006` | ~~Policy-as-code vs seuils en dur~~ — **remplacé par `008`** |
| `007` | Agent vs dbt tests seuls |
| `008` | **HITL pur vs scoring d'autonomie** (décision v4) |
| `009` | **Source hybride** — Olist rejoué + injection contrôlée vs génération Faker |
| `010` | **Agent générique** (décision du 2026-07-28) — deux cycles, zéro nom en dur, contrat versionné, 8 nœuds / 3 issues, ne jamais inventer une valeur |

> Les ADR se rédigent **au fil de l'eau**, pas en phase finale. Une décision reconstituée trois mois plus
> tard est une justification, pas une décision.
