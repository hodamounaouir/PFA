"""Verrou 1 (phase 1.4) : le rejeu est déterministe.

Deux exécutions de data.replay sur le même jour produisent des fichiers
identiques à l'octet près — condition pour que ground_truth.yaml reste vrai
quel que soit le moment où l'on régénère les batchs.
"""

import hashlib
from pathlib import Path

import pytest

from data import config, replay

pytestmark = pytest.mark.skipif(
    not config.OLIST_DIR.exists(),
    reason="dataset Olist absent (téléchargement manuel, cf. ADR 009)",
)

# Un jour ordinaire de la fenêtre, sans anomalie prévue
DAY = "2018-03-10"


def _folder_hashes(folder: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.glob("*.csv"))
    }


def test_deux_rejeux_produisent_les_memes_octets():
    folder = config.INCOMING_DIR / DAY

    replay.main(["--day", DAY])
    first = _folder_hashes(folder)

    replay.main(["--day", DAY])
    second = _folder_hashes(folder)

    assert first, "aucun fichier produit"
    assert first == second
