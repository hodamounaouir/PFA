"""DAG medallion_pipeline — pipeline Bronze → Silver → Gold, un run par jour rejoué.

Phase 2.3 : Airflow orchestre les briques déjà écrites (phases 1, 2.1, 2.2).
Il n'y a AUCUNE IA ici — c'est la baseline du benchmark.

Chaque tâche lance une commande du projet dans l'environnement Python ISOLÉ du
pipeline (/opt/airflow/pipeline-venv), séparé des dépendances d'Airflow.

Enchaînement (pour un jour {{ ds }}) :

    replay → inject → ingest_bronze
           → dbt run (silver) → dbt test (silver)
           → dbt run (gold)   → dbt test (gold)
           → archive_baseline

Fenêtre : 2018-03-01 → 2018-05-31 (92 jours, cf. data/config.py).
catchup=True + max_active_runs=1 : les jours se rejouent dans l'ordre, ce qui
construit l'historique dont l'agent (phase 4) aura besoin.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

# Chemins DANS le conteneur (le repo entier est monté sur /opt/airflow/project).
PROJECT = "/opt/airflow/project"
PY = "/opt/airflow/pipeline-venv/bin/python"   # python du venv isolé du pipeline
DBT = "/opt/airflow/pipeline-venv/bin/dbt"
DBT_DIR = f"{PROJECT}/dbt"

# Un `dbt test` qui échoue à cause d'une anomalie INJECTÉE est une DÉTECTION
# attendue, pas un bug. dbt renvoie :
#   0 = tous les tests passent
#   1 = des tests échouent  → ce sont nos détections baseline → on continue
#   2 = erreur réelle dbt   → on bloque le pipeline
# On ne fait donc échouer la tâche que sur le code 2 → le DAG reste vert sur les
# détections (conforme à la Definition of Done de la phase 2).
DBT_TEST_TOLERATE = (
    'rc=$?; '
    'if [ "$rc" -eq 2 ]; then exit 2; fi; '
    'echo "dbt test terminé (rc=$rc — 0=tout vert, 1=détections baseline attendues)"; '
    'exit 0'
)

default_args = {
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="medallion_pipeline",
    description="Bronze→Silver→Gold : rejeu Olist + injection + ingestion + dbt (baseline sans agent)",
    start_date=datetime(2018, 3, 1),
    end_date=datetime(2018, 5, 31),
    schedule="@daily",
    catchup=True,
    max_active_runs=1,              # batchs séquentiels : l'historique se construit dans l'ordre
    default_args=default_args,
    tags=["pfa", "medallion", "baseline"],
    doc_md=__doc__,
) as dag:

    # 1) Rejoue le jour Olist → data/incoming/<jour>/
    replay = BashOperator(
        task_id="replay",
        bash_command=f"cd {PROJECT} && {PY} -m data.replay --day {{{{ ds }}}}",
    )

    # 2) Injecte les anomalies prévues ce jour-là (--if-scheduled : ne casse pas
    #    un jour sans anomalie, c'est le cas de la plupart des jours).
    inject = BashOperator(
        task_id="inject",
        bash_command=f"cd {PROJECT} && {PY} -m data.inject --day {{{{ ds }}}} --if-scheduled",
    )

    # 3) Ingestion brute → Snowflake RAW (Bronze), idempotente.
    ingest_bronze = BashOperator(
        task_id="ingest_bronze",
        bash_command=f"cd {PROJECT} && {PY} -m ingestion.load --day {{{{ ds }}}}",
    )

    # 4) Silver : vues stg_ (typage), puis leurs tests baseline.
    dbt_run_silver = BashOperator(
        task_id="dbt_run_silver",
        bash_command=f"cd {DBT_DIR} && {DBT} run --select staging --profiles-dir . --target dev",
    )
    dbt_test_silver = BashOperator(
        task_id="dbt_test_silver",
        bash_command=(
            f"cd {DBT_DIR} && {DBT} test --select staging --profiles-dir . --target dev "
            f"--target-path target/silver; " + DBT_TEST_TOLERATE
        ),
    )

    # 5) Gold : tables fct_, puis leurs tests baseline.
    dbt_run_gold = BashOperator(
        task_id="dbt_run_gold",
        bash_command=f"cd {DBT_DIR} && {DBT} run --select marts --profiles-dir . --target dev",
    )
    dbt_test_gold = BashOperator(
        task_id="dbt_test_gold",
        bash_command=(
            f"cd {DBT_DIR} && {DBT} test --select marts --profiles-dir . --target dev "
            f"--target-path target/gold; " + DBT_TEST_TOLERATE
        ),
    )

    # 6) Archive le résultat baseline du jour vs ground_truth → benchmarks/baseline_run.json
    archive_baseline = BashOperator(
        task_id="archive_baseline",
        bash_command=f"cd {PROJECT} && {PY} -m benchmarks.archive_baseline --day {{{{ ds }}}}",
    )

    (
        replay
        >> inject
        >> ingest_bronze
        >> dbt_run_silver
        >> dbt_test_silver
        >> dbt_run_gold
        >> dbt_test_gold
        >> archive_baseline
    )
