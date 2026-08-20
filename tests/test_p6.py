"""L'invariant P6 : ne jamais inventer une valeur (phase 5.2).

Face à `8000` dans une colonne à [1–100], l'agent **ne peut pas savoir** s'il
s'agit de 80,00 € saisis en centimes, d'une faute de frappe, ou d'une vraie
grosse commande. Proposer « remplacer 8000 par 80 », c'est fabriquer de la
donnée qui n'a jamais existé — et une donnée fabriquée est pire qu'une donnée
fausse : la fausse se voit, la fabriquée est cohérente.

Le test central est `test_P4_une_valeur_inventee_est_refusee_MEME_approuvee` :
c'est la preuve qui donne son sens au garde-fou. Une règle qui cède devant un
« oui » ne protège de rien.
"""

import copy

import pytest

from agent.corrections import (
    EXCLURE,
    GESTES,
    ISOLER,
    NORMALISER,
    controler,
    correction_par_defaut,
)
from agent.detect import ecart
from agent.nodes import apply
from agent.state import DECISION_APPROVED, new_state

PROFIL = {
    "row_count": 351,
    "columns": {
        "VILLE": {
            "top": [
                {"value": "sao paulo", "count": 200},
                {"value": "são paulo", "count": 151},
            ]
        },
        "PRIX": {"numeric_min": 1.0, "numeric_max": 8000.0},
    },
}

COLLISION = ecart(
    "semantique",
    "RAW.G",
    type="collision_semantique",
    dama="coherence",
    colonne="VILLE",
    observe=["sao paulo", "são paulo"],
    reference="sao paulo",
)
OUTLIER = ecart(
    "contrat",
    "RAW.O",
    type="hors_bornes",
    dama="exactitude",
    colonne="PRIX",
    observe=[1.0, 8000.0],
    reference=[1, 100],
)


# ===========================================================================
# Ce qui est autorisé — et pourquoi le fil rouge en fait partie
# ===========================================================================


def test_normaliser_vers_une_ecriture_deja_presente_est_autorise():
    """⭐ Sans ce cas, P6 interdirait la correction que le projet existe pour
    montrer.

    Ce qui distingue `são paulo` → `sao paulo` d'une invention est vérifiable :
    **la valeur écrite est déjà dans la colonne**. On ne crée rien, on choisit
    parmi ce qui existe.
    """
    sql = "UPDATE t SET ville = 'sao paulo' WHERE ville = 'são paulo'"
    assert controler(sql, [COLLISION], PROFIL) == []


def test_mettre_a_null_est_autorise():
    """On efface, on n'invente pas."""
    assert (
        controler("UPDATE t SET prix = NULL WHERE prix > 100", [OUTLIER], PROFIL) == []
    )


def test_marquer_une_autre_colonne_est_autorise():
    """Écrire dans une colonne de quarantaine, c'est isoler : la donnée
    diagnostiquée n'est pas touchée."""
    sql = "UPDATE t SET quarantaine = TRUE, motif = 'hors bornes' WHERE prix > 100"
    assert controler(sql, [OUTLIER], PROFIL) == []


def test_une_correction_sans_affectation_ne_declenche_rien():
    """Un `DELETE` borné ou un `INSERT` en quarantaine n'invente aucune valeur —
    ils ont leurs propres garde-fous, ce n'est pas le rôle de P6."""
    assert controler("DELETE FROM t WHERE prix > 100", [OUTLIER], PROFIL) == []
    assert controler(None, [OUTLIER], PROFIL) == []


# ===========================================================================
# Ce qui est refusé
# ===========================================================================


def test_une_valeur_jamais_observee_est_refusee():
    """Le cas d'école : `80` n'a jamais été vu dans la colonne. L'agent le
    fabriquerait."""
    refus = controler("UPDATE t SET prix = 80 WHERE prix = 8000", [OUTLIER], PROFIL)
    assert refus and "jamais été observée" in refus[0]


def test_deviner_une_unite_est_refuse():
    """`prix / 100` suppose que la saisie était en centimes. C'est une hypothèse
    sur l'intention, pas une correction — et rien dans la donnée ne la soutient."""
    refus = controler(
        "UPDATE t SET prix = prix / 100 WHERE prix > 100", [OUTLIER], PROFIL
    )
    assert refus and "n'est pas connu au moment de décider" in refus[0]


def test_transformer_toute_la_colonne_est_refuse():
    """⭐ Le refus qui surprend, et qui est pourtant le bon.

    `LOWER(city)` n'invente rien, mais ce n'est pas une correction : c'est une
    transformation appliquée **aussi aux lignes saines**. Sa place est dans le
    modèle Silver, où elle sera relue, versionnée et testée — pas dans un
    `UPDATE` ponctuel dont personne ne saura six mois plus tard qu'il a tourné.

    *L'agent corrige des lignes ; dbt transforme des colonnes.*
    """
    assert controler("UPDATE t SET ville = LOWER(ville) WHERE 1=1", [COLLISION], PROFIL)


def test_une_valeur_du_contrat_mais_jamais_vue_reste_une_invention():
    """Un contrat dit ce qui **devrait** être, pas ce qui **est**. Écrire une
    valeur admise mais jamais observée resterait une invention."""
    admise = ecart(
        "contrat",
        "RAW.O",
        type="valeur_non_admise",
        dama="validite",
        colonne="VILLE",
        observe=["?"],
        reference=["sao paulo", "brasilia"],
    )
    # `brasilia` est dans le contrat, mais absente du top-K de la colonne.
    assert controler(
        "UPDATE t SET ville = 'brasilia' WHERE ville = '?'", [admise], PROFIL
    )


# ===========================================================================
# ⭐ P4 — la preuve : le refus survit à l'approbation
# ===========================================================================


def etat_approuve(fix, **surcharges):
    etat = new_state("olist", "bronze", "RAW.O", "2018-04-29")
    etat["anomalies"] = [OUTLIER]
    etat["profile"] = PROFIL
    etat["diagnosis"] = {"root_cause": "?", "proposed_fix": fix}
    etat["human_decision"] = DECISION_APPROVED
    etat["decided_by"] = "hoda"
    etat.update(surcharges)
    return etat


def test_P4_une_valeur_inventee_est_refusee_MEME_approuvee():
    """⭐⭐ LA preuve de la phase 5.2.

    Le garde-fou s'applique **après** l'approbation, et c'est tout son intérêt :
    un humain peut approuver sans lire. Une règle qui cède devant un « oui » ne
    protège de rien.
    """
    resultat = apply(etat_approuve("UPDATE t SET prix = 80 WHERE prix = 8000"))

    assert resultat["applied_fix"] is None, "la correction a été appliquée !"
    assert "REFUSÉE" in resultat["logs"][0]["message"]
    assert resultat["logs"][0]["refus"]


def test_le_refus_ne_tue_pas_le_run():
    """On ne lève pas : ce n'est pas un bug de câblage mais un cas métier — le
    modèle a proposé quelque chose d'inacceptable. Le run doit se terminer par
    `log`, sinon la trace de ce refus serait perdue au moment précis où elle est
    la plus instructive."""
    resultat = apply(etat_approuve("UPDATE t SET prix = 80 WHERE prix = 8000"))
    assert "logs" in resultat and resultat["logs"]


def test_le_refus_dit_le_recours():
    """Un refus sans issue laisse l'humain bloqué. Il doit apprendre, dans le
    même message, que son autorité n'est pas soumise à P6."""
    entree = apply(etat_approuve("UPDATE t SET prix = 80 WHERE prix = 8000"))["logs"][0]
    assert "--fix" in entree["recours"]


def test_une_correction_acceptable_passe():
    """Le garde-fou doit laisser passer ce qui est légitime, sinon il ne prouve
    rien : un refus universel serait indistinguable d'un `apply` cassé."""
    resultat = apply(etat_approuve("UPDATE t SET prix = NULL WHERE prix > 100"))
    assert resultat["applied_fix"] == "UPDATE t SET prix = NULL WHERE prix > 100"


def test_P6_ne_contraint_PAS_l_humain():
    """⭐ La nuance décidée dès la phase 3.1, et tenue ici.

    « L'agent ne peut pas savoir si 8000 valait 80 ; toi, tu peux avoir appelé
    le fournisseur. Tu as l'autorité pour affirmer une valeur, lui ne l'a pas. »
    Les autres garde-fous restent pour les deux — ils protègent de l'accident,
    pas du jugement.
    """
    resultat = apply(
        etat_approuve(
            "UPDATE t SET prix = 999 WHERE prix = 8000",
            fix_override="UPDATE t SET prix = 80 WHERE prix = 8000",
        )
    )
    assert resultat["applied_fix"] == "UPDATE t SET prix = 80 WHERE prix = 8000"


def test_apply_ne_modifie_pas_l_etat_recu():
    etat = etat_approuve("UPDATE t SET prix = 80 WHERE prix = 8000")
    avant = copy.deepcopy(etat)
    apply(etat)
    assert etat == avant


# ===========================================================================
# Le geste sûr proposé à la place
# ===========================================================================


def test_le_defaut_sur_un_outlier_est_isoler_et_exclure():
    """⭐ La seule réponse qui ne suppose rien sur ce que la valeur aurait dû
    être : la donnée brute reste en Bronze pour l'audit, et l'agrégat cesse
    d'être faux. Les deux moitiés du problème, sans en inventer une."""
    defaut = correction_par_defaut(OUTLIER)
    assert defaut["gestes"] == [ISOLER, EXCLURE]
    assert "remplacer" in defaut["interdit"]


def test_le_defaut_sur_une_collision_est_normaliser():
    assert correction_par_defaut(COLLISION)["gestes"] == [NORMALISER]


def test_le_defaut_explique_pourquoi():
    """Un refus qu'on ne comprend pas se contourne. Un refus expliqué se
    respecte — ou se conteste, ce qui est aussi bien."""
    assert "rien ne permet de trancher" in correction_par_defaut(OUTLIER)["pourquoi"]


@pytest.mark.parametrize("geste", GESTES)
def test_chaque_geste_autorise_est_explique(geste):
    """Le vocabulaire part sous les yeux de l'humain dans la proposition : un
    nom de constante ne lui apprendrait rien."""
    assert len(GESTES[geste]) > 20
