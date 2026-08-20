"""Contrôle de l'impact estimé et de la file d'attente (phase 5.1).

L'impact est **le champ dont dépend la décision**. Sans lui, l'humain n'approuve
pas : il signe. C'est la faiblesse que `DESIGN.md` §5.3 anticipe (« et si
l'humain approuve sans lire ? »), et la raison pour laquelle ces tests portent
autant sur ce que l'impact **refuse d'affirmer** que sur ce qu'il calcule.
"""

import pytest

from agent.detect import ecart
from agent.graph import agent_persistant, propositions_en_attente, thread
from agent.impact import AVAL_NON_CALCULE, EXACT, MINIMUM, estimer, pour_un_ecart
from agent.nodes.propose import build_proposal
from agent.state import new_state
from conftest import PROFIL_FACTICE

PROFIL = {
    "row_count": 351,
    "columns": {
        "CUSTOMER_ID": {"null_count": 51},
        "PRIX": {"numeric_min": 1.0, "numeric_max": 8000.0},
        "VILLE": {
            "top": [
                {"value": "sao paulo", "count": 200},
                {"value": "são paulo", "count": 151},
                {"value": "recife", "count": 30},
            ]
        },
        "STATUT": {"top": [{"value": "ok", "count": 340}, {"value": "?", "count": 11}]},
    },
}


def ec(**kw):
    base = dict(
        famille="contrat",
        table="RAW.ORDERS",
        type="nulls_interdits",
        dama="completude",
        colonne="CUSTOMER_ID",
        observe=51,
    )
    base.update(kw)
    return ecart(**base)


# ===========================================================================
# Compter des lignes — et savoir quand on ne peut pas
# ===========================================================================


def test_des_nulls_se_comptent_exactement():
    detail = pour_un_ecart(ec(), PROFIL)
    assert detail["lignes_concernees"] == 51
    assert detail["precision"] == EXACT
    assert detail["part_du_lot"] == pytest.approx(51 / 351)


def test_des_doublons_se_comptent_exactement():
    detail = pour_un_ecart(ec(type="doublons", dama="unicite", doublons=62), PROFIL)
    assert detail["lignes_concernees"] == 62


def test_les_valeurs_hors_liste_se_comptent_par_leur_top_k():
    """Le top-K a déjà mesuré combien de lignes portent chaque valeur : on relit
    plutôt que de rouvrir une requête."""
    detail = pour_un_ecart(
        ec(type="valeur_non_admise", dama="validite", colonne="STATUT", observe=["?"]),
        PROFIL,
    )
    assert detail["lignes_concernees"] == 11


def test_une_borne_depassee_ne_dit_pas_combien_de_lignes():
    """⭐ La nuance qui évite une mauvaise décision.

    `numeric_max = 8000` prouve qu'une valeur sort des bornes, jamais **combien**
    de lignes. Annoncer « 1 ligne » quand on veut dire « au moins 1 » ferait
    refuser une anomalie majeure sur la foi d'un chiffre inventé.
    """
    detail = pour_un_ecart(
        ec(
            type="hors_bornes",
            dama="exactitude",
            colonne="PRIX",
            observe=[1.0, 8000.0],
            reference=[1, 100],
        ),
        PROFIL,
    )
    assert detail["lignes_concernees"] == 1
    assert detail["precision"] == MINIMUM
    assert (
        "au moins"
        in estimer(
            [
                ec(
                    type="hors_bornes",
                    dama="exactitude",
                    colonne="PRIX",
                    observe=[1.0, 8000.0],
                    reference=[1, 100],
                )
            ],
            PROFIL,
        )["resume"]
    )


def test_une_derive_ne_compte_pas_des_lignes_mais_un_deplacement():
    """Une métrique qui dérive ne désigne pas des lignes : c'est le lot qui a
    changé de forme. L'impact se lit dans la variation."""
    detail = pour_un_ecart(
        ec(
            famille="statistique",
            type="derive_statistique",
            colonne=None,
            observe=42.0,
            reference=351.0,
            metrique="row_count",
        ),
        PROFIL,
    )
    assert detail["lignes_concernees"] is None
    assert detail["variation"]["variation_relative"] == pytest.approx(-0.88, abs=0.01)


# ===========================================================================
# Le résumé — des nombres, jamais un adjectif
# ===========================================================================


def test_le_resume_porte_des_nombres_et_une_dimension():
    """« impact modéré » ne veut rien dire et ne se conteste pas. « 51 lignes
    sur 351 (14,5 %) » se vérifie, se discute, et se compare au run d'hier."""
    resume = estimer([ec()], PROFIL)["resume"]
    assert "51" in resume and "351" in resume and "14.5%" in resume
    assert "completude" in resume
    for flou in ("modéré", "faible", "important", "critique"):
        assert flou not in resume


def test_une_troncature_se_lit_en_une_ligne():
    """Deux nombres et un pourcentage disent en une ligne ce qu'un score z de
    −9,1 ne dit à personne."""
    resume = estimer(
        [
            ec(
                famille="statistique",
                type="derive_statistique",
                colonne=None,
                observe=42.0,
                reference=351.0,
                metrique="row_count",
            )
        ],
        PROFIL,
    )["resume"]
    assert "351 → 42" in resume and "-88.0%" in resume


def test_les_lignes_ne_sont_jamais_sommees():
    """⭐ La même ligne peut porter un null **et** un doublon.

    Sommer donnerait « 113 lignes sur 351 » ici, et pourrait dépasser la taille
    du lot dès que deux écarts se recouvrent — un impact de « 420 sur 351 »
    détruirait la confiance dans tout le reste de la proposition.
    """
    impact = estimer(
        [ec(), ec(type="doublons", dama="unicite", colonne="ID", doublons=62)], PROFIL
    )
    assert impact["ecart_le_plus_etendu"]["lignes_concernees"] == 62
    assert "113" not in impact["resume"]
    assert "+1 autre" in impact["resume"]


def test_l_en_tete_retient_le_plus_etendu_pas_le_premier():
    """C'est lui qui décide si la correction vaut d'être approuvée."""
    impact = estimer(
        [ec(type="doublons", dama="unicite", colonne="ID", doublons=3), ec()], PROFIL
    )
    assert impact["ecart_le_plus_etendu"]["colonne"] == "CUSTOMER_ID"


def test_tous_les_ecarts_restent_listes():
    impact = estimer([ec(), ec(type="doublons", dama="unicite", doublons=62)], PROFIL)
    assert len(impact["par_ecart"]) == 2


def test_aucun_ecart_le_dit():
    assert estimer([], PROFIL)["resume"] == "aucun écart soumis"


# ===========================================================================
# Ce que l'impact refuse de taire
# ===========================================================================


def test_l_effet_aval_est_annonce_comme_non_calcule():
    """⭐ Le silence serait le pire des choix.

    Un impact qui omettrait l'aval laisserait approuver une correction qui
    déplace un indicateur métier de moitié. Le dire coûte un champ ; le taire
    coûterait une mauvaise décision. Le calcul viendra avec le lineage (7.1).
    """
    impact = estimer([ec()], PROFIL)
    assert impact["aval"] == AVAL_NON_CALCULE
    assert "7.1" in impact["aval"]


def test_l_impact_ne_demande_aucune_source_de_donnees():
    """⭐ Aucune requête, et ce n'est pas de la paresse.

    Un nœud qui interrogerait la base au moment de proposer comparerait un lot
    mesuré tout à l'heure à une base lue maintenant : l'écart affiché ne
    correspondrait ni à ce qui a été détecté, ni à ce que l'humain verrait s'il
    regardait lui-même.
    """
    import inspect

    assert set(inspect.signature(estimer).parameters) == {"anomalies", "profil"}


# ===========================================================================
# La proposition, et la file qui la rend trouvable
# ===========================================================================


def test_la_proposition_porte_l_impact_calcule():
    etat = new_state("olist", "bronze", "RAW.ORDERS", "2018-04-29")
    etat["anomalies"] = [ec()]
    etat["profile"] = PROFIL
    proposition = build_proposal(etat)

    assert isinstance(proposition["impact"], dict)
    assert "51" in proposition["impact"]["resume"]
    assert "stub" not in str(proposition["impact"])


def test_la_file_rend_trouvable_un_run_mis_en_pause(tmp_path):
    """⭐ Sans elle, un run mis en pause par Airflow à 3 h du matin n'existe pour
    personne : il faut déjà connaître son `thread_id` pour le retrouver, donc
    savoir qu'il existe."""
    db = tmp_path / "checkpoints.sqlite"
    PROFIL_FACTICE.colonnes = ["c0", "c1", "c2", "c3"]

    with agent_persistant(db) as app:
        app.invoke(
            new_state("olist", "bronze", "RAW.ORDERS", "2018-04-29"),
            thread("olist|RAW.ORDERS|2018-04-29"),
        )

    attente = propositions_en_attente(db)
    assert [p["thread_id"] for p in attente] == ["olist|RAW.ORDERS|2018-04-29"]
    assert attente[0]["table"] == "RAW.ORDERS"
    assert attente[0]["anomalies"] == 1
    assert attente[0]["resume"], "l'impact doit permettre de choisir laquelle traiter"


def test_un_run_termine_ne_reste_pas_dans_la_file(tmp_path):
    """Une file qui garderait les runs tranchés deviendrait illisible en une
    semaine — et on cesserait de la regarder."""
    db = tmp_path / "checkpoints.sqlite"
    PROFIL_FACTICE.colonnes = ["c0"]  # aucune collision : le run va jusqu'au bout

    with agent_persistant(db) as app:
        app.invoke(
            new_state("olist", "bronze", "RAW.ORDERS", "2018-04-29"), thread("termine")
        )

    assert propositions_en_attente(db) == []


def test_la_file_est_vide_sans_checkpoint(tmp_path):
    assert propositions_en_attente(tmp_path / "rien.sqlite") == []
