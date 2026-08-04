"""Verrou 2 (phase 1.4) : ground_truth.yaml ↔ contenu réel des batchs.

Pour chaque anomalie déclarée dans le corrigé, vérifie que le batch injecté
porte bien la panne annoncée (type, cible, ampleur). Si ce test passe, le
corrigé du benchmark dit la vérité.
"""

from datetime import date, timedelta

import pandas as pd
import pytest
import yaml

from data import config, prepare
from data.inject import spread_anomalies

GROUND_TRUTH = config.DATA_DIR / "ground_truth.yaml"


def _spec() -> dict:
    return yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8"))


def _anomaly(anomaly_id: str) -> dict:
    """Une anomalie datée du corrigé, rampes étalées.

    On lit la vue étalée et non le YAML brut : une anomalie déclarée en plage
    n'a ni `day` ni `date`, et c'est l'étalement qui fait foi — c'est lui que
    l'injecteur consomme.
    """
    return next(a for a in spread_anomalies() if a["id"] == anomaly_id)


def _le_jour(anomaly_id: str, jour: int) -> dict:
    return next(
        a for a in spread_anomalies() if a["id"] == anomaly_id and a["day"] == jour
    )


def _batch_path(anomaly: dict):
    folder = config.INCOMING_DIR / str(anomaly["date"])
    if not (folder / ".injected").exists():
        pytest.skip(f"batch {anomaly['date']} non injecté (lancer replay puis inject)")
    return folder / f"{anomaly['table']}.csv"


def _read(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _source_orders_count(day: str) -> int:
    orders = pd.read_csv(
        config.OLIST_DIR / config.CSV_BY_TABLE["orders"],
        usecols=["order_id", "order_purchase_timestamp"],
    )
    days = pd.to_datetime(orders["order_purchase_timestamp"]).dt.date
    return int((days == date.fromisoformat(day)).sum())


def test_marqueurs_presents_sur_chaque_jour_a_anomalie():
    for anomaly in spread_anomalies():
        marker = config.INCOMING_DIR / str(anomaly["date"]) / ".injected"
        if not marker.exists():
            pytest.skip(f"{anomaly['date']} non injecté")
        assert anomaly["id"] in marker.read_text()


# --- La fenêtre de référence (décision du 2026-08-04) ------------------------


def test_la_fenetre_de_reference_ne_porte_aucune_anomalie():
    """L'invariant structurel : J1→J43 est propre, et le corrigé doit le rester.

    C'est sur cette fenêtre que l'agent construira son contrat en phase 4.2.
    Une anomalie qui s'y glisserait — par une rampe qui commence trop tôt, ou
    par un jour mal saisi — serait apprise comme la norme, et le piège
    descriptif ↔ normatif se refermerait sans que personne ne le voie.

    Test purement déclaratif : il ne dépend d'aucun batch rejoué, donc il
    protège la décision même quand rien n'est chargé.
    """
    debut = date.fromisoformat(config.WINDOW_START)
    coupables = [
        (a["id"], a["day"])
        for a in spread_anomalies()
        if (date.fromisoformat(str(a["date"])) - debut).days + 1 <= config.REFERENCE_END_DAY
    ]
    assert not coupables, (
        f"anomalie(s) dans la fenêtre de référence J1→J{config.REFERENCE_END_DAY} : "
        f"{coupables}"
    )


def test_les_preparations_sont_coherentes():
    """Jour ↔ date, et règle connue — mêmes contrôles que pour les anomalies.

    `charger_preparations()` sort en erreur si l'un des deux cloche ; ce test
    vérifie surtout qu'il y a bien quelque chose à charger, sinon un corrigé
    vidé par mégarde passerait pour valide.
    """
    preparations = prepare.charger_preparations()
    assert preparations, "la section `preparation` du corrigé a disparu"
    debut = date.fromisoformat(config.WINDOW_START)
    for prep in preparations:
        assert prep["rule"] in prepare.REGLES
        assert date.fromisoformat(str(prep["date"])) == debut + timedelta(
            days=prep["day"] - 1
        )
        assert prep["day"] <= config.REFERENCE_END_DAY, (
            "une préparation hors fenêtre de référence nettoierait des données "
            "que l'agent est censé surveiller"
        )


def test_plus_aucune_anomalie_reelle_non_datee():
    """`real_anomalies` a été supprimée le 2026-08-04 — elle ne doit pas revenir.

    Tant qu'elle existait, le cas São Paulo était un état permanent : l'agent
    « signalait », il ne « détectait » pas. Tout ce que l'agent doit trouver est
    désormais daté et quantifié, donc mesurable en phase 8.
    """
    assert "real_anomalies" not in _spec()


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


@pytest.mark.parametrize("jour", [50, 65, 78])
def test_derive_semantique_au_taux_annonce(jour):
    """Le taux porte sur les lignes CANDIDATES, pas sur le batch entier.

    Un batch pauvre en grandes villes produirait sinon moins d'anomalies que le
    corrigé n'en annonce, et le benchmark surestimerait le rappel de l'agent.
    """
    anomaly = _le_jour("semantic_drift_j50", jour)
    df = _read(_batch_path(anomaly))
    variants = anomaly["params"]["variants"]
    colonne = df[anomaly["params"]["column"]]

    accentuees = int(colonne.isin(variants.values()).sum())
    candidates = accentuees + int(colonne.isin(variants).sum())
    assert accentuees == round(candidates * anomaly["params"]["rate"])


def test_derive_semantique_absente_avant_son_premier_jour():
    """Le J44 est propre : rien d'accentué avant le J50 (test réciproque).

    Sans lui, une injection qui déborderait sur la fenêtre de référence ne se
    verrait pas — les tests d'ampleur ne regardent que les jours où l'on
    attend quelque chose.
    """
    debut = date.fromisoformat(config.WINDOW_START)
    veille = debut + timedelta(days=config.REFERENCE_END_DAY)  # J44
    chemin = config.INCOMING_DIR / veille.isoformat() / "customers.csv"
    if not chemin.exists():
        pytest.skip(f"batch {veille} non rejoué")
    villes = _read(chemin)["customer_city"]
    assert not villes.str.contains(r"[^\x00-\x7F]", regex=True).any()


def test_recidive_strictement_identique_a_l_originale():
    """J85 doit rester la copie exacte de J60 (mesure mémoire T1 vs T2)."""
    first, second = _anomaly("nulls_j60"), _anomaly("nulls_j85_recidive")
    assert second["recidive_of"] == first["id"]
    assert second["table"] == first["table"]
    assert second["params"] == first["params"]
