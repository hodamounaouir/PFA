"""Verrou 2 (phase 1.4) : ground_truth.yaml ↔ contenu réel des batchs.

Pour chaque anomalie déclarée dans le corrigé, vérifie que le batch injecté
porte bien la panne annoncée (type, cible, ampleur). Si ce test passe, le
corrigé du benchmark dit la vérité.
"""

from datetime import date

import pandas as pd
import pytest
import yaml

from data import config

GROUND_TRUTH = config.DATA_DIR / "ground_truth.yaml"


def _spec() -> dict:
    return yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8"))


def _anomaly(anomaly_id: str) -> dict:
    return next(a for a in _spec()["anomalies"] if a["id"] == anomaly_id)


def _batch_path(anomaly: dict):
    folder = config.INCOMING_DIR / str(anomaly["date"])
    if not (folder / ".injected").exists():
        pytest.skip(f"batch {anomaly['date']} non injecté (lancer replay puis inject)")
    return folder / f"{anomaly['table']}.csv"


def _read(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _source_orders_count(day: str) -> int:
    orders = pd.read_csv(config.OLIST_DIR / config.CSV_BY_TABLE["orders"],
                         usecols=["order_id", "order_purchase_timestamp"])
    days = pd.to_datetime(orders["order_purchase_timestamp"]).dt.date
    return int((days == date.fromisoformat(day)).sum())


def test_marqueurs_presents_sur_les_5_jours():
    for anomaly in _spec()["anomalies"]:
        marker = config.INCOMING_DIR / str(anomaly["date"]) / ".injected"
        if not marker.exists():
            pytest.skip(f"{anomaly['date']} non injecté")
        assert anomaly["id"] in marker.read_text()


def test_j45_schema_drift():
    anomaly = _anomaly("schema_drift_j45")
    columns = _read(_batch_path(anomaly)).columns
    assert anomaly["params"]["new_name"] in columns
    assert anomaly["params"]["column"] not in columns


@pytest.mark.parametrize("anomaly_id", ["nulls_j60", "nulls_j85_recidive"])
def test_nulls_au_taux_annonce(anomaly_id):
    anomaly = _anomaly(anomaly_id)
    df = _read(_batch_path(anomaly))
    empty = (df[anomaly["params"]["column"]] == "").sum()
    assert empty == round(len(df) * anomaly["params"]["rate"])


def test_j75_doublons_au_taux_annonce():
    anomaly = _anomaly("duplicates_j75")
    df = _read(_batch_path(anomaly))
    duplicated = int(df.duplicated().sum())
    original = len(df) - duplicated
    assert duplicated == round(original * anomaly["params"]["rate"])


def test_j80_troncature_au_taux_annonce():
    anomaly = _anomaly("truncate_j80")
    df = _read(_batch_path(anomaly))
    source_count = _source_orders_count(str(anomaly["date"]))
    assert len(df) == round(source_count * anomaly["params"]["keep_rate"])
    assert len(df) < source_count * 0.5  # le trou de volume est bien massif


def test_recidive_strictement_identique_a_l_originale():
    """J85 doit rester la copie exacte de J60 (mesure mémoire T1 vs T2)."""
    first, second = _anomaly("nulls_j60"), _anomaly("nulls_j85_recidive")
    assert second["recidive_of"] == first["id"]
    assert second["table"] == first["table"]
    assert second["params"] == first["params"]
