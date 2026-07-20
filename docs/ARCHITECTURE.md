# Architecture

> **Ce document décrit *comment le système est structuré*** — composants, flux, responsabilités.
>
> - Le **quoi** et le **pourquoi fonctionnel** : [`CAHIER_DES_CHARGES.md`](../CAHIER_DES_CHARGES.md) (v4)
> - Le **pourquoi technique** et les arbitrages : [`DESIGN.md`](DESIGN.md)
> - L'**ordre de construction** : [`ROADMAP.md`](../ROADMAP.md)

**Statut** : architecture cible. Le projet est en phase 0 — voir l'[avancement](../README.md#avancement).

---

## 1. Principes directeurs

Cinq invariants. Tout le reste en découle, et **aucun n'est négociable** — une PR qui en casse un est
refusée, quelle que soit sa valeur par ailleurs.

| # | Principe | Conséquence concrète |
|---|----------|----------------------|
| **P1** | **Le graphe contrôle le flux, le LLM ne fait que raisonner** | Le LLM n'est appelé **que** dans `Diagnose`. Le routage et les décisions sont du code déterministe et testable. |
| **P2** | **Le LLM ne voit jamais les données brutes** | Il reçoit des **statistiques agrégées et des métadonnées**. L'accès aux échantillons passe par un tool en lecture seule, journalisé et masquable. |
| **P3** | **Aucune correction sans validation humaine** | Le graphe ne contient **aucun chemin** `Diagnose → Apply` : la seule arête entrante d'`Apply` vient de `Propose` avec `human_decision == "approved"`. Prouvé par test. |
| **P4** | **`Apply` est borné, même après approbation** | Transaction SQL, table diagnostiquée uniquement, mots-clés destructeurs rejetés, `Validate` systématique après coup. |
| **P5** | **Le journal est append-only et complet** | `logs: Annotated[list, add]` + une ligne dans `INCIDENTS` pour **chaque** run, y compris « rien d'anormal » et « refusé ». |

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
   │                                                   │
   │  Diagnose intègre : mémoire (INCIDENTS)           │
   │                     + cause racine (lineage dbt)  │
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

```python
class AgentState(TypedDict):
    layer: str                        # bronze | silver | gold (contexte Airflow)
    table: str
    batch_id: str
    profile: dict                     # ← Profile
    schema_history: list
    anomalies: list                   # ← Detect
    past_incidents: list              # ← lus dans INCIDENTS (mémoire)
    diagnosis: Optional[dict]         # ← Diagnose (LLM) : root_cause, proposed_fix, explanation
    human_decision: Optional[str]     # ← Propose : "approved" | "rejected"
    validation: Optional[dict]        # ← Validate : success | failed
    logs: Annotated[list, add]        # append-only
```

Détail structurant : **`logs: Annotated[list, add]`** — le réducteur `add` rend le journal *append-only
par construction*. Un node ne peut pas réécrire l'histoire, même par erreur (P5).

### 5.2 Les nodes

| Node | LLM ? | Rôle |
|------|:-----:|------|
| `Profile` | ❌ | Statistiques agrégées via `profile_table` ; persiste dans `_profiles` |
| `Detect` | ❌ | Dérive de schéma (diff) + dérives statistiques (z-score vs historique) + anomalie sémantique (clustering) + échecs dbt test |
| `Diagnose` | ✅ | **Le seul appel LLM.** Stats + métadonnées + lineage dbt + incidents passés → diagnostic structuré (cause, correction proposée, explication) |
| `Propose` | ❌ | `interrupt()` — met le graphe en pause, attend la décision humaine (Streamlit) |
| `Apply` | ❌ | Écrit — **uniquement si `human_decision == "approved"`**, en transaction, table diagnostiquée seulement |
| `Validate` | ❌ | Re-profile la table : l'anomalie a-t-elle disparu ? Échec → « à traiter manuellement » |
| `Log` | ❌ | Une ligne dans `INCIDENTS`, quel que soit le chemin parcouru |

**Un seul node appelle le LLM.** C'est la propriété qui rend le système testable : les six autres sont
du code déterministe, couverts par des tests unitaires sans mock.

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

Ce qui est **testé** (les preuves, pas de simples tests d'hygiène) :

- Aucun chemin d'exécution n'atteint `Apply` sans `human_decision == "approved"`.
- Une exécution se met en pause sur `interrupt` et reprend correctement après décision.
- `Apply` refuse toute requête hors de la table diagnostiquée (et les mots-clés destructeurs).

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
   ├─ (refusé) ───────────────────────────────────────► Log ──► END
   │
   ├─ Apply ........... transaction, table diagnostiquée uniquement
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

> Les ADR se rédigent **au fil de l'eau**, pas en phase finale. Une décision reconstituée trois mois plus
> tard est une justification, pas une décision.
