"""Contrôle d'`apply` borné et de `validate` réel (phase 5.3).

`apply` est **le seul nœud du graphe qui écrit dans les données** — un sur huit.
Tout ce qui le borne se teste ici : les garde-fous qui valent pour tout le monde,
l'unique exception DDL, et le fait qu'aucune écriture ne parte quand l'un d'eux
se déclenche.

`validate`, lui, répond à une question que `apply` ne peut pas poser : la
correction a-t-elle eu **l'effet attendu** ? Exécuter une requête sans erreur ne
prouve que sa syntaxe.
"""

import copy

import pytest

from agent.nodes import apply, validate
from agent.nodes.validate import VALIDATION_ECHEC, VALIDATION_OK
from agent.state import DECISION_APPROVED, new_state
from conftest import PROFIL_FACTICE, REFERENCES

ECART_NULLS = {
    "famille": "contrat",
    "table": "RAW.ORDERS",
    "colonne": "COL",
    "type": "nulls_interdits",
    "observe": 51,
    "reference": 0,
    "ampleur": 0.14,
    "dama": "completude",
    "details": {},
}
ECART_RENOMMAGE = {
    "famille": "inventaire",
    "table": "RAW.ORDERS",
    "colonne": None,
    "type": "renommage_probable",
    "observe": "RAW.COMMANDES",
    "reference": "RAW.ORDERS",
    "ampleur": None,
    "dama": "coherence",
    "details": {},
}


def etat(fix, anomalies=None, **surcharges):
    state = new_state("olist", "bronze", "RAW.ORDERS", "2018-04-29")
    state["anomalies"] = anomalies if anomalies is not None else [ECART_NULLS]
    state["profile"] = {"row_count": 351, "columns": {"COL": {"null_count": 51}}}
    state["diagnosis"] = {"root_cause": "?", "proposed_fix": fix}
    state["human_decision"] = DECISION_APPROVED
    state["decided_by"] = "hoda"
    state.update(surcharges)
    return state


# ===========================================================================
# apply — les garde-fous qui valent pour TOUT LE MONDE
# ===========================================================================


def test_une_correction_hors_de_la_table_diagnostiquee_est_refusee():
    """Un diagnostic sur `RAW.ORDERS` n'a aucune raison d'écrire dans un mart :
    c'est soit une hallucination, soit bien pire."""
    resultat = apply(etat("UPDATE MARTS.FCT_DAILY_SALES SET x = NULL WHERE y"))
    assert resultat["applied_fix"] is None
    assert REFERENCES.corrections == [], "une écriture est partie malgré le refus"


def test_un_mot_cle_destructeur_est_refuse():
    resultat = apply(etat("DROP TABLE RAW.ORDERS"))
    assert resultat["applied_fix"] is None
    assert any("DROP" in r for r in resultat["logs"][0]["refus"])


def test_ces_garde_fous_valent_AUSSI_pour_le_SQL_de_l_humain():
    """⭐ La différence avec P6, et elle est voulue.

    P6 contraint l'agent seul — l'humain a l'autorité d'affirmer une valeur.
    Mais « ne pas détruire » et « rester dans sa table » protègent de
    l'**accident**, pas du jugement : ils s'appliquent aux deux.
    """
    resultat = apply(etat("UPDATE t SET a = NULL WHERE b", fix_override="DROP TABLE x"))
    assert resultat["applied_fix"] is None
    assert REFERENCES.corrections == []


def test_une_approbation_sans_correction_n_ecrit_rien():
    """Le diagnostic n'a rien proposé (LLM en panne) et l'humain a approuvé un
    vide. On le dit plutôt que d'écrire `NULL`."""
    resultat = apply(etat(None))
    assert resultat["applied_fix"] is None
    assert REFERENCES.corrections == []


# ===========================================================================
# apply — l'unique exception DDL (ADR 010, décision 14)
# ===========================================================================


def test_restaurer_un_nom_de_table_est_autorise():
    """⭐ La seule écriture de l'agent qui modifie un **schéma** et non un
    contenu, et elle n'est légitime que dans un cas : un renommage accidentel.

    P6 tient par construction — le nom restauré est **lu** dans le registre,
    jamais deviné. C'est l'inverse du cas « 8000 dans [1–100] », où aucune
    source ne dit ce que la valeur aurait dû être.
    """
    resultat = apply(
        etat("ALTER TABLE RAW.COMMANDES RENAME TO RAW.ORDERS", [ECART_RENOMMAGE])
    )
    assert resultat["applied_fix"]
    assert REFERENCES.corrections, "la restauration n'a pas été exécutée"


def test_le_DDL_est_refuse_sans_ecart_d_inventaire():
    """⭐ L'autorisation ne se donne pas parce que le SQL en a la forme, mais
    parce qu'un **fait constaté** l'appelle.

    Sans cette condition, il suffirait au modèle d'écrire un renommage pour
    franchir un garde-fou qui existe précisément pour l'en empêcher.
    """
    resultat = apply(etat("ALTER TABLE RAW.COMMANDES RENAME TO RAW.ORDERS"))
    assert resultat["applied_fix"] is None


def test_le_DDL_est_refuse_vers_une_autre_table():
    """L'exception porte sur la **cible** : elle doit être la table déclarée."""
    resultat = apply(
        etat("ALTER TABLE RAW.COMMANDES RENAME TO RAW.AUTRE", [ECART_RENOMMAGE])
    )
    assert resultat["applied_fix"] is None


def test_l_exception_ne_couvre_pas_les_autres_DDL():
    resultat = apply(etat("ALTER TABLE RAW.ORDERS DROP COLUMN x", [ECART_RENOMMAGE]))
    assert resultat["applied_fix"] is None


# ===========================================================================
# apply — l'écriture et son comptage
# ===========================================================================


def test_une_correction_legitime_est_executee_et_comptee():
    """Le comptage n'est pas de l'ornement : « 51 lignes affectées » est ce qui
    permet de vérifier, après coup, que la correction a fait ce qu'elle
    annonçait."""
    resultat = apply(etat("UPDATE RAW.ORDERS SET COL = NULL WHERE COL IS NULL"))

    assert resultat["applied_fix"]
    entree = resultat["logs"][0]
    assert entree["lignes_affectees"] == 51
    assert (entree["lignes_avant"], entree["lignes_apres"]) == (351, 351)


def test_le_lot_est_transmis_au_comptage():
    """Compter la table entière au lieu du lot dirait « 20 926 lignes » là où
    l'humain attend « 351 » — et la comparaison avant/après perdrait son sens."""
    apply(etat("UPDATE RAW.ORDERS SET COL = NULL WHERE COL IS NULL"))
    assert REFERENCES.corrections[0][2] == "2018-04-29"


def test_une_ecriture_qui_echoue_remonte():
    """Une panne d'écriture n'est pas un refus : elle doit se voir. La
    transaction du connecteur garantit qu'elle n'a rien laissé derrière elle."""
    REFERENCES.ecriture_leve = True
    with pytest.raises(RuntimeError):
        apply(etat("UPDATE RAW.ORDERS SET COL = NULL WHERE COL IS NULL"))


def test_apply_ne_modifie_pas_l_etat_recu():
    state = etat("UPDATE RAW.ORDERS SET COL = NULL WHERE COL IS NULL")
    avant = copy.deepcopy(state)
    apply(state)
    assert state == avant


# ===========================================================================
# validate — on re-mesure, on ne croit pas sur parole
# ===========================================================================


def etat_a_verifier(**surcharges):
    state = new_state("olist", "bronze", "RAW.ORDERS", "2018-04-29")
    PROFIL_FACTICE.deja_profiles.clear()
    PROFIL_FACTICE.colonnes = ["c0", "c1", "c2", "c3"]
    fiche = PROFIL_FACTICE.invoke({"table": "RAW.ORDERS", "batch_id": "2018-04-29"})
    state["profile"] = fiche
    state["anomalies"] = [
        {
            "famille": "semantique",
            "table": "RAW.ORDERS",
            "colonne": "c1",
            "type": "collision_semantique",
            "observe": ["sao paulo", "são paulo"],
            "reference": "sao paulo",
            "ampleur": 351,
            "dama": "coherence",
            "details": {},
        }
    ]
    state.update(surcharges)
    return state


def test_une_correction_efficace_est_validee():
    resultat = validate(etat_a_verifier())
    assert resultat["validation"]["status"] == VALIDATION_OK
    assert resultat["logs"][0]["ecarts_restants"] == 0


def test_un_ecart_toujours_present_fait_echouer_la_validation():
    """⭐ Exécuter une requête sans erreur ne prouve que sa syntaxe.

    Un `validate` qui croirait `apply` sur parole confirmerait que la requête a
    tourné, pas qu'elle a eu l'effet attendu — c'est exactement la différence
    entre « corrigé » et « cru corrigé ».
    """
    PROFIL_FACTICE.guerit = False  # la correction n'a rien changé
    resultat = validate(etat_a_verifier())

    assert resultat["validation"]["status"] == VALIDATION_ECHEC
    assert resultat["validation"]["raison"]


def test_le_statut_d_echec_appelle_un_humain_pas_une_re_tentative():
    """⚠️ Le nom vient du cahier et il est explicite à dessein : *manual review*.

    Un agent qui réessaie tout seul écrirait deux fois sans qu'un humain ait
    revu quoi que ce soit — alors même que la première écriture vient d'échouer
    à faire ce qu'elle promettait.
    """
    assert VALIDATION_ECHEC == "failed_manual_review"


def test_une_table_disparue_entre_temps_fait_echouer():
    PROFIL_FACTICE.absente = True
    resultat = validate(etat_a_verifier())
    assert resultat["validation"]["status"] == VALIDATION_ECHEC
    assert "disparu" in resultat["validation"]["raison"]


def test_la_comparaison_se_fait_par_signature():
    """Comparer par signature plutôt que par valeur traite les cinq familles
    d'un coup : ce qu'on veut savoir n'est pas « la valeur a-t-elle changé »
    mais « l'écart existe-t-il encore »."""
    PROFIL_FACTICE.guerit = False
    restantes = validate(etat_a_verifier())["logs"][0]["restantes"]
    assert restantes and "collision_semantique" in restantes[0]


def test_validate_ne_modifie_pas_l_etat_recu():
    state = etat_a_verifier()
    avant = copy.deepcopy(state)
    validate(state)
    assert state == avant
