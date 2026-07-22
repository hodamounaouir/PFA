"""Ingestion Bronze : charge les batchs de data/incoming/ dans Snowflake RAW (phase 2.1).

Bronze = la couche brute. On y dépose les données **telles quelles**, sans jugement :
  - aucune transformation, aucun typage (toutes les colonnes en VARCHAR),
    aucun rejet de ligne ;
  - trois métadonnées de traçabilité par ligne : `_batch_id` (le jour rejoué),
    `_source` (le fichier d'origine), `_ingested_at` (l'heure de chargement) ;
  - **idempotent** : recharger le même batch ne duplique rien (on efface d'abord
    les lignes de ce `_batch_id`, puis on réinsère) ;
  - le schéma observé de chaque table est capturé dans `OPS._SCHEMA_HISTORY`
    (une ligne par colonne) — c'est ce que lira `read_schema_history` en phase 4
    pour repérer une dérive (ex. le renommage payment_value→amount au J45).

Le VARCHAR partout est volontaire : si une colonne change de nom ou apparaît,
l'ingestion ne casse pas — elle ajoute la colonne et continue. C'est le rôle de
Bronze de tout accepter ; c'est dbt (Silver, phase 2.2) qui typera et nettoiera.

Usage :
  uv run python -m ingestion.load --day 2018-03-01            # un jour
  uv run python -m ingestion.load --from 2018-03-01 --to 2018-03-30
  uv run python -m ingestion.load                             # toute la fenêtre
"""

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv
from snowflake.connector.pandas_tools import write_pandas

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import config  # noqa: E402

RAW_SCHEMA = "RAW"
OPS_SCHEMA = "OPS"
SCHEMA_HISTORY = "_SCHEMA_HISTORY"

# Colonnes techniques ajoutées à chaque table Bronze (préfixe _ pour les distinguer
# des colonnes métier). _ingested_at est rempli côté Snowflake (DEFAULT).
META_BATCH = "_batch_id"
META_SOURCE = "_source"
META_INGESTED = "_ingested_at"


def connect() -> snowflake.connector.SnowflakeConnection:
    """Ouvre une connexion Snowflake à partir du .env (même contrat que scripts/)."""
    load_dotenv(config.DATA_DIR.parent / ".env")
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=RAW_SCHEMA,
        login_timeout=15,
    )


def ensure_schema_history(cur) -> None:
    """Crée la table OPS._SCHEMA_HISTORY si besoin (une ligne = une colonne observée)."""
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OPS_SCHEMA}.{SCHEMA_HISTORY} (
            batch_id          VARCHAR,
            table_name        VARCHAR,
            column_name       VARCHAR,
            ordinal_position  NUMBER,
            captured_at       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
        """
    )


def ensure_bronze_table(cur, table: str, columns: list[str]) -> None:
    """Garantit que RAW.<table> existe et possède toutes les colonnes du batch.

    Toutes les colonnes métier sont VARCHAR. Les colonnes techniques sont créées
    une fois. `ADD COLUMN IF NOT EXISTS` absorbe les dérives de schéma (colonne
    renommée ou ajoutée) sans jamais casser l'ingestion.
    """
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {RAW_SCHEMA}.{table} (
            {META_BATCH}     VARCHAR,
            {META_SOURCE}    VARCHAR,
            {META_INGESTED}  TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
        """
    )
    for col in columns:
        cur.execute(
            f"ALTER TABLE {RAW_SCHEMA}.{table} ADD COLUMN IF NOT EXISTS {col} VARCHAR"
        )


def record_schema(cur, batch_id: str, table: str, columns: list[str]) -> None:
    """Journalise le schéma observé de la table pour ce batch (idempotent)."""
    cur.execute(
        f"DELETE FROM {OPS_SCHEMA}.{SCHEMA_HISTORY} "
        f"WHERE batch_id = %s AND table_name = %s",
        (batch_id, table),
    )
    rows = [(batch_id, table, col, i) for i, col in enumerate(columns, start=1)]
    cur.executemany(
        f"INSERT INTO {OPS_SCHEMA}.{SCHEMA_HISTORY} "
        f"(batch_id, table_name, column_name, ordinal_position) "
        f"VALUES (%s, %s, %s, %s)",
        rows,
    )


def load_table(conn, cur, batch_id: str, table: str, csv_path: Path) -> int:
    """Charge un CSV brut dans RAW.<table> pour un batch donné. Retourne le nb de lignes."""
    # dtype=str : Bronze ne type rien. Les valeurs manquantes du source (ex. nulls
    # injectés) deviennent NaN → NULL en base, ce qui préserve l'anomalie.
    df = pd.read_csv(csv_path, dtype=str)
    columns = list(df.columns)

    ensure_bronze_table(cur, table, columns)
    record_schema(cur, batch_id, table, columns)

    df[META_BATCH] = batch_id
    df[META_SOURCE] = csv_path.name

    # Idempotence : on efface les lignes déjà présentes pour ce batch avant de réinsérer.
    cur.execute(f"DELETE FROM {RAW_SCHEMA}.{table} WHERE {META_BATCH} = %s", (batch_id,))

    # quote_identifiers=False : les noms de colonnes suivent la casse Snowflake (uppercase),
    # ce qui évite le classique décalage minuscule/MAJUSCULE de write_pandas.
    write_pandas(
        conn,
        df,
        table_name=table.upper(),
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=RAW_SCHEMA,
        quote_identifiers=False,
    )
    return len(df)


def load_batch(conn, batch_id: str) -> None:
    """Charge tous les CSV présents dans data/incoming/<batch_id>/."""
    folder = config.INCOMING_DIR / batch_id
    if not folder.is_dir():
        sys.exit(f"❌ Batch introuvable : {folder} (as-tu lancé data/replay.py ?)")

    csvs = sorted(folder.glob("*.csv"))
    cur = conn.cursor()
    ensure_schema_history(cur)

    counts = []
    for csv_path in csvs:
        table = csv_path.stem  # orders.csv -> orders
        n = load_table(conn, cur, batch_id, table, csv_path)
        counts.append(f"{table}={n}")
    conn.commit()
    print(f"📥 {batch_id} → RAW  ({', '.join(counts)})")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Charge les batchs Olist dans Snowflake RAW (Bronze)"
    )
    parser.add_argument("--day", type=date.fromisoformat, help="charge un seul jour")
    parser.add_argument("--from", dest="start", type=date.fromisoformat,
                        help="début de plage (défaut : début de fenêtre)")
    parser.add_argument("--to", dest="end", type=date.fromisoformat,
                        help="fin de plage incluse (défaut : fin de fenêtre)")
    args = parser.parse_args(argv)
    if args.day and (args.start or args.end):
        parser.error("--day est exclusif de --from/--to")
    return args


def resolve_days(args: argparse.Namespace) -> list[date]:
    if args.day:
        days = [args.day]
    else:
        start = args.start or date.fromisoformat(config.WINDOW_START)
        end = args.end or date.fromisoformat(config.WINDOW_END)
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    start = date.fromisoformat(config.WINDOW_START)
    end = date.fromisoformat(config.WINDOW_END)
    for day in days:
        if not start <= day <= end:
            sys.exit(f"❌ {day} est hors fenêtre de rejeu ({start} → {end}, cf. data/config.py)")
    return days


def main(argv: list[str] | None = None) -> None:
    days = resolve_days(parse_args(argv))
    conn = connect()
    try:
        for day in days:
            load_batch(conn, day.isoformat())
    finally:
        conn.close()
    print(f"✅ {len(days)} batch(s) chargé(s) dans RAW")


if __name__ == "__main__":
    main()
