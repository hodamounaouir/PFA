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
        # Économie de crédits : le warehouse s'endort après 60 s d'inactivité
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
