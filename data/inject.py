"""Injecteur d'anomalies contrôlé (phase 1.3, ADR 009).

Modifie les batchs déjà écrits par data/replay.py — ne génère rien.
La config des anomalies EST data/ground_truth.yaml (une seule source).

Une classe par type d'anomalie ; déterministe (seed dérivé de data/config.py) ;
refuse de corrompre deux fois le même batch (marqueur .injected).

Deux formes de déclaration (cf. `spread_anomalies`) : une anomalie **datée**
(un jour, un effet) ou **étalée** (une plage et des paliers de taux, pour une
dérive qui s'installe). L'étalement est résolu au chargement — `inject_day` ne
voit que des anomalies datées avec un taux ferme.

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


class SemanticVariants:
    """Réécrit une part des valeurs sous une orthographe concurrente (phase 1.5).

    Le contraire de `data/prepare.py` : là où la préparation replie les
    variantes, l'injection en fabrique. Une ville écrite `sao paulo` devient
    `são paulo` — même ville, deux clés d'agrégation, donc un chiffre d'affaires
    qui se scinde en deux lignes sans qu'aucun test de complétude ne bronche.

    La table de variantes est **déclarée**, jamais devinée : on ne « rajoute pas
    des accents », on applique une correspondance écrite dans le corrigé et
    construite sur les villes réellement présentes. C'est ce qui rend le
    benchmark exact — toute valeur accentuée qui apparaîtra sera forcément
    la nôtre, la fenêtre de référence ayant été rendue ASCII pure.
    """

    def __init__(self, params):
        self.params = params

    def apply(self, df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
        column, variants = self.params["column"], self.params["variants"]
        rate = self.params["rate"]
        if column not in df.columns:
            raise ValueError(f"colonne {column!r} absente")
        # Seules les lignes portant une ville de la table sont candidates : le
        # taux s'applique à elles, pas au batch entier. Sinon l'ampleur réelle
        # dépendrait de la composition du jour, et le corrigé serait faux.
        candidats = np.flatnonzero(df[column].isin(variants).to_numpy())
        n = round(len(candidats) * rate)
        if n == 0:
            return df
        choisis = rng.choice(candidats, size=n, replace=False)
        df = df.copy()
        position = df.columns.get_loc(column)
        df.iloc[choisis, position] = df.iloc[choisis, position].map(variants)
        return df


ANOMALY_TYPES = {
    "rename_column": RenameColumn,
    "inject_nulls": InjectNulls,
    "duplicate_rows": DuplicateRows,
    "truncate_rows": TruncateRows,
    "semantic_variants": SemanticVariants,
}


def _check_day(anomaly_id: str, day: int, declared, start: date) -> date:
    """Le jour et la date déclarés doivent désigner le même instant."""
    declared = date.fromisoformat(str(declared))
    computed = start + timedelta(days=day - 1)
    if declared != computed:
        sys.exit(
            f"❌ ground_truth.yaml incohérent : {anomaly_id} déclare "
            f"date={declared} mais J{day} = {computed}"
        )
    return declared


def _spread(anomaly: dict, start: date) -> list[dict]:
    """Une dérive progressive → une entrée par jour, taux résolu.

    Une anomalie qui s'installe (un nouvel outil de saisie qu'on déploie) ne se
    déclare pas jour par jour : on écrit une plage et des paliers, et on étale
    ici. Le corrigé reste lisible — une intention, une entrée — sans que
    `inject_day` ait à connaître la notion de rampe : il continue de recevoir
    des anomalies datées avec un taux ferme.

    Un palier vaut jusqu'au suivant : `{50: 0.10, 65: 0.40}` donne 10 % de J50 à
    J64, puis 40 % à partir de J65.
    """
    schedule = {int(k): v for k, v in anomaly["params"]["rate_schedule"].items()}
    debut = _check_day(anomaly["id"], anomaly["from_day"], anomaly["from_date"], start)
    _check_day(anomaly["id"], anomaly["to_day"], anomaly["to_date"], start)
    if max(schedule) > anomaly["to_day"]:
        sys.exit(
            f"❌ ground_truth.yaml : {anomaly['id']} a un palier après la fin de sa "
            f"plage J{anomaly['from_day']}→J{anomaly['to_day']} — paliers : {sorted(schedule)}"
        )
    # Le premier palier DOIT ouvrir la plage. Sinon le corrigé annonce une
    # dérive qui commence au J40 alors qu'elle commence au J50 : la phase 8
    # mesurerait la détection contre une date attendue fausse, et les jours
    # intermédiaires seraient déclarés « à anomalie » sans rien contenir.
    if min(schedule) != anomaly["from_day"]:
        sys.exit(
            f"❌ ground_truth.yaml : {anomaly['id']} démarre J{anomaly['from_day']} "
            f"mais son premier palier est J{min(schedule)} — la plage déclarée "
            f"doit commencer là où la dérive commence vraiment."
        )

    etalees = []
    for offset in range(anomaly["to_day"] - anomaly["from_day"] + 1):
        jour = anomaly["from_day"] + offset
        applicables = [palier for palier in schedule if palier <= jour]
        params = {k: v for k, v in anomaly["params"].items() if k != "rate_schedule"}
        params["rate"] = schedule[max(applicables)]
        etalees.append(
            {**anomaly, "day": jour, "date": debut + timedelta(days=offset),
             "params": params}
        )
    return etalees


def spread_anomalies() -> list[dict]:
    """Le corrigé, rampes étalées : une entrée = un jour = un taux ferme.

    C'est la vue que consomment l'injecteur **et** les tests de cohérence, pour
    qu'il n'existe qu'une seule interprétation du corrigé.
    """
    spec = yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8"))
    start = date.fromisoformat(config.WINDOW_START)
    etalees = []
    for anomaly in spec["anomalies"]:
        if "from_day" in anomaly:
            etalees.extend(_spread(anomaly, start))
        else:
            _check_day(anomaly["id"], anomaly["day"], anomaly["date"], start)
            etalees.append(anomaly)
    return etalees


def load_anomalies_by_date() -> dict[date, list[dict]]:
    by_date: dict[date, list[dict]] = {}
    for anomaly in spread_anomalies():
        by_date.setdefault(date.fromisoformat(str(anomaly["date"])), []).append(anomaly)
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
