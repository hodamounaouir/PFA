"""La voie **unique** de reprise (phase 6.1).

`scripts/decide.py` et les boutons Streamlit passent tous deux par
`agent/hitl.py`. Ce n'est pas un souci d'élégance : une seconde voie de reprise
serait une **seconde façon de contourner P3**, et la garantie « aucun chemin
n'atteint `apply` sans approbation » ne vaudrait plus que pour les chemins qu'on
a testés.
"""

import pytest

from agent.hitl import (
    AUCUNE_PROPOSITION,
    CORRECTION_SANS_APPROBATION,
    DECISION_INCONNUE,
    QUESTION_VIDE,
    proposition,
    questionner,
    trancher,
)
from agent.state import DECISION_APPROVED, DECISION_REJECTED, new_state
from conftest import PROFIL_FACTICE


@pytest.fixture
def en_pause(tmp_path):
    """Un run réellement arrêté sur `propose`, dans une base jetable."""
    from agent.graph import agent_persistant, thread

    db = tmp_path / "checkpoints.sqlite"
    PROFIL_FACTICE.deja_profiles.clear()
    PROFIL_FACTICE.colonnes = ["c0", "c1", "c2", "c3"]

    with agent_persistant(db) as app:
        app.invoke(
            new_state("olist", "bronze", "RAW.ORDERS", "2018-04-29"), thread("fil")
        )
    return db


# ---------------------------------------------------------------------------


def test_la_proposition_se_relit_avant_de_trancher(en_pause):
    """On ne demande à personne de trancher sans lui montrer ce qu'il tranche."""
    payload = proposition("fil", en_pause)
    assert payload["table"] == "RAW.ORDERS"
    assert payload["impact"]["resume"]


def test_trancher_fait_avancer_le_graphe(en_pause):
    resultat = trancher("fil", DECISION_REJECTED, par="hoda", db=en_pause)
    assert resultat["ok"]
    assert resultat["parcours"][-1] == "log"
    assert not resultat["en_attente"]


def test_injecter_sur_un_fil_sans_pause_est_refuse(en_pause):
    """⭐ Vérifié **avant** d'injecter.

    `Command(resume=…)` sur un fil qui n'attend rien relancerait le graphe
    **depuis le début** — donc referait un profilage et une détection — et
    l'humain croirait avoir tranché une proposition qui n'existait plus.

    Ce test manquait : un sabotage retirant la vérification passait inaperçu.
    """
    trancher(
        "fil", DECISION_REJECTED, par="hoda", db=en_pause
    )  # la pause est consommée

    second = trancher("fil", DECISION_APPROVED, par="hoda", db=en_pause)
    assert not second["ok"]
    assert second["code"] == AUCUNE_PROPOSITION


def test_un_fil_inconnu_est_refuse(tmp_path):
    resultat = trancher("jamais-vu", DECISION_REJECTED, db=tmp_path / "vide.sqlite")
    assert not resultat["ok"] and resultat["code"] == AUCUNE_PROPOSITION


def test_une_decision_inventee_est_refusee(en_pause):
    """On ne devine pas ce que l'appelant a voulu dire : `"oui"` n'est pas une
    approbation, et l'interpréter ouvrirait un chemin vers `apply`."""
    resultat = trancher("fil", "oui", db=en_pause)
    assert not resultat["ok"] and resultat["code"] == DECISION_INCONNUE


def test_une_correction_reecrite_exige_une_approbation(en_pause):
    """Amender un contrat ou refuser n'écrit rien dans les données : il n'y a
    donc **pas de SQL à réécrire**. L'accepter en silence laisserait croire le
    contraire à qui vient de taper une correction."""
    resultat = trancher(
        "fil", DECISION_REJECTED, fix_override="UPDATE t SET a = 1", db=en_pause
    )
    assert not resultat["ok"] and resultat["code"] == CORRECTION_SANS_APPROBATION


def test_une_question_ne_tranche_pas(en_pause):
    """La seule branche qui **remonte** dans le graphe : elle diffère au lieu de
    clore. Un humain à qui on ne laisse que trois boutons approuve vite et mal."""
    resultat = questionner("fil", "pourquoi ces valeurs ?", par="hoda", db=en_pause)
    assert resultat["ok"]
    assert resultat["questions_restantes"] < 10
    # La proposition attend de nouveau : rien n'a été tranché.
    assert proposition("fil", en_pause) is not None


def test_une_question_vide_n_en_est_pas_une(en_pause):
    resultat = questionner("fil", "   ", db=en_pause)
    assert not resultat["ok"] and resultat["code"] == QUESTION_VIDE


def test_le_module_ne_parle_a_personne():
    """⭐ Aucun `print`, aucun composant d'interface : ce module rend des
    dictionnaires. Un terminal et un navigateur n'ont pas les mêmes besoins, et
    mêler les deux obligerait l'un à dépendre de l'autre."""
    from pathlib import Path

    import agent.hitl as hitl

    source = Path(hitl.__file__).read_text(encoding="utf-8")
    assert "print(" not in source
    assert "streamlit" not in source
