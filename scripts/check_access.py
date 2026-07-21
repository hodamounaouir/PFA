"""Vérifie tous les accès externes du projet en une exécution (phase 0.2).

Usage : uv run python scripts/check_access.py
Sortie : ✅/❌ par service ; code retour 0 seulement si tout est vert.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def check_snowflake() -> str:
    import snowflake.connector

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        login_timeout=15,
    )
    try:
        cur = conn.cursor()
        cur.execute("SELECT CURRENT_VERSION(), CURRENT_DATABASE()")
        version, database = cur.fetchone()
        return f"Snowflake {version}, base {database}"
    finally:
        conn.close()


def check_groq() -> str:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=30)
    reply = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "Réponds uniquement : OK"}],
        max_tokens=5,
    )
    return f"LLM répond : {reply.choices[0].message.content.strip()!r}"


def check_olist() -> str:
    folder = PROJECT_ROOT / "data" / "olist"
    csvs = sorted(folder.glob("*.csv"))
    if len(csvs) < 9:
        raise RuntimeError(f"{len(csvs)}/9 fichiers CSV dans {folder}")
    return f"{len(csvs)} fichiers CSV dans data/olist/"


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    checks = [
        ("Snowflake", check_snowflake),
        ("LLM Groq", check_groq),
        ("Dataset Olist", check_olist),
    ]
    failures = 0
    for name, check in checks:
        try:
            detail = check()
            print(f"✅ {name:<14} {detail}")
        except Exception as exc:  # noqa: BLE001 — on veut un bilan, pas un crash
            failures += 1
            print(f"❌ {name:<14} {type(exc).__name__}: {exc}")
    print()
    if failures:
        print(f"❌ {failures} service(s) en échec")
    else:
        print("🎉 Tous les accès sont opérationnels")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
