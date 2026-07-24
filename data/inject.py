"""Injecteur d'anomalies contrôlé (phase 1.3, ADR 009).

Modifie les batchs déjà écrits par data/replay.py — ne génère rien.
La config des anomalies EST data/ground_truth.yaml (une seule source).

Une classe par type d'anomalie ; déterministe (seed dérivé de data/config.py) ;
refuse de corrompre deux fois le même batch (marqueur .injected).

Usage :
    uv run python -m data.inject                     # tous les jours à anomalie
    uv run python -m data.inject --day 2018-04-14    # un seul jour
"""

import argparse
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yaml

from data import config

GROUND_TRUTH = config.DATA_DIR / "ground_truth.yaml"
MARKER = ".injected"


class RenameColumn:
    def __init__(self, params):
        self.params = params

    def apply(self, df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
        column, new_name = self.params["column"], self.params["new_name"]
        if column not in df.columns:
            raise ValueError(f"colonne {column!r} absente")
        return df.rename(columns={column: new_name})


class InjectNulls:
    def __init__(self, params):
        self.params = params

    def apply(self, df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
        column, rate = self.params["column"], self.params["rate"]
        n = round(len(df) * rate)
        rows = rng.choice(len(df), size=n, replace=False)
        df = df.copy()
        df.iloc[rows, df.columns.get_loc(column)] = ""
        return df


class DuplicateRows:
    def __init__(self, params):
        self.params = params

    def apply(self, df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
        n = round(len(df) * self.params["rate"])
        rows = sorted(rng.choice(len(df), size=n, replace=False))
        # Doublons ajoutés en fin de fichier, comme un job rejoué en append
        return pd.concat([df, df.iloc[rows]], ignore_index=True)


class TruncateRows:
    def __init__(self, params):
        self.params = params

    def apply(self, df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
        return df.head(round(len(df) * self.params["keep_rate"]))


ANOMALY_TYPES = {
    "rename_column": RenameColumn,
    "inject_nulls": InjectNulls,
    "duplicate_rows": DuplicateRows,
    "truncate_rows": TruncateRows,
}


def load_anomalies_by_date() -> dict[date, list[dict]]:
    spec = yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8"))
    start = date.fromisoformat(config.WINDOW_START)
    by_date: dict[date, list[dict]] = {}
    for anomaly in spec["anomalies"]:
        declared = date.fromisoformat(str(anomaly["date"]))
        computed = start + timedelta(days=anomaly["day"] - 1)
        if declared != computed:
            sys.exit(
                f"❌ ground_truth.yaml incohérent : {anomaly['id']} déclare "
                f"date={declared} mais J{anomaly['day']} = {computed}"
            )
        by_date.setdefault(declared, []).append(anomaly)
    return by_date


def inject_day(day: date, anomalies: list[dict]) -> None:
    folder = config.INCOMING_DIR / day.isoformat()
    if not folder.is_dir():
        sys.exit(f"❌ {folder} absent — lancer d'abord : uv run python -m data.replay --day {day}")
    marker = folder / MARKER
    if marker.exists():
        sys.exit(
            f"❌ {day} déjà injecté ({marker}). Pour recommencer proprement : "
            f"rejouer le jour avec data.replay puis relancer l'injection."
        )

    rng = np.random.default_rng(config.SEED + anomalies[0]["day"])
    for anomaly in anomalies:
        path = folder / f"{anomaly['table']}.csv"
        # dtype=str + keep_default_na=False : les lignes non touchées ressortent
        # à l'octet près (pas de reformatage de nombres ni de NaN parasites)
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        before = len(df)
        df = ANOMALY_TYPES[anomaly["type"]](anomaly.get("params", {})).apply(df, rng)
        df.to_csv(path, index=False)
        print(f"💉 {day} J{anomaly['day']} {anomaly['id']:<22} {anomaly['table']}.csv "
              f"({before} → {len(df)} lignes)")
    marker.write_text("\n".join(a["id"] for a in anomalies) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Injecte les anomalies de ground_truth.yaml")
    parser.add_argument("--day", type=date.fromisoformat,
                        help="n'injecter que ce jour (défaut : tous les jours à anomalie)")
    parser.add_argument("--if-scheduled", action="store_true",
                        help="mode orchestration (Airflow) : un jour sans anomalie prévue "
                             "sort proprement (code 0) au lieu d'échouer")
    args = parser.parse_args(argv)

    by_date = load_anomalies_by_date()
    if args.day:
        if args.day not in by_date:
            msg = f"ℹ️ aucune anomalie prévue le {args.day} (cf. ground_truth.yaml)"
            if args.if_scheduled:
                print(msg + " — batch laissé intact.")
                return
            sys.exit(msg)
        by_date = {args.day: by_date[args.day]}

    for day in sorted(by_date):
        inject_day(day, by_date[day])
    print(f"✅ {len(by_date)} jour(s) corrompu(s), conformément à ground_truth.yaml")


if __name__ == "__main__":
    main()
