# Image Airflow + un environnement Python ISOLÉ pour le pipeline du projet.
#
# Pourquoi un venv séparé ? Airflow épingle ses propres versions de dépendances
# (dont pandas). Le pipeline du projet a les siennes (pandas, snowflake, dbt…).
# On installe donc les deps du pipeline dans /opt/airflow/pipeline-venv ; Airflow
# n'y touche jamais → aucun conflit de versions possible.
#
# Argument d'histoire pour la soutenance : « Airflow orchestre, mais chaque étape
# tourne dans l'environnement du projet, isolé des dépendances d'Airflow. »

FROM apache/airflow:2.10.5-python3.11

# Environnement dédié au pipeline : rejeu, injection, ingestion Bronze, dbt.
# (numpy/pyarrow arrivent en dépendances de pandas/snowflake.)
RUN python -m venv /opt/airflow/pipeline-venv \
 && /opt/airflow/pipeline-venv/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/airflow/pipeline-venv/bin/pip install --no-cache-dir \
      "pandas>=2.2" \
      "numpy>=1.26" \
      "pyarrow>=18.0.0" \
      "snowflake-connector-python>=4.7.1" \
      "python-dotenv>=1.2.2" \
      "pyyaml>=6.0.3" \
      "dbt-snowflake>=1.8.0"
