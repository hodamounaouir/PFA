# Cahier des Charges — v4

## Plateforme de Qualité de Données Auto-Adaptative sous Contrôle Humain (LangGraph)

> **Pipeline Medallion (Bronze / Silver / Gold)** doté d'un **agent IA** qui **détecte, diagnostique et
> propose la correction** des problèmes de qualité de données — en **s'adaptant dynamiquement** aux
> évolutions de schéma et aux anomalies sémantiques. **Aucune correction n'est appliquée sans validation
> humaine explicite**, et chaque incident laisse une **trace complète**.

**Contexte** : Stage Data Engineering — Entreprise : Tython — Rôle : Data Engineer Intern
**Version** : 4.0 — simplifie la gouvernance (HITL pur, suppression du scoring), recentre le noyau,
déplace mémoire vectorielle / journalisation GitHub / streaming en extensions.
**Stack** : Snowflake · dbt · Airflow · LangGraph / LangChain · Streamlit · GitHub Actions

---

## 0. Ce qui change par rapport à la v3 (journal des décisions)

| Décision v4 | Origine | Impact |
|-------------|---------|--------|
| **HITL pur : toute correction exige une validation humaine** | Décision projet 2026-07-20 | Suppression du triplet confiance × risque × environnement, de la matrice de décision et des branches `Act` (auto) / `Escalate` |
| **Suppression de la policy-as-code** (`governance/policy.yaml`) | Conséquence du HITL pur | Plus de seuils de routage à calibrer ; la garantie est **structurelle** (topologie du graphe), pas déclarative |
| **Graphe réduit à 7 nœuds** | Simplification | `Recall` et `TraceRootCause` fusionnés dans `Diagnose` ; un seul point de pause : `Propose` |
| **Suppression de la boucle de retry** | Simplification | Échec de validation → incident marqué « à traiter manuellement », pas de re-diagnostic automatique |
| **Table `INCIDENTS` (Snowflake) = mémoire + journal** | Simplification | La mémoire du noyau est du SQL (mêmes table / type d'anomalie) ; le RAG vectoriel (Chroma) devient une **extension** |
| **Journalisation GitHub (MCP) → extension** | Recentrage | Le journal auditable du noyau est la table `INCIDENTS`, consultable dans Streamlit |
| **Streaming (Kafka/Redpanda) → extension** | Décision projet | Le batch quotidien d'abord ; le streaming n'arrive que si le temps le permet |
| **Source de données = hybride : dataset réel Olist rejoué + injection contrôlée** | Décision projet 2026-07-20 | Pas de génération Faker ; le fil rouge sémantique (`sao paulo`/`são paulo`) est réel ; `ground_truth.yaml` conservé pour le benchmark (ADR 009) |
| Rappel v3 conservé : Airflow, Snowflake, dbt tests seuls, LLM gratuit (Groq/Cortex) | HG6/HG10/HG11/HG12 | Inchangé |

---

## 1. Contexte et problématique

Les pipelines classiques reposent sur des **règles de qualité statiques** définies à la main, qui ne
s'adaptent ni aux évolutions de schéma ni aux **anomalies sémantiques** (ex. `sao paulo` vs `são paulo` qui
faussent les agrégats sans violer aucune règle de format). Quand un incident survient, le diagnostic est
**manuel, chronophage et peu tracé** — et une fois l'incident résolu, rien n'est capitalisé : le même
problème est re-diagnostiqué de zéro des mois plus tard.

**Problématique** :
> Comment concevoir un pipeline qui **détecte et diagnostique** de façon **auto-adaptative** les
> problèmes de qualité, via un agent IA orchestré comme une **machine à états**, qui **propose** les
> corrections — sans jamais en appliquer une seule **sans validation humaine explicite** — et qui
> garde une **trace complète et exploitable** de chaque incident ?

---

## 2. Positionnement & proposition de valeur

Le projet se tient sur **deux jambes complémentaires** :

### 2.1 Qualité auto-adaptative (le moteur)
L'agent ne se contente pas d'exécuter des règles figées. Il **profile** les données, **détecte** les
dérives (schéma + sémantique) par comparaison à l'historique, **génère dynamiquement** de nouvelles
règles, et **réutilise** les incidents passés pour diagnostiquer plus vite (mémoire).

### 2.2 Contrôle humain systématique (la couche de sûreté)
Aucune IA ne modifie des données sans qu'un humain l'ait approuvé. Le graphe de l'agent ne contient
**aucun chemin** entre le diagnostic et l'application qui ne passe par une **pause de validation
humaine** (`interrupt` LangGraph). La garantie n'est pas une politique configurable : c'est la
**topologie du graphe**. Et chaque incident — corrigé, refusé ou sans suite — est **journalisé**.

> **La phrase du projet** : *« Une IA qui rend la qualité de données auto-adaptative — l'agent détecte,
> diagnostique et propose ; l'humain décide ; tout est tracé. »*

---

## 3. Objectifs

### 3.1 Objectifs prioritaires (⭐ — cœur de la soutenance)

| # | Objectif | Critère de succès |
|---|----------|-------------------|
| O1 | Pipeline Medallion de bout en bout | Ingestion → Silver → Gold sur ≥ 2 sources |
| O2 | Agent LangGraph détectant schéma & anomalies sémantiques | Graphe d'état + conditional edges fonctionnels |
| O3 | Génération dynamique de règles de qualité | ≥ 3 types (format, cohérence, complétude) rattachés aux dimensions DAMA |
| O4 | Observabilité des décisions | Streamlit : incidents, raisonnement, propositions, validation HITL |
| O5 | **Validation humaine systématique (HITL)** | Pause réelle du graphe (`interrupt` + checkpointer), reprise après décision, aucun chemin vers `Apply` sans approbation — prouvé par test |
| O6 | Preuve de valeur vs baseline | Benchmark chiffré (précision, rappel, MTTR, taux d'approbation des propositions) |

### 3.2 Objectifs différenciants (🌟 — ce qui rend le projet remarquable)

| # | Objectif | Critère de succès |
|---|----------|-------------------|
| O7 | **Mémoire de l'agent** (table `INCIDENTS`) | L'agent reconnaît une anomalie déjà vue (même table / même type) et réutilise le diagnostic validé ; 2ᵉ passage plus rapide |
| O8 | **Analyse de cause racine** via lineage | Sur une casse Gold, l'agent remonte à la modification Bronze/Silver responsable (lineage dbt `manifest.json`) |

### 3.3 Extensions (🔸 — si le temps le permet, dans cet ordre)

| # | Extension | Critère de succès |
|---|-----------|-------------------|
| E1 | Mémoire **vectorielle** (RAG, Chroma) | Rappel par similarité sémantique au-delà du match table/type |
| E2 | Journalisation **GitHub via MCP** | 1 issue par incident, trace auditable hors machine |
| E3 | **CI** GitHub Actions | dbt tests + tests unitaires nodes (LLM mocké) à chaque push |
| E4 | **Streaming** (Kafka/Redpanda) | Bronze alimenté en continu, l'aval inchangé |
| E5 | Catalogue & lineage externe (OpenMetadata) | ⚪ Perspective — le lineage dbt interne suffit à O8 |

### 3.4 Hors périmètre

- Déploiement en production réelle de l'entreprise.
- **Toute correction automatique**, où que ce soit — par conception : chaque application passe par un humain.
- Volumétrie Big Data (POC démontrable, pas un système à l'échelle).

---

## 4. Architecture fonctionnelle

### 4.1 Vue d'ensemble

```
Rejeu du dataset réel Olist (1 batch/jour) + injection contrôlée (ground_truth.yaml)
        │
        ▼
Ingestion Python ──► Bronze (Snowflake, brut + métadonnées)
        │
        ▼
dbt (dbt-snowflake) ──► Silver (nettoyage / typage / dédoublonnage)
        │              └──► Gold (agrégats métier, BI/ML)
        ▼
Snowflake (stockage / requêtage · + table INCIDENTS)

   ↕ à chaque couche, Airflow déclenche la tâche « agent qualité » :
   ┌──────────────────────────────────────────────────────────────┐
   │ Agent IA (LangGraph) — 7 nœuds                                │
   │  Profile ► Detect ► Diagnose(LLM) ► Propose ⏸ ► Apply         │
   │  ► Validate ► Log                                             │
   │  Mémoire & journal : table INCIDENTS (Snowflake)              │
   │  Validation humaine & observabilité : Streamlit               │
   └──────────────────────────────────────────────────────────────┘
```

### 4.2 Couches Medallion

- **Bronze** — ingestion brute ; l'agent détecte les dérives de schéma et **signale ou propose de bloquer**.
- **Silver** — nettoyage dbt ; l'agent **génère les règles manquantes** selon le profil.
- **Gold** — agrégats métier ; l'agent vérifie la **cohérence sémantique inter-tables** avant publication.

---

## 5. L'agent IA (LangGraph) — spécification

### 5.1 Principe
Machine à états (`StateGraph`). Le **graphe** contrôle le flux ; le **LLM n'est appelé que dans `Diagnose`**.
Le LLM raisonne sur des **statistiques agrégées et métadonnées**, **jamais** sur les données brutes par défaut
(accès aux échantillons seulement via un outil en lecture seule, journalisé et masquable).

### 5.2 État partagé (`AgentState`)

```python
class AgentState(TypedDict):
    layer: str                        # bronze | silver | gold (contexte Airflow)
    table: str
    batch_id: str
    profile: dict                     # ← Profile
    schema_history: list
    anomalies: list                   # ← Detect
    past_incidents: list              # ← lus dans INCIDENTS (mémoire, O7)
    diagnosis: Optional[dict]         # ← Diagnose : root_cause, proposed_fix, explanation
    human_decision: Optional[str]     # ← Propose : "approved" | "rejected" (HITL)
    validation: Optional[dict]        # ← Validate : success | failed
    logs: Annotated[list, add]        # audit trail append-only
```

### 5.3 Graphe

```
START
  → Profile → Detect ──(rien d'anormal)──────────────────────────► Log → END
                 │ (anomalies)
                 ▼
              Diagnose (LLM + lineage dbt + incidents passés)
                 │
                 ▼
              Propose ⏸ interrupt — attente de la décision humaine (Streamlit)
                 │                         │
             (approuvé)                (refusé)
                 ▼                         │
              Apply ──► Validate ──────────┴──► Log → END
                          (succès, ou échec marqué « à traiter manuellement »)
```

- **`Diagnose`** absorbe la mémoire et la cause racine : avant d'appeler le LLM, le nœud lit les
  incidents similaires dans `INCIDENTS` (O7) et le lineage dbt depuis `manifest.json` (O8), et les
  injecte dans le contexte.
- **`Propose`** est le **seul point de sortie** de `Diagnose` : structurellement, aucune correction ne
  peut être appliquée sans passer par la pause de validation.
- **Pas de boucle de retry** : si `Validate` constate que la correction n'a pas eu l'effet attendu,
  l'incident est marqué « échec — à traiter manuellement » et journalisé. L'humain reprend la main.

### 5.4 Garde-fous

Ils sont **structurels** (dans le code et la topologie du graphe), pas configurables :

1. **Aucun chemin `Diagnose → Apply`** : la seule arête entrante d'`Apply` vient de `Propose` avec
   `human_decision == "approved"`. Prouvé par test.
2. **`Apply` est borné** : transaction SQL, table diagnostiquée uniquement, mots-clés destructeurs
   (`DROP`, `TRUNCATE`, autre table) rejetés — même après approbation humaine.
3. **`Validate` systématique** : re-profilage après application ; on ne croit jamais une correction sur parole.
4. **Journalisation totale** : chaque run écrit une ligne dans `INCIDENTS`, y compris « rien d'anormal »
   et « refusé ». Le journal est append-only.
5. **LLM confiné** : un seul nœud l'appelle (`Diagnose`), sur agrégats et métadonnées uniquement.

### 5.5 La table `INCIDENTS`

Une ligne par exécution de l'agent :

```
incident_id · run_ts · layer · table · batch_id · anomalies (JSON) ·
diagnosis (JSON) · proposed_fix (JSON) · human_decision · decided_by · decided_at ·
validation_status · duration_s
```

Trois rôles : **journal auditable** (relu dans Streamlit), **mémoire de l'agent** (lue par `Diagnose` —
uniquement les incidents ayant reçu une décision humaine), **source du benchmark** (MTTR, taux
d'approbation).

### 5.6 Outils exposés (`@tool`)
`profile_table` · `read_schema_history` · `run_sql` (lecture seule) · `generate_dq_rule` (dbt test) ·
`lineage_impact` (parse `manifest.json`) · `read_past_incidents` (SQL sur `INCIDENTS`, décisions humaines
uniquement) · `write_log`.

---

## 6. Features différenciantes (détail)

### 6.1 🌟 Mémoire de l'agent (O7)
Chaque incident **ayant reçu une décision humaine** est réutilisable : au début de `Diagnose`, l'agent
requête `INCIDENTS` (même table, même type d'anomalie) et injecte le diagnostic et la décision passés
dans le contexte du LLM. **Effet démontrable** : le 2ᵉ passage d'une même anomalie est plus rapide et
mieux argumenté (« cas similaire résolu le J-12, correction approuvée »). Narratif : *« l'agent
apprend »*. L'extension E1 (RAG vectoriel) généralise ce rappel à la similarité sémantique.

### 6.2 🌟 Analyse de cause racine (O8)
Quand un agrégat Gold est incohérent, l'agent **remonte le lineage** (graphe de dépendances dbt, déjà
présent dans `manifest.json`) pour trouver **quelle** modification Bronze/Silver l'a causé (ex. la casse
de `city` non normalisée en Silver provoque le fan-out en Gold). C'est précisément ce qui prend le plus de
temps à un data engineer → **réduction concrète du MTTR**.

---

## 7. Stack technique

| Domaine | Outil |
|---------|-------|
| Ingestion | Python (`requests`, `pandas`) — CSV/JSON/API/PostgreSQL |
| Stockage / requêtage | **Snowflake** (Bronze/Silver/Gold + `INCIDENTS`) |
| Transformation & tests | **dbt** (`dbt-snowflake`) + dbt tests |
| Orchestration | **Airflow** |
| Agent (raisonnement) | **LangGraph** (`StateGraph`, conditional edges, `interrupt`) |
| Tools/prompts/parsing | **LangChain** (`@tool`, `PromptTemplate`, `PydanticOutputParser`) |
| LLM | **Groq** (recommandé) / Google AI Studio / **Snowflake Cortex** (zéro-fuite) |
| Mémoire & journal | Table `INCIDENTS` (Snowflake) — 🔸 E1 : + Chroma (vectoriel) |
| Persistance agent | LangGraph Checkpointer (`SqliteSaver` / `PostgresSaver`) |
| Observabilité & HITL | **Streamlit** |
| Journalisation externe | 🔸 E2 : **GitHub** via serveur **MCP** |
| CI | 🔸 E3 : **GitHub Actions** |
| Données | Dataset réel **Olist** (Kaggle) rejoué jour par jour + injection contrôlée (cas sémantique `sao paulo`/`são paulo` réel) |

---

## 8. Méthodologie d'évaluation (benchmark)

### 8.1 Protocole
1. Jeu de test avec anomalies injectées et documentées (nulls anormaux, formats, doublons, **incohérences
   sémantiques** dont le fan-out `sao paulo`/`são paulo`).
2. Exécution en parallèle : (a) **baseline** règles statiques (dbt tests) ; (b) **agent** LangGraph.
3. Comparaison sur les métriques ci-dessous.

### 8.2 Métriques

| Métrique | Définition | Axe |
|----------|------------|-----|
| Précision | Anomalies signalées réellement vraies | Qualité |
| Rappel | Anomalies réelles détectées | Qualité |
| Anomalies sémantiques détectées | Invisibles à la baseline, captées par l'agent | Qualité auto-adaptative |
| **Temps de diagnostic (MTTR)** | Délai détection → cause identifiée (manuel vs agent) | Valeur métier |
| **Taux d'approbation des propositions** | Propositions de l'agent approuvées telles quelles par l'humain | Qualité des diagnostics |
| **Gain mémoire** | Réduction du temps de diagnostic au 2ᵉ passage d'une anomalie connue | Auto-adaptatif |

**Livrable** : rapport de benchmark chiffré (tableau comparatif + synthèse + limites).

---

## 9. Scénario de démonstration (fil rouge de la soutenance)

Toute la démo tourne autour d'**un incident** :

1. Les ventes par ville sont **fausses** (double comptage `sao paulo`/`são paulo`) — invisible aux règles statiques.
2. L'agent **détecte** l'anomalie sémantique.
3. `Diagnose` : pas d'antécédent dans `INCIDENTS` (la 2ᵉ fois, il reconnaîtra) ; le LLM **remonte le
   lineage** → cause = normalisation manquante en Silver.
4. Il **propose** la normalisation de `city` en Silver avec l'impact estimé (n tables Gold concernées) — et le graphe **se met
   en pause**.
5. **Validation humaine dans Streamlit** : le validateur lit l'anomalie, la cause, la correction et
   l'impact, puis clique ✅ Approuver.
6. Le graphe **reprend** : correction appliquée, `Validate` re-profile → agrégats corrigés.
7. Incident complet **journalisé dans `INCIDENTS`**, visible dans Streamlit.
8. *(Bis)* La même anomalie réinjectée plus tard : l'agent la **reconnaît** et cite l'incident précédent.

→ Un seul incident démontre O1→O8 d'un coup.

---

## 10. Livrables

| # | Livrable |
|---|----------|
| L1 | Pipeline fonctionnel (code, couches Bronze/Silver/Gold, modèles dbt) |
| L2 | Agent LangGraph (graphe 7 nœuds, tools, mémoire, cause racine) |
| L3 | Interface Streamlit (observabilité + validation HITL) |
| L4 | Jeu de données de test avec anomalies injectées (`ground_truth.yaml`) |
| L5 | Rapport de benchmark chiffré (dont gain MTTR & mémoire) |
| L6 | Journal d'incidents complet (`INCIDENTS`) + preuve HITL (tests) |
| L7 | 🔸 CI (GitHub Actions) — extension E3 |
| L8 | Documentation technique (README, architecture, ADR) |
| L9 | Support de soutenance |
| L10 | 🔸 Journalisation GitHub via MCP — extension E2 |

---

## 11. Planning indicatif

| Phase | Contenu | Durée |
|-------|---------|-------|
| 0 | Cadrage, choix techniques, environnement (Snowflake/Airflow/dbt) | 3–5 j |
| 1 | Jeu de données + anomalies injectées (`ground_truth.yaml`) | 1 sem |
| 2 | Pipeline Medallion sans agent (baseline) | 2–3 sem |
| 3 | Squelette agent LangGraph (7 nœuds, stubs, checkpointer) | 1–2 sem |
| 4 | Agent branché au pipeline (détection réelle, `INCIDENTS`, règles) | 2 sem |
| 5 | HITL complet : `interrupt`, reprise, `Apply` borné, `Validate` | 1–2 sem |
| 6 | Observabilité Streamlit (BI, incidents, validation) | 1–2 sem |
| 7 | 🌟 Cause racine (lineage) — puis extensions E1→E4 si le temps | 1–2 sem |
| 8 | Benchmark chiffré | 1–2 sem |
| 9 | Documentation, ADR, soutenance | 1 sem |

---

## 12. Risques & mitigation

| Risque | Mitigation |
|--------|------------|
| L'agent propose une correction incorrecte | Validation humaine systématique + `Apply` borné (transaction, table unique) + `Validate` post-application |
| L'humain approuve trop vite (« rubber-stamping ») | La proposition affiche cause + impact + diff estimé ; le taux d'approbation est mesuré au benchmark |
| Coût LLM trop élevé | LLM appelé uniquement si `Detect` trouve une anomalie ; provider gratuit (Groq/Cortex) |
| Fuite de données sensibles vers le LLM | LLM sur agrégats/métadonnées ; option **Cortex** (données restent dans Snowflake) |
| Complexité dépassant le temps | Noyau d'abord (O1→O6) ; O7/O8 puis E1→E4 incrémentalement |
| Anomalies réelles non maîtrisées (dates, ampleur) | Montage hybride : données réelles (Olist) + anomalies **injectées** à dates choisies, documentées dans `ground_truth.yaml` |
| Scope creep | Backlog priorisé (⭐ / 🌟 / 🔸), revue hebdomadaire |

---

## 13. Critères de réussite

- Pipeline Medallion de bout en bout sur ≥ 2 sources.
- Graphe LangGraph avec ≥ 1 scénario complet (détection → diagnostic → proposition → **validation
  humaine** → application → vérification → journal).
- Amélioration mesurable vs baseline sur ≥ 2 métriques (dont anomalies sémantiques).
- HITL démontrable : une exécution **se met réellement en pause** et **reprend** après décision — et le
  test « aucun chemin vers `Apply` sans approbation » passe.
- 🌟 Mémoire démontrable (2ᵉ passage plus rapide) **et/ou** cause racine tracée sur ≥ 1 incident.
- Journal `INCIDENTS` complet et consultable dans Streamlit.
- Documentation permettant à un tiers de reprendre le projet.

---

## 14. Documentation attendue

- README avec schéma d'architecture (pipeline + graphe LangGraph).
- **ADR** justifiant les choix structurants : Airflow vs Dagster · LangGraph vs function calling simple ·
  Snowflake vs DuckDB · choix du LLM · **HITL pur vs scoring d'autonomie**.
- Section **limites connues & perspectives** (recul critique).

---

*Projet réalisé dans le cadre d'un stage Data Engineering — Tython. Cahier des charges v4.*
