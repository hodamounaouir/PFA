"""Contrôle de l'étape 3.1 : l'état partagé de l'agent."""

from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    DECISIONS,
    AgentState,
    log_entry,
    new_state,
)


def test_new_state_remplit_toutes_les_cles():
    """La fabrique doit couvrir *toutes* les clés déclarées dans AgentState.

    Sans ce test, ajouter un champ à AgentState sans l'ajouter à new_state()
    passerait inaperçu jusqu'au premier KeyError en plein run.
    """
    state = new_state(
        dataset="olist", layer="bronze", table="RAW.ORDERS", batch_id="2018-04-29"
    )
    assert set(state) == set(AgentState.__annotations__)


def test_etat_initial_neutre():
    """Un état neuf ne présume rien : aucune anomalie, aucune décision."""
    state = new_state("olist", "bronze", "RAW.ORDERS", "2018-04-29")
    assert state["anomalies"] == []
    assert state["diagnosis"] is None
    assert state["human_decision"] is None
    assert state["logs"] == []


def test_les_trois_decisions_sont_distinctes():
    """P3 s'appuie sur ces constantes : elles doivent rester distinctes."""
    assert DECISIONS == {DECISION_APPROVED, DECISION_AMEND, DECISION_REJECTED}
    assert len(DECISIONS) == 3


def test_log_entry_horodate_et_accepte_des_extras():
    entry = log_entry("detect", "2 écarts constatés", anomalies=2)
    assert entry["node"] == "detect"
    assert entry["message"] == "2 écarts constatés"
    assert entry["anomalies"] == 2
    assert entry["ts"].startswith("20")  # ISO 8601
