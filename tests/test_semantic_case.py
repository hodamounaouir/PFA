"""Requête témoin du fil rouge sémantique (phase 1.4, ADR 009).

Prouve que les variantes de casse/accent de São Paulo provoquent un double
comptage mesurable dans tout agrégat par ville sur `geolocation`.
Ce test est la preuve permanente que le cas est RÉEL (non injecté).
"""

from pathlib import Path

import pandas as pd
import pytest

GEOLOCATION_CSV = (
    Path(__file__).resolve().parent.parent / "data" / "olist" / "olist_geolocation_dataset.csv"
)

pytestmark = pytest.mark.skipif(
    not GEOLOCATION_CSV.exists(),
    reason="dataset Olist absent (téléchargement manuel, cf. ADR 009)",
)


@pytest.fixture(scope="module")
def cities() -> pd.Series:
    return pd.read_csv(GEOLOCATION_CSV, usecols=["geolocation_city"])["geolocation_city"]


def test_variantes_sao_paulo_presentes(cities):
    counts = cities.value_counts()
    assert counts["sao paulo"] > 100_000
    assert counts["são paulo"] > 20_000


def test_agregat_par_ville_eclate_sao_paulo(cities):
    """La requête témoin : GROUP BY ville, sans puis avec normalisation."""
    naive = cities.value_counts()

    normalized = (
        cities.str.normalize("NFKD")
        .str.encode("ascii", errors="ignore")
        .str.decode("ascii")
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
        .value_counts()
    )

    # Sans normalisation, le total de São Paulo est éclaté sur plusieurs lignes :
    # la ligne 'sao paulo' seule sous-compte d'au moins 15 %.
    assert naive["sao paulo"] < normalized["sao paulo"] * 0.85

    # Après normalisation, les variantes fusionnent (au moins 20 000 lignes récupérées)
    ecart = normalized["sao paulo"] - naive["sao paulo"]
    assert ecart > 20_000
