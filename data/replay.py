"""Simulateur de rejeu : transforme Olist (historique figé) en batchs quotidiens.

Un jour rejoué = un dossier `data/incoming/YYYY-MM-DD/` contenant les commandes
du jour (orders, order_items, order_payments, customers). Au jour 1 de la
fenêtre, les référentiels (products, geolocation) sont livrés en entier.

Déterministe : mêmes arguments → mêmes fichiers, à l'octet près.

Usage :
    uv run python -m data.replay --day 2018-03-15
    uv run python -m data.replay --from 2018-03-01 --to 2018-03-05
"""

import argparse
import sys
from datetime import date, timedelta

import pandas as pd

from data import config


def load_tables() -> dict[str, pd.DataFrame]:
    tables = {
        name: pd.read_csv(config.OLIST_DIR / filename, low_memory=False)
        for name, filename in config.CSV_BY_TABLE.items()
    }
    purchase = pd.to_datetime(tables["orders"]["order_purchase_timestamp"])
    tables["orders"] = tables["orders"].assign(_day=purchase.dt.date)
    return tables


def batch_for_day(tables: dict[str, pd.DataFrame], day: date) -> dict[str, pd.DataFrame]:
    orders = tables["orders"]
    orders_day = orders[orders["_day"] == day].drop(columns="_day")
    order_ids = orders_day["order_id"]

    batch = {
        "orders": orders_day,
        "order_items": tables["order_items"][
            tables["order_items"]["order_id"].isin(order_ids)
        ],
        "order_payments": tables["order_payments"][
            tables["order_payments"]["order_id"].isin(order_ids)
        ],
        "customers": tables["customers"][
            tables["customers"]["customer_id"].isin(orders_day["customer_id"])
        ],
    }
    if day == date.fromisoformat(config.WINDOW_START):
        for name in config.REFERENCE_TABLES:
            batch[name] = tables[name]
    return batch


def write_batch(batch: dict[str, pd.DataFrame], day: date) -> None:
    folder = config.INCOMING_DIR / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    # Un batch réécrit redevient vierge : l'injecteur pourra repasser
    (folder / ".injected").unlink(missing_ok=True)
    for name, df in batch.items():
        # Tri par clés puis reset d'index : sortie identique à chaque exécution
        df.sort_values(by=list(df.columns[:2]), kind="mergesort").to_csv(
            folder / f"{name}.csv", index=False
        )
    counts = ", ".join(f"{name}={len(df)}" for name, df in batch.items())
    print(f"📦 {day} → {folder.relative_to(config.DATA_DIR.parent)}  ({counts})")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rejoue Olist jour par jour")
    parser.add_argument("--day", type=date.fromisoformat, help="rejoue un seul jour")
    parser.add_argument("--from", dest="start", type=date.fromisoformat,
                        help="début de plage (défaut : début de fenêtre)")
    parser.add_argument("--to", dest="end", type=date.fromisoformat,
                        help="fin de plage incluse (défaut : fin de fenêtre)")
    parser.add_argument("--seed", type=int, default=config.SEED,
                        help="réservé à l'injection (le rejeu est sans hasard)")
    args = parser.parse_args(argv)
    if args.day and (args.start or args.end):
        parser.error("--day est exclusif de --from/--to")
    return args


def check_window(day: date) -> None:
    start = date.fromisoformat(config.WINDOW_START)
    end = date.fromisoformat(config.WINDOW_END)
    if not start <= day <= end:
        sys.exit(f"❌ {day} est hors fenêtre de rejeu ({start} → {end}, cf. data/config.py)")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.day:
        days = [args.day]
    else:
        start = args.start or date.fromisoformat(config.WINDOW_START)
        end = args.end or date.fromisoformat(config.WINDOW_END)
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    for day in days:
        check_window(day)

    tables = load_tables()
    for day in days:
        write_batch(batch_for_day(tables, day), day)
    print(f"✅ {len(days)} jour(s) rejoué(s)")


if __name__ == "__main__":
    main()
