# Airflow local — pipeline Medallion (phase 2.3)

Airflow **orchestre** ici la baseline (sans IA) : il rejoue chaque jour Olist,
injecte les anomalies prévues, ingère en Bronze (Snowflake RAW), puis lance dbt
(Silver + Gold) avec ses tests. Le résultat de chaque jour est archivé dans
[`benchmarks/baseline_run.json`](../benchmarks/baseline_run.json).

> Conçu pour tourner **sur ton PC** (Docker Desktop), pas sur le serveur.
> Snowflake étant dans le cloud, le DAG l'atteint de la même façon depuis ton PC.

---

## 1. Prérequis (sur le PC)

1. **Docker Desktop** installé et **lancé** (l'icône baleine active).
2. Le repo cloné, et **dans le repo** :
   - `data/olist/` rempli avec les CSV Kaggle (dossier non versionné — à copier).
   - `.env` **à la racine du repo** rempli (identifiants `SNOWFLAKE_*`, `GROQ_API_KEY`).
     Copie-le depuis `.env.example` si besoin.
3. ⚠️ **Fins de ligne du `.env`** : enregistre-le en **LF** (pas CRLF), sinon les
   valeurs Snowflake sont lues avec un `\r` parasite et la connexion échoue.
   Dans VS Code : coin bas-droit → clique `CRLF` → choisis `LF` → sauvegarde.

Toutes les commandes ci-dessous se lancent **depuis le dossier `airflow/`** :

```powershell
cd airflow
```

---

## 2. Construire l'image et démarrer

```powershell
docker compose build                # construit Airflow + le venv isolé du pipeline (~quelques min)
docker compose up airflow-init      # UNE SEULE FOIS : crée la base + l'utilisateur admin
docker compose up -d                # lance webserver + scheduler en tâche de fond
```

Ouvre ensuite **http://localhost:8080** → login **airflow** / **airflow**.
Tu dois voir le DAG **`medallion_pipeline`** dans la liste.

---

## 3. Lancer le pipeline sur la fenêtre (2018-03-01 → 05-31)

### Option A — recommandée : d'abord 30 jours « propres », puis le reste

On valide que le DAG est **vert de bout en bout** sur les jours sans anomalie,
avant d'attaquer les jours corrompus (où des `dbt test` échouent = détections).

```powershell
# Les 30 premiers jours (aucune anomalie injectée) :
docker compose exec airflow-scheduler \
  airflow dags backfill -s 2018-03-01 -e 2018-03-30 medallion_pipeline

# Le reste de la fenêtre (contient les anomalies J45, J60, J75, J80, J85) :
docker compose exec airflow-scheduler \
  airflow dags backfill -s 2018-03-31 -e 2018-05-31 medallion_pipeline
```

### Option B — tout d'un coup

Dans l'UI, **active** (unpause) le DAG `medallion_pipeline` : `catchup=True` +
`max_active_runs=1` rejouent automatiquement les 92 jours **dans l'ordre**.

---

## 4. Vérifier le résultat

- **UI Airflow** : la vue *Grid* montre chaque jour. Les jours d'anomalie
  restent **verts** (les échecs de `dbt test` = détections, tolérées volontairement,
  cf. le DAG) ; seule une vraie erreur dbt (code 2) rendrait une tâche rouge.
- **Snowflake** : schémas `RAW` (Bronze), `STAGING` (Silver), `MARTS` (Gold) remplis.
- **Fichier** : [`benchmarks/baseline_run.json`](../benchmarks/baseline_run.json)
  se remplit — une entrée par jour, avec `expected_anomalies`, les tests, et
  `baseline_detected`. Les jours J45/J60/J75/J80/J85 doivent avoir
  `baseline_detected: true` ; les autres `false`.

---

## 5. Rejouer un jour proprement

`data.replay` régénère le batch **à neuf** (il efface le marqueur `.injected`),
et l'ingestion est idempotente. Pour rejouer un jour, relance-le **depuis la
tâche `replay`** (bouton *Clear* sur `replay` dans l'UI, ou) :

```powershell
docker compose exec airflow-scheduler \
  airflow dags backfill -s 2018-04-14 -e 2018-04-14 --reset-dagruns medallion_pipeline
```

> Ne relance pas `inject` seul sur un batch déjà injecté : il refuse de corrompre
> deux fois le même jour (marqueur `.injected`). Repars toujours de `replay`.

---

## 6. Arrêter / réinitialiser

```powershell
docker compose down          # arrête les conteneurs (garde la base Airflow + les volumes)
docker compose down -v       # + efface les volumes (repart de zéro : refais l'étape airflow-init)
```

---

## 7. En cas de souci

| Symptôme | Cause probable / solution |
|---|---|
| `env file ../.env not found` | Le `.env` racine manque. Crée-le (`cp .env.example .env`) et remplis-le. |
| Connexion Snowflake échoue (`250001`, host bizarre) | `.env` en CRLF → réenregistre-le en **LF** (voir §1.3). |
| `❌ Batch introuvable` à l'ingestion | `data/olist/` vide → les CSV Kaggle ne sont pas dans le repo. |
| Tâche `replay` : `hors fenêtre de rejeu` | Jour hors 2018-03-01 → 05-31 (fenêtre figée, `data/config.py`). |
| L'image ne se build pas (tag introuvable) | Ajuste la version dans `Dockerfile` (`apache/airflow:2.10.5-python3.11`). |
| Port 8080 déjà pris | Change `"8080:8080"` en `"8081:8080"` dans `docker-compose.yaml`. |
