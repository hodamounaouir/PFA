"""Création rejouable de l'infrastructure Snowflake (ADR 001).

Idempotent : peut être relancé sans risque (IF NOT EXISTS partout).
Usage : uv run python scripts/setup_snowflake.py
"""

import os
import sys

import snowflake.connector
from dotenv import load_dotenv

DATABASE = "DATA_QUALITY"
SCHEMAS = {
    "RAW": "Bronze — données brutes ingérées telles quelles",
    "STAGING": "Silver — données nettoyées/typées par dbt",
    "MARTS": "Gold — agrégats métier exposés au dashboard",
    "OPS": "Tables techniques (INCIDENTS, profils, historique agent)",
}


def main() -> int:
    load_dotenv()
    warehouse = os.environ["SNOWFLAKE_WAREHOUSE"]

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=warehouse,
    )

    statements = [
        # Un compte neuf n'a pas forcément de warehouse, et le nom du warehouse
        # par défaut a varié selon les époques et les régions. On le crée donc
        # au lieu de supposer qu'il existe : sans ça, rejouer l'infrastructure
        # sur un second trial (le plan B de l'ADR 001) échouait dès la première
        # instruction — précisément le jour où le script doit servir.
        # `INITIALLY_SUSPENDED` pour ne pas consommer de crédits à la création.
        f"CREATE WAREHOUSE IF NOT EXISTS {warehouse} WITH "
        f"WAREHOUSE_SIZE = 'XSMALL' AUTO_SUSPEND = 60 AUTO_RESUME = TRUE "
        f"INITIALLY_SUSPENDED = TRUE",
        # Économie de crédits : le warehouse s'endort après 60 s d'inactivité.
        # Conservé pour le cas où il *préexistait* — le CREATE ci-dessus n'aurait
        # alors rien fait, et il pourrait traîner un auto-suspend trop long.
        f"ALTER WAREHOUSE {warehouse} SET AUTO_SUSPEND = 60",
        f"CREATE DATABASE IF NOT EXISTS {DATABASE}",
    ]
    statements += [
        f"CREATE SCHEMA IF NOT EXISTS {DATABASE}.{name} COMMENT = '{comment}'"
        for name, comment in SCHEMAS.items()
    ]

    try:
        cur = conn.cursor()
        for stmt in statements:
            cur.execute(stmt)
            print(f"✅ {stmt}")
        cur.execute(f"SHOW SCHEMAS IN DATABASE {DATABASE}")
        found = {row[1] for row in cur.fetchall()}
        missing = set(SCHEMAS) - found
        if missing:
            print(f"❌ Schémas manquants : {missing}")
            return 1
        print(f"\n🎉 Base {DATABASE} prête — schémas : {', '.join(sorted(found))}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
