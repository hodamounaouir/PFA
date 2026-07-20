# Contribuer

> Ce projet est un **projet de stage** (Tython) avec un contributeur principal et des relecteurs. Ce
> document sert deux publics : le contributeur principal — pour rester cohérent sur ~4 mois — et **toute
> personne qui reprendrait le projet ensuite**. Le critère de réussite §13 du cahier est explicite :
> *« documentation permettant à un tiers de reprendre le projet »*. Ce fichier en fait partie.

---

## 1. Avant de coder : lire dans cet ordre

| # | Document | Ce que vous y trouvez |
|---|----------|----------------------|
| 1 | [`README.md`](README.md) | De quoi il s'agit, en 5 minutes |
| 2 | [`CAHIER_DES_CHARGES.md`](CAHIER_DES_CHARGES.md) | Le **contrat** (v4) — quoi et pourquoi |
| 3 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Comment c'est structuré |
| 4 | [`docs/DESIGN.md`](docs/DESIGN.md) | Pourquoi ces choix — et ce qui a été écarté |
| 5 | [`ROADMAP.md`](ROADMAP.md) | Où on en est, et quelle est la prochaine étape |

**Ne commencez pas une tâche sans avoir lu le *Definition of Done* de sa phase dans la roadmap.** Une
phase se termine quand son DoD est vrai — pas quand le temps imparti est écoulé.

---

## 2. Installation

### Prérequis

- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv)
- Docker (Airflow local)
- Un compte Snowflake ⚠️ [voir la question du trial](ROADMAP.md#️-à-régler-dès-maintenant--la-fenêtre-snowflake)
- Une clé LLM (Groq recommandé — gratuit)

### Mise en route

```bash
make setup                 # environnement + dépendances figées
cp .env.example .env       # renseigner les secrets
python scripts/check_access.py   # ✅ Snowflake  ✅ LLM
```

Si `check_access.py` n'est pas vert, **arrêtez-vous là**. Tout le reste échouera plus loin, plus
obscurément.

---

## 3. Les 6 règles non négociables

Elles ne sont pas stylistiques. **Chacune protège une propriété qui rend le projet défendable** — une PR
qui en casse une est refusée, quelle que soit sa valeur par ailleurs.

### R1 — Le LLM n'est appelé que dans `Diagnose`

Si vous vous surprenez à appeler un LLM dans `Detect` ou ailleurs, **arrêtez**. Vous cassez la
propriété centrale : *le graphe contrôle le flux, le LLM ne fait que raisonner* ([`DESIGN.md` §2](docs/DESIGN.md)).

Besoin d'intelligence dans `Detect` ? Produisez des **candidats** par du code déterministe, et laissez
`Diagnose` **qualifier**.

### R2 — Le LLM ne reçoit jamais de lignes brutes

Stats agrégées et métadonnées uniquement. L'échantillon passe par `run_sql` (lecture seule, journalisé),
jamais par défaut. Confidentialité d'abord, mais aussi qualité du raisonnement ([`DESIGN.md` §3](docs/DESIGN.md)).

### R3 — Aucun chemin vers `Apply` sans décision humaine

Le graphe ne contient **aucune arête `Diagnose → Apply`**. La seule entrée d'`Apply` est `Propose` avec
`human_decision == "approved"`. Ajouter un raccourci « juste pour le dev » — même derrière un flag —
est un bug : c'est précisément la promesse du projet ([`DESIGN.md` §5](docs/DESIGN.md)).

**Le test** : le test de preuve P3 (« aucune exécution n'atteint `Apply` sans approbation ») doit passer
sur chaque commit.

### R4 — `Apply` est borné, même après approbation

Transaction SQL ; table diagnostiquée uniquement ; mots-clés destructeurs (`DROP`, `TRUNCATE`, `DELETE`
sans `WHERE`) rejetés. L'approbation humaine autorise **cette correction-là**, pas un accès en écriture
généralisé.

### R5 — La mémoire ne relit que les incidents tranchés par un humain

`read_past_incidents` filtre sur `human_decision IS NOT NULL`. Un agent qui apprend de ses propres
hallucinations non validées est une régression. Non négociable, et c'est la première question qu'un jury
posera sur la feature.

### R6 — Chaque run écrit sa ligne dans `INCIDENTS`

Y compris « rien d'anormal », y compris « refusé », y compris « échec ». Le journal est append-only :
on n'update jamais une ligne d'incident passée (les corrections d'état passent par de nouvelles lignes).
Un journal à trous ne prouve rien.

---

## 4. Où mettre quoi

| Vous écrivez… | Ça va dans… |
|---------------|-------------|
| Un chargement de source | `ingestion/` — **brut**, aucune transformation |
| Une transformation | `dbt/models/{bronze,silver,gold}/` — jamais en Python |
| Un node du graphe | `agent/nodes/` — une fonction état → état |
| Un tool LangChain | `agent/tools/` — un fichier par tool, testé isolément |
| Un écran | `streamlit/` — affiche et débloque, ne calcule pas |
| Un DAG | `airflow/dags/` — déclenche, ne décide pas |
| Une anomalie de test | `data/` + **obligatoirement** `data/ground_truth.yaml` |
| Une décision structurante | `docs/adr/NNN-titre.md` (voir §7) |

### Ce qui est versionné, ce qui ne l'est pas

| Versionné ✅ | Ignoré ❌ |
|-------------|----------|
| `data/ground_truth.yaml` — la vérité terrain | `data/*.csv`, `data/*.parquet` — régénérables via `--seed 42` |
| `.env.example` — les clés, sans valeurs | `.env` — **jamais**, sous aucun prétexte |
| `benchmarks/*.json` — les résultats figés | `dbt/target/`, `logs/`, `.venv/` |
| Les règles dbt générées par l'agent (une fois approuvées) | Checkpoints SQLite locaux |

Avant tout premier commit : vérifier le `.gitignore`. Un secret commité est un secret compromis, même
après un `git rm` — l'historique le garde.

---

## 5. Workflow Git

### Branches

```
main                    # toujours vert, toujours démontrable
└── phase-N/sujet       # ex. phase-4/detection-semantique
└── fix/sujet
└── docs/sujet
```

### Commits

Format [Conventional Commits](https://www.conventionalcommits.org/) :

```
feat(agent): node Propose — interrupt + reprise via checkpointer
fix(agent): Apply rejette les requêtes hors table diagnostiquée
test(hitl): aucun chemin vers Apply sans approbation (preuve P3)
docs(adr): ADR 008 — HITL pur vs scoring d'autonomie
chore(data): injecteur d'anomalies sémantiques
```

**Portées** : `ingestion` · `dbt` · `agent` · `airflow` · `streamlit` · `data` ·
`benchmarks` · `ci` · `docs` · `hitl`

### Référencer la roadmap

Un commit qui fait avancer une phase la mentionne : `feat(agent): tool profile_table (phase 4)`. Sur
quatre mois, c'est ce qui permet de reconstituer l'histoire du projet — et de la raconter en soutenance.

---

## 6. Tests

### Le principe

Un seul node appelle le LLM. **Les six autres sont testables sans mock** — c'est le bénéfice direct de
R1, et il faut l'encaisser.

| Quoi | Comment |
|------|---------|
| Nodes déterministes | Test unitaire direct, état factice en entrée |
| `Diagnose` | **LLM mocké** — on teste le parsing et la gestion d'erreur, pas le LLM |
| Routage | Les 3 chemins du graphe : rien d'anormal / refusé / approuvé |
| Pause & reprise | Une exécution interrompue sur `Propose` reprend après redémarrage du process |
| `Apply` | Requête hors table diagnostiquée → rejet ; mot-clé destructeur → rejet |
| Journal | Tout chemin (y compris « rien d'anormal ») produit sa ligne `INCIDENTS` |
| Tools | Chacun isolément, avant tout branchement dans un node |

```bash
make test          # pytest, LLM mocké
make lint          # ruff + format
make check         # lint + test
```

**Aucun test n'appelle un vrai LLM.** La CI doit être déterministe, gratuite, et tourner sans clé API.

### Les tests qui sont des livrables

Trois tests ne sont pas de l'hygiène — ce sont les **preuves** du projet, celles qu'on montre au jury :

1. **Aucun chemin vers `Apply` sans `human_decision == "approved"`** — prouve le HITL structurel (P3).
2. **Pause sur `interrupt` + reprise après redémarrage** — prouve que le HITL est un mécanisme, pas une démo.
3. **`Apply` borné** (table unique, mots-clés rejetés) — prouve que l'approbation n'ouvre pas tout.

Ne les traitez pas comme des tests ordinaires.

---

## 7. Les ADR

Une décision structurante = un fichier `docs/adr/NNN-titre.md`.

### Format

```markdown
# NNN — Titre de la décision

**Statut** : proposé | accepté | remplacé par NNN
**Date** : YYYY-MM-DD

## Contexte
Le problème, les contraintes, ce qui force un choix.

## Options
Ce qui a été envisagé — honnêtement, avec les avantages de ce qu'on n'a pas retenu.

## Décision
Ce qu'on fait, et pourquoi cette option-là.

## Conséquences
Ce que ça coûte. Ce qu'on ne pourra plus faire. Ce qu'il faudra surveiller.
```

### La règle

> **Un ADR se rédige au moment de la décision, pas en phase 9.**

Un ADR reconstitué trois mois plus tard n'est pas une décision : c'est une justification. Ça se voit, et
un jury le sent. La section « Conséquences » est celle qui compte — c'est là qu'on montre qu'on a compris
ce qu'on payait. L'ADR `008-hitl-pur-vs-scoring.md` (décision v4) est le premier à écrire — le contexte
est encore frais.

---

## 8. Definition of Done d'une contribution

Avant de fusionner :

- [ ] `make check` est vert (lint + tests)
- [ ] Aucune des 6 règles non négociables (§3) n'est enfreinte
- [ ] Les 3 tests de preuve (§6) passent toujours
- [ ] Tout nouveau tool est testé isolément
- [ ] Toute nouvelle anomalie de test est dans `ground_truth.yaml`
- [ ] Une décision structurante ? → son ADR est écrit **dans la même PR**
- [ ] Le DoD de la phase concernée ([`ROADMAP.md`](ROADMAP.md)) est toujours atteignable
- [ ] La doc suit : un changement d'architecture met à jour [`ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## 9. Secrets

- **Jamais** de secret dans le code, un commit, un notebook ou une capture d'écran.
- `.env` est ignoré ; `.env.example` est commité **sans valeurs**.
- Une nouvelle variable d'environnement s'ajoute **dans les deux** : `.env.example` et
  `scripts/check_access.py`.
- Un secret commité par erreur est **compromis** : le révoquer, pas seulement le supprimer. L'historique
  Git n'oublie pas.

---

## 10. Les pièges connus

Tirés des `Piège` de la [`ROADMAP.md`](ROADMAP.md) — ce sont des erreurs anticipées, pas des hypothèses :

| Phase | Le piège | Pourquoi ça coûte cher |
|-------|----------|------------------------|
| 0 | Commencer à coder l'ingestion | La phase 0 sert à découvrir les problèmes d'accès **maintenant**, pas en phase 4 |
| 1 | Écrire `ground_truth.yaml` après coup | Le benchmark ne vaut alors plus rien (§9.1 du design) |
| 2 | Ajouter l'agent « juste pour voir » | La baseline doit rester une **référence propre** — c'est contre elle qu'on mesure tout |
| 2 | Une baseline qui attrape `sao paulo`/`são paulo` | Le projet perd son sujet. Elle **doit** le rater, et c'est à prouver par une requête |
| 3 | Appeler un LLM hors `Diagnose` | Casse R1 — le projet perd sa défendabilité |
| 3–5 | Ajouter un raccourci d'auto-apply « pour le dev » | Casse R3 — la promesse centrale du projet devient fausse |
| 4 | Viser un détecteur sémantique général | Un détecteur modeste et lucide vaut mieux qu'un ambitieux et faux |
| 4 | Relire des incidents sans décision humaine | L'agent apprend ses erreurs — R5 |
| 8 | Un run unique par mesure | Un LLM n'est pas déterministe : ≥ 3 runs, moyenne + écart-type |

---

## 11. Si le temps manque

L'ordre de sacrifice est **décidé à l'avance**, pas dans la panique ([`ROADMAP.md`](ROADMAP.md)) :

1. **E4** (streaming)
2. **E2 + E3** (GitHub MCP, CI) → remplaçables par le journal `INCIDENTS` et un `pytest` manuel
3. **E1** (mémoire vectorielle) → la mémoire SQL du noyau démontre déjà O7
4. **Cause racine (phase 7)** → en dernier recours
5. **Phase 6** réduite à deux écrans (Décision + Validation)

**Jamais sacrifiables** : les phases 0 → 6, 8 et 9.

> Un projet sans benchmark (8) ou sans documentation (9) perd plus de points qu'un projet sans extension.

---

## 12. Une question ?

- Sur le **quoi/pourquoi fonctionnel** → [`CAHIER_DES_CHARGES.md`](CAHIER_DES_CHARGES.md)
- Sur un **choix technique** → [`docs/DESIGN.md`](docs/DESIGN.md), puis [`docs/adr/`](docs/adr/)
- Sur **l'ordre des choses** → [`ROADMAP.md`](ROADMAP.md)
- Si la réponse n'y est **nulle part** → c'est probablement qu'un ADR manque. Écrivez-le.
