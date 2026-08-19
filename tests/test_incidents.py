"""Contrôle de la mémoire de l'agent (phase 4.4) — signature, silence, journal.

La pièce centrale est la **signature d'anomalie** : c'est elle qui définit « la
même anomalie », donc ce que l'agent retrouve et ce sur quoi il se tait. Sa
granularité est un compromis, et ces tests le figent aux deux bouts — trop large
l'agent devient aveugle, trop étroite la mémoire ne sert jamais.

Aucun test ne touche à une base : la signature et le filtre sont des fonctions
pures, le journal est éprouvé contre le double de `conftest.py`.
"""

import pytest

from agent.detect import silence
from agent.detect import ecart
from agent.incidents import SANS_AMPLEUR, depuis_texte, octave, signature, texte
from agent.sql_guard import controler
from agent.state import DECISION_APPROVED, DECISION_REJECTED
from agent.tools.read_past_incidents import incidents_similaires, resumer


def anomalie(ampleur=0.30, colonne="CUSTOMER_ID", type="nulls_interdits"):
    return ecart(
        "contrat",
        "RAW.ORDERS",
        type=type,
        dama="completude",
        colonne=colonne,
        ampleur=ampleur,
    )


def incident(decision, signatures, **extra):
    base = {
        "incident_id": "i1",
        "batch_id": "2018-04-29",
        "human_decision": decision,
        "signatures": signatures,
        "diagnosis": {"root_cause": "cause", "proposed_fix": "SQL"},
        "decided_by": "hoda",
    }
    base.update(extra)
    return base


# ===========================================================================
# L'ordre de grandeur — le 4ᵉ terme, celui dont tout dépend
# ===========================================================================


def test_une_variation_mineure_garde_la_meme_signature():
    """Trop étroite, la mémoire ne servirait jamais : 30 % et 35 % de nulls sont
    la **même** anomalie, et le J85 doit retrouver le J60."""
    assert octave(0.30) == octave(0.35)


def test_un_changement_d_echelle_change_la_signature():
    """⭐ Trop large, l'agent devient aveugle.

    Un refus sur « 30 % de nulls, c'est normal » ne doit pas le faire taire à
    85 %. C'est l'exigence explicite de PROGRESS §4.4, et la raison pour
    laquelle l'octave a été préférée à la décade — `floor(log10)` mettrait les
    deux dans le même seau.
    """
    assert octave(0.30) != octave(0.85)


def test_l_echelle_vaut_pour_les_taux_comme_pour_les_decomptes():
    """Logarithmique donc sans unité : la même règle sur [0, 1] et sur [0, 10⁶]."""
    assert octave(51) != octave(5100)
    assert octave(0.001) != octave(0.5)


@pytest.mark.parametrize("valeur", [0.0, 1e-12, -0.0])
def test_une_ampleur_nulle_ne_part_pas_a_l_infini(valeur):
    """`log2(0)` vaut -inf : un taux de 10⁻¹² n'est pas « mille fois moins
    grave » qu'un taux de 10⁻⁹, c'est zéro."""
    assert octave(valeur) == "0"


def test_une_anomalie_sans_ampleur_a_un_seau_explicite():
    """Une table est absente ou elle ne l'est pas — il n'y a pas de « plus ou
    moins ». Le seau est nommé plutôt que `None`, sinon deux signatures sans
    ampleur ne se compareraient pas égales."""
    assert octave(None) == SANS_AMPLEUR
    sans = ecart("inventaire", "RAW.ORDERS", type="table_absente", dama="completude")
    assert signature(sans)[3] == SANS_AMPLEUR


def test_la_signature_porte_ses_quatre_termes():
    assert signature(anomalie()) == (
        "RAW.ORDERS",
        "CUSTOMER_ID",
        "nulls_interdits",
        "-2",
    )


def test_la_signature_se_relit():
    """Elle finit dans `INCIDENTS` et dans l'écran « signatures en silence » :
    une signature qu'on ne peut pas redécouper est une signature qu'on ne peut
    pas expliquer à l'humain qui la voit."""
    sig = signature(anomalie())
    assert depuis_texte(texte(sig)) == sig


def test_le_separateur_ne_se_confond_pas_avec_le_contenu():
    """Le point apparaît dans `RAW.ORDERS`, le tiret dans les octaves négatives."""
    brut = texte(signature(anomalie()))
    assert brut.count("|") == 3


# ===========================================================================
# Le filtre de silence
# ===========================================================================


def test_une_signature_refusee_n_est_plus_soumise():
    refuse = incident(DECISION_REJECTED, [texte(signature(anomalie()))])
    retenus, tus = silence.filtrer([anomalie()], [refuse])
    assert retenus == []
    assert len(tus) == 1


def test_l_ecart_tu_est_rendu_et_non_supprime():
    """⭐ Garde-fou anti-cécité. Rendre les deux listes plutôt que d'amputer :
    un appelant qui ne recevrait que les écarts retenus ne pourrait pas
    journaliser les autres, et l'agent deviendrait progressivement muet sans que
    personne s'en aperçoive — invisible **parce qu'**il ne dit plus rien."""
    refuse = incident(DECISION_REJECTED, [texte(signature(anomalie()))])
    _, tus = silence.filtrer([anomalie()], [refuse])
    assert tus[0]["colonne"] == "CUSTOMER_ID"


def test_l_agent_reparle_si_l_ampleur_change_d_echelle():
    """⭐⭐ La raison d'être du 4ᵉ terme.

    Refus à 30 % ; le lot suivant en porte 85 %. Ce n'est plus la même
    signature, donc l'écart repart en décision. Sans l'octave, l'agent se
    tairait sur une anomalie trois fois plus grave.
    """
    refuse = incident(DECISION_REJECTED, [texte(signature(anomalie(0.30)))])
    retenus, tus = silence.filtrer([anomalie(0.85)], [refuse])
    assert len(retenus) == 1 and tus == []


def test_seules_les_decisions_humaines_font_taire():
    """R5. Un incident sans décision n'a rien tranché — run en pause, ou clos
    sans réponse. Le lire comme un refus ferait taire l'agent sur une question
    que **personne n'a jamais lue**."""
    sans_decision = incident(None, [texte(signature(anomalie()))])
    retenus, tus = silence.filtrer([anomalie()], [sans_decision])
    assert len(retenus) == 1 and tus == []


def test_une_approbation_ne_fait_pas_taire():
    """Approuver, c'est corriger — pas décréter que l'anomalie est normale.
    La confondre avec un refus rendrait l'agent muet sur ce qu'il vient de
    réparer, donc incapable de constater une récidive."""
    approuve = incident(DECISION_APPROVED, [texte(signature(anomalie()))])
    retenus, _ = silence.filtrer([anomalie()], [approuve])
    assert len(retenus) == 1


def test_sans_antecedent_tout_passe():
    retenus, tus = silence.filtrer([anomalie()], [])
    assert len(retenus) == 1 and tus == []


# ===========================================================================
# La mémoire — l'autre sens (objectif O7)
# ===========================================================================


def test_l_incident_du_J60_est_retrouve_au_J85():
    """⭐ L'objectif O7 en une ligne : la récidive cite le précédent."""
    passe = incident(
        DECISION_APPROVED, [texte(signature(anomalie(0.30)))], batch_id="2018-04-29"
    )
    trouves = incidents_similaires([passe], [anomalie(0.30)])
    assert [i["batch_id"] for i in trouves] == ["2018-04-29"]


def test_un_incident_sans_rapport_n_est_pas_cite():
    autre = incident(DECISION_APPROVED, [texte(signature(anomalie(colonne="AUTRE")))])
    assert incidents_similaires([autre], [anomalie()]) == []


def test_ce_qui_part_au_modele_est_enumere_champ_par_champ():
    """⚠️ Frontière R2. Un incident porte le JSON complet des anomalies passées,
    donc potentiellement des valeurs de données. On ne fait pas confiance à la
    forme stockée : on choisit ce qui sort."""
    complet = incident(
        DECISION_APPROVED,
        ["sig"],
        anomalies=[{"observe": ["sao paulo", "são paulo"], "secret": "x"}],
    )
    resume = resumer([complet])[0]
    assert set(resume) == {
        "lot",
        "cause_racine",
        "correction_proposee",
        "decision_humaine",
        "decide_par",
    }
    assert "sao paulo" not in str(resume)


def test_la_memoire_est_bornee():
    """Un prompt qui grossit à chaque run finit par coûter plus cher que
    l'incident qu'il explique."""
    beaucoup = [incident(DECISION_APPROVED, ["s"]) for _ in range(10)]
    assert len(resumer(beaucoup)) == 3


# ===========================================================================
# Le garde-fou SQL — première ligne de défense
# ===========================================================================


@pytest.mark.parametrize(
    "sql,motif",
    [
        ("DROP TABLE RAW.ORDERS", "DROP"),
        ("TRUNCATE TABLE RAW.ORDERS", "TRUNCATE"),
        ("ALTER TABLE RAW.ORDERS ADD COLUMN x INT", "ALTER"),
        ("DELETE FROM RAW.ORDERS", "WHERE"),
    ],
)
def test_les_formes_destructrices_sont_signalees(sql, motif):
    alertes = controler(sql, "RAW.ORDERS")
    assert alertes and any(motif in a for a in alertes)


def test_un_delete_borne_n_est_pas_refuse():
    """⚠️ `DELETE` n'est pas destructeur en soi — c'est `DELETE` **sans
    `WHERE`** qui vide une table. Les confondre refuserait la correction la plus
    naturelle qui soit : supprimer les lignes dupliquées d'un lot."""
    assert (
        controler("DELETE FROM RAW.ORDERS WHERE _batch_id = '2018-05-14'", "RAW.ORDERS")
        == []
    )


def test_une_table_etrangere_est_signalee():
    """Un modèle qui diagnostique `RAW.ORDERS` n'a aucune raison d'écrire dans un
    mart : c'est soit une hallucination, soit bien pire."""
    alertes = controler("UPDATE MARTS.FCT_DAILY_SALES SET x = 1 WHERE y", "RAW.ORDERS")
    assert any("étrangère" in a for a in alertes)


def test_une_correction_legitime_passe():
    assert (
        controler("UPDATE RAW.ORDERS SET city = NULL WHERE city = ''", "RAW.ORDERS")
        == []
    )


def test_l_absence_de_sql_n_est_pas_une_alerte():
    """Un diagnostic peut n'en proposer aucun — et ne rien proposer n'est pas
    proposer quelque chose de dangereux."""
    assert controler(None, "RAW.ORDERS") == []
    assert controler("", "RAW.ORDERS") == []
