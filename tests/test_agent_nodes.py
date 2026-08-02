"""Contrôle des nœuds de l'agent (phase 3.1), testés **isolément** (sans graphe).

C'est tout l'intérêt d'avoir des fonctions pures `AgentState -> dict` : on peut
vérifier chaque nœud sans compiler le graphe, sans checkpointer, sans Snowflake
et sans LLM.

⚠️ C'est **ici** que vivent les noms de colonnes, jamais dans `agent/`. Même
séparation que `ground_truth.yaml` : le dataset appartient au banc d'essai, pas
à l'agent. Un test branche un dataset de commandes, l'autre un dataset RH sans
aucun rapport — et le même nœud doit traiter les deux.

Ce fichier grandit d'un bloc à chaque nœud ajouté.
"""

import copy

import pytest

from agent.nodes import amend, apply, detect, diagnose, log, profile, propose, validate
from agent.nodes.amend import _version_suivante
from agent.nodes.validate import VALIDATION_OK
from agent.nodes.detect import STUB_NULL_THRESHOLD
from agent.nodes.propose import build_proposal
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    log_entry,
    new_state,
)

# Deux datasets volontairement étrangers l'un à l'autre.
SCHEMA_COMMANDES = [
    {"name": "order_id"},
    {"name": "customer_id"},
    {"name": "order_status"},
    {"name": "order_purchase_timestamp"},
]
SCHEMA_RH = [
    {"name": "matricule"},
    {"name": "departement"},
    {"name": "salaire_brut"},
]


def base_state(schema=None, table="RAW.ORDERS"):
    state = new_state(dataset="olist", layer="bronze", table=table, batch_id="2018-04-29")
    state["schema_history"] = schema or []
    return state


# --- Nœud 1/8 : profile ------------------------------------------------------


def test_profile_ne_produit_que_des_agregats():
    """Le profil ne doit jamais contenir de lignes brutes : le LLM les verrait."""
    fiche = profile(base_state(SCHEMA_COMMANDES))["profile"]
    assert set(fiche) == {"row_count", "columns"}
    assert isinstance(fiche["row_count"], int)


def test_profile_s_adapte_a_n_importe_quel_dataset():
    """LE test de portabilité : le même nœud, deux datasets sans rapport.

    Si un jour il devient rouge parce qu'un nom de colonne s'est glissé dans
    `agent/`, c'est que l'agent a cessé d'être portable.
    """
    commandes = profile(base_state(SCHEMA_COMMANDES))["profile"]
    rh = profile(base_state(SCHEMA_RH, table="HR.EMPLOYES"))["profile"]

    assert list(commandes["columns"]) == [c["name"] for c in SCHEMA_COMMANDES]
    assert list(rh["columns"]) == [c["name"] for c in SCHEMA_RH]


def test_profile_calcule_les_memes_metriques_partout():
    """Les métriques du stub sont indépendantes du type : valables pour toute colonne."""
    for schema in (SCHEMA_COMMANDES, SCHEMA_RH):
        for stats in profile(base_state(schema))["profile"]["columns"].values():
            assert set(stats) == {"null_rate", "distinct"}


def test_profile_sans_schema_reste_neutre():
    """Sans introspection, le stub retombe sur des noms qui n'évoquent aucun dataset."""
    colonnes = profile(base_state())["profile"]["columns"]
    assert all(nom.startswith("col_") for nom in colonnes)


def test_profile_ne_modifie_pas_l_etat_recu():
    """Fonction pure : le nœud retourne ses changements, il ne mute rien."""
    state = base_state(SCHEMA_COMMANDES)
    avant = copy.deepcopy(state)
    profile(state)
    assert state == avant


def test_profile_ecrit_une_ligne_de_journal_au_format_commun():
    entry = profile(base_state(SCHEMA_RH))["logs"][0]
    assert entry["node"] == "profile"
    assert entry["colonnes"] == 3
    assert set(log_entry("x", "y")) <= set(entry)  # ts + node + message garantis


# --- Nœud 2/8 : detect -------------------------------------------------------


def etat_avec_profil(colonnes: dict, table="RAW.ORDERS"):
    """Un état porteur d'un profil donné — ce que `profile` aurait produit."""
    state = base_state(table=table)
    state["profile"] = {"row_count": 351, "columns": colonnes}
    return state


def test_detect_ne_signale_rien_quand_tout_est_propre():
    """Le chemin « rien d'anormal » doit exister : c'est un des 4 du graphe."""
    state = etat_avec_profil(
        {"a": {"null_rate": 0.0, "distinct": 351}, "b": {"null_rate": 0.02, "distinct": 12}}
    )
    assert detect(state)["anomalies"] == []


def test_detect_signale_la_colonne_qui_depasse():
    state = etat_avec_profil(
        {
            "propre": {"null_rate": 0.0, "distinct": 351},
            "trouee": {"null_rate": 0.301, "distinct": 245},
        }
    )
    anomalies = detect(state)["anomalies"]
    assert len(anomalies) == 1
    assert anomalies[0]["colonne"] == "trouee"


def test_detect_produit_un_fait_chiffre_pas_un_jugement():
    """La forme de sortie est figée : les 4 familles devront toutes la produire.

    Aucun champ ne porte de verdict (« grave », « à corriger ») — seulement des
    mesures. Le jugement appartient à l'humain.
    """
    state = etat_avec_profil({"trouee": {"null_rate": 0.301, "distinct": 245}})
    ecart = detect(state)["anomalies"][0]

    assert set(ecart) == {"famille", "table", "colonne", "type", "observe", "reference", "dama"}
    assert ecart["observe"] == 0.301
    assert ecart["reference"] == STUB_NULL_THRESHOLD
    assert ecart["table"] == "RAW.ORDERS"


def test_detect_marche_sur_n_importe_quel_dataset():
    """Aucun nom de colonne n'est connu d'avance : l'écart est trouvé, pas su."""
    rh = detect(etat_avec_profil({"salaire_brut": {"null_rate": 0.4}}, "HR.EMPLOYES"))
    capteurs = detect(etat_avec_profil({"temperature_c": {"null_rate": 0.4}}, "IOT.MESURES"))

    assert rh["anomalies"][0]["colonne"] == "salaire_brut"
    assert capteurs["anomalies"][0]["colonne"] == "temperature_c"


def test_detect_supporte_un_profil_vide():
    """Robustesse : un lot vide ne doit pas faire exploser le graphe."""
    state = base_state()
    assert detect(state)["anomalies"] == []


def test_detect_s_enchaine_avec_profile():
    """Les deux nœuds bout à bout, comme dans le graphe."""
    state = base_state(SCHEMA_COMMANDES)
    state["profile"] = profile(state)["profile"]
    anomalies = detect(state)["anomalies"]

    # le stub de profile met des nulls sur la 2e colonne
    assert [a["colonne"] for a in anomalies] == [SCHEMA_COMMANDES[1]["name"]]


def test_detect_ne_modifie_pas_l_etat_recu():
    state = etat_avec_profil({"trouee": {"null_rate": 0.301}})
    avant = copy.deepcopy(state)
    detect(state)
    assert state == avant


def test_detect_ecrit_une_ligne_de_journal_au_format_commun():
    state = etat_avec_profil({"a": {"null_rate": 0.0}, "b": {"null_rate": 0.5}})
    entry = detect(state)["logs"][0]
    assert entry["node"] == "detect"
    assert entry["colonnes_examinees"] == 2
    assert set(log_entry("x", "y")) <= set(entry)


# --- Nœud 3/8 : diagnose -----------------------------------------------------


def etat_avec_ecart(colonne="col_trouee", table="RAW.ORDERS"):
    """Un état porteur d'un écart — ce que `detect` aurait produit."""
    state = base_state(table=table)
    state["anomalies"] = [
        {
            "famille": "statistique",
            "table": table,
            "colonne": colonne,
            "type": "nulls",
            "observe": 0.301,
            "reference": 0.0,
            "dama": "completude",
        }
    ]
    return state


def test_diagnose_produit_les_trois_champs_attendus():
    """Le contrat de sortie du LLM, figé dès le stub (étape 7 : forcé par Pydantic)."""
    diagnosis = diagnose(etat_avec_ecart())["diagnosis"]
    assert set(diagnosis) == {"root_cause", "proposed_fix", "explanation"}
    assert all(isinstance(v, str) and v for v in diagnosis.values())


def test_diagnose_parle_de_l_ecart_qu_il_a_recu():
    """Générique : il nomme la colonne trouvée par detect, il ne la connaît pas."""
    rh = diagnose(etat_avec_ecart("salaire_brut", "HR.EMPLOYES"))["diagnosis"]
    capteurs = diagnose(etat_avec_ecart("temperature_c", "IOT.MESURES"))["diagnosis"]

    assert "salaire_brut" in rh["root_cause"]
    assert "temperature_c" in capteurs["root_cause"]
    assert "HR.EMPLOYES" in rh["proposed_fix"]


def test_diagnose_propose_d_isoler_pas_de_deviner():
    """Règle « ne jamais inventer une valeur » (garde-fou dur dans apply, phase 5.2).

    Face à un écart, l'agent ne peut pas savoir quelle était la bonne valeur.
    Il isole, met à NULL ou exclut d'un agrégat — il ne substitue jamais.
    """
    fix = diagnose(etat_avec_ecart())["diagnosis"]["proposed_fix"]
    assert "isoler" in fix.lower()
    assert "sans modifier les valeurs" in fix.lower()


def test_diagnose_sans_ecart_ne_fabrique_pas_de_diagnostic():
    """Le graphe ne route pas ici sans écart, mais un nœud ne suppose rien.

    C'est aussi la forme qu'aura l'échec de parsing LLM à l'étape 7 :
    `diagnosis = None`, run terminé en « à traiter manuellement », sans exception.
    """
    result = diagnose(base_state())
    assert result["diagnosis"] is None
    assert result["logs"][0]["node"] == "diagnose"


def test_diagnose_ne_modifie_pas_l_etat_recu():
    state = etat_avec_ecart()
    avant = copy.deepcopy(state)
    diagnose(state)
    assert state == avant


def test_diagnose_ecrit_une_ligne_de_journal_au_format_commun():
    entry = diagnose(etat_avec_ecart())["logs"][0]
    assert entry["node"] == "diagnose"
    assert entry["anomalies"] == 1
    assert set(log_entry("x", "y")) <= set(entry)


def test_les_trois_noeuds_s_enchainent():
    """profile → detect → diagnose, comme dans le graphe."""
    state = base_state(SCHEMA_COMMANDES)
    state["profile"] = profile(state)["profile"]
    state["anomalies"] = detect(state)["anomalies"]
    diagnosis = diagnose(state)["diagnosis"]

    assert SCHEMA_COMMANDES[1]["name"] in diagnosis["root_cause"]


# --- Nœud 4/8 : propose ------------------------------------------------------


def etat_diagnostique(colonne="col_trouee", table="RAW.ORDERS"):
    """Un état prêt à être soumis — ce que `diagnose` aurait laissé."""
    state = etat_avec_ecart(colonne, table)
    state["diagnosis"] = diagnose(state)["diagnosis"]
    return state


def test_la_proposition_offre_les_trois_choix_dans_l_ordre():
    """Les deux « non » sont distincts : c'est ce qui empêche le contrat de vieillir."""
    proposal = build_proposal(etat_diagnostique())
    assert proposal["choix"] == [DECISION_APPROVED, DECISION_AMEND, DECISION_REJECTED]


def test_la_proposition_porte_de_quoi_decider():
    """Tout ce dont l'humain a besoin, en un seul objet — rien à aller chercher ailleurs."""
    proposal = build_proposal(etat_diagnostique())
    assert set(proposal) == {
        "dataset",
        "layer",
        "table",
        "batch_id",
        "anomalies",
        "root_cause",
        "proposed_fix",
        "explanation",
        "impact",
        "past_incidents",
        "choix",
    }


def test_la_proposition_affiche_toujours_un_impact():
    """Sans impact chiffré, « 1 ligne sur 351 » paraît négligeable — et ne l'est pas."""
    proposal = build_proposal(etat_diagnostique())
    assert proposal["impact"]  # non vide (réel en phase 5.1)


def test_propose_ne_decide_rien():
    """LA garantie du projet : la décision vient de l'extérieur, jamais de l'agent."""
    state = etat_diagnostique()
    result = propose(state)

    assert "human_decision" not in result
    assert state["human_decision"] is None


def test_propose_marche_sur_n_importe_quel_dataset():
    rh = build_proposal(etat_diagnostique("salaire_brut", "HR.EMPLOYES"))
    assert rh["table"] == "HR.EMPLOYES"
    assert "salaire_brut" in rh["root_cause"]


def test_propose_supporte_un_diagnostic_absent():
    """Si le parsing LLM a échoué (étape 7), la proposition reste construite."""
    state = etat_avec_ecart()  # diagnosis reste None
    proposal = build_proposal(state)
    assert proposal["root_cause"] is None
    assert proposal["anomalies"]  # les faits, eux, sont toujours là


def test_propose_ne_modifie_pas_l_etat_recu():
    state = etat_diagnostique()
    avant = copy.deepcopy(state)
    propose(state)
    assert state == avant


def test_propose_ecrit_une_ligne_de_journal_au_format_commun():
    entry = propose(etat_diagnostique())["logs"][0]
    assert entry["node"] == "propose"
    assert entry["anomalies"] == 1
    assert entry["antecedents"] == 0
    assert set(log_entry("x", "y")) <= set(entry)


# --- Nœud 5/8 : apply — le seul qui écrit dans les données -------------------


@pytest.mark.parametrize("decision", [None, DECISION_REJECTED, DECISION_AMEND])
def test_apply_refuse_toute_execution_sans_approbation(decision):
    """P3, première preuve — au niveau du nœud.

    Trois cas dangereux : personne n'a répondu, l'humain a refusé, l'humain a
    demandé un amendement du contrat. Dans aucun des trois `apply` ne doit
    s'exécuter. La preuve exhaustive sur les *chemins du graphe* arrive à
    l'étape 8 ; celle-ci couvre le nœud lui-même.
    """
    state = etat_diagnostique()
    state["human_decision"] = decision
    with pytest.raises(RuntimeError, match="P3"):
        apply(state)


def test_apply_s_execute_avec_approbation():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    state["decided_by"] = "hoda"

    entry = apply(state)["logs"][0]
    assert entry["node"] == "apply"
    assert entry["decideur"] == "hoda"
    assert entry["fix"]  # la correction appliquée est tracée


def test_apply_ne_retourne_aucune_donnee_metier():
    """Il agit sur la base, pas sur l'état : seuls la correction et le journal remontent."""
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    assert set(apply(state)) == {"applied_fix", "logs"}


def test_apply_execute_la_correction_de_l_agent_par_defaut():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    result = apply(state)

    assert result["applied_fix"] == state["diagnosis"]["proposed_fix"]
    assert result["logs"][0]["reecrite_par_humain"] is False


def test_apply_execute_la_correction_de_l_humain_si_elle_existe():
    """L'humain peut réécrire la correction — sinon il irait corriger hors de
    l'agent, et le journal deviendrait faux."""
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    state["fix_override"] = "UPDATE ... SET x = y / 100 WHERE ..."

    result = apply(state)
    assert result["applied_fix"] == state["fix_override"]
    assert result["logs"][0]["reecrite_par_humain"] is True


def test_on_sait_toujours_distinguer_proposee_de_reecrite():
    """Base de la métrique de qualité en phase 8 : proposée / réécrite / refusée."""
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    state["fix_override"] = "ma propre correction"

    # la proposition de l'agent reste intacte dans l'état, à côté de l'appliquée
    assert apply(state)["applied_fix"] != state["diagnosis"]["proposed_fix"]


def test_apply_ne_modifie_pas_l_etat_recu():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    avant = copy.deepcopy(state)
    apply(state)
    assert state == avant


# --- Nœud 6/8 : amend — le miroir d'apply ------------------------------------


@pytest.mark.parametrize("decision", [None, DECISION_APPROVED, DECISION_REJECTED])
def test_amend_refuse_toute_execution_sans_decision_d_amendement(decision):
    """Un contrat amendé par erreur rendrait l'agent aveugle — silencieusement."""
    state = etat_diagnostique()
    state["human_decision"] = decision
    with pytest.raises(RuntimeError):
        amend(state)


def test_amend_ne_touche_jamais_aux_donnees():
    """LA différence avec apply : il ne retourne aucune clé de données.

    Ni profile, ni anomalies, ni validation — seulement la version du contrat
    et le journal. En phase 5.3 un test comptera les lignes avant/après.
    """
    state = etat_diagnostique()
    state["human_decision"] = DECISION_AMEND
    assert set(amend(state)) == {"contract_version", "logs"}


def test_amend_incremente_la_version_du_contrat():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_AMEND
    state["contract_version"] = "v1"
    assert amend(state)["contract_version"] == "v2"


@pytest.mark.parametrize(
    ("actuelle", "attendue"),
    [(None, "v1"), ("v1", "v2"), ("v9", "v10"), ("brouillon", "v1")],
)
def test_la_numerotation_des_contrats_est_previsible(actuelle, attendue):
    """Une table sans contrat démarre en v1 ; une version illisible ne plante pas."""
    assert _version_suivante(actuelle) == attendue


def test_amend_trace_le_passage_d_une_version_a_l_autre():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_AMEND
    state["contract_version"] = "v1"
    state["decided_by"] = "hoda"

    entry = amend(state)["logs"][0]
    assert entry["node"] == "amend"
    assert (entry["depuis"], entry["vers"]) == ("v1", "v2")
    assert entry["decideur"] == "hoda"


def test_amend_ne_modifie_pas_l_etat_recu():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_AMEND
    avant = copy.deepcopy(state)
    amend(state)
    assert state == avant


# --- Nœud 7/8 : validate -----------------------------------------------------


def test_validate_remesure_la_metrique_fautive():
    """On ne croit jamais une correction sur parole : on la re-mesure."""
    state = etat_diagnostique()
    validation = validate(state)["validation"]

    assert set(validation) == {"status", "metric", "before", "after"}
    assert validation["metric"] == "nulls(col_trouee)"
    assert validation["before"] == 0.301  # la valeur qui avait déclenché l'alerte


def test_validate_marche_sur_n_importe_quel_dataset():
    rh = validate(etat_diagnostique("salaire_brut", "HR.EMPLOYES"))["validation"]
    assert rh["metric"] == "nulls(salaire_brut)"


def test_validate_sans_ecart_ne_pretend_rien_avoir_verifie():
    validation = validate(base_state())["validation"]
    assert validation["metric"] is None
    assert validation["status"] == VALIDATION_OK


def test_validate_ne_modifie_pas_l_etat_recu():
    state = etat_diagnostique()
    avant = copy.deepcopy(state)
    validate(state)
    assert state == avant


def test_validate_ecrit_une_ligne_de_journal_au_format_commun():
    entry = validate(etat_diagnostique())["logs"][0]
    assert entry["node"] == "validate"
    assert entry["status"] == VALIDATION_OK
    assert set(log_entry("x", "y")) <= set(entry)


# --- Nœud 8/8 : log — la sortie unique ---------------------------------------


def fusionner(state: dict, result: dict) -> dict:
    """Applique le résultat d'un nœud **comme le ferait LangGraph**.

    Piège : le réducteur `Annotated[list, add]` est une mécanique *LangGraph*,
    pas *Python*. Hors du graphe, `state.update(result)` écrase `logs` au lieu
    de le concaténer — d'où cet émulateur, qui rend la règle explicite :
    `logs` s'accumule, tout le reste s'écrase.
    """
    logs = state["logs"] + result.get("logs", [])
    state.update(result)
    state["logs"] = logs
    return state


def test_log_resume_le_chemin_rien_d_anormal():
    entry = log(base_state())["logs"][0]
    assert entry["anomalies"] == 0
    assert entry["decision"] is None
    assert entry["applied_fix"] is None
    assert entry["validation"] is None


def test_log_resume_le_chemin_refuse():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_REJECTED
    entry = log(state)["logs"][0]

    assert entry["anomalies"] == 1
    assert entry["decision"] == DECISION_REJECTED
    assert entry["applied_fix"] is None  # rien n'a été écrit
    assert entry["validation"] is None  # on n'est pas passé par validate


def test_log_resume_le_chemin_amende():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_AMEND
    state = fusionner(state, amend(state))
    entry = log(state)["logs"][-1]

    assert entry["contract_version"] == "v1"
    assert entry["applied_fix"] is None  # amend n'écrit jamais dans les données


def test_log_resume_le_chemin_approuve():
    state = etat_diagnostique()
    state["human_decision"] = DECISION_APPROVED
    state["decided_by"] = "hoda"
    state = fusionner(state, apply(state))
    state = fusionner(state, validate(state))
    entry = log(state)["logs"][-1]

    assert entry["decision"] == DECISION_APPROVED
    assert entry["decideur"] == "hoda"
    assert entry["applied_fix"]
    assert entry["validation"] == VALIDATION_OK


def test_log_compte_les_etapes_traversees():
    """Un journal disant « 0 écart » est ambigu : rien vu, ou rien regardé ?"""
    state = base_state(SCHEMA_COMMANDES)
    state = fusionner(state, profile(state))
    state = fusionner(state, detect(state))
    entry = log(state)["logs"][-1]

    assert entry["etapes"] == 3  # profile + detect + log


def test_log_ne_modifie_pas_l_etat_recu():
    state = etat_diagnostique()
    avant = copy.deepcopy(state)
    log(state)
    assert state == avant


def test_log_ne_retourne_que_du_journal():
    """Sortie unique : il conclut le run, il ne change plus rien."""
    assert set(log(etat_diagnostique())) == {"logs"}
