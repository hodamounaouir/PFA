"""Contrôle du graphe assemblé (phase 3.4) — les chemins et les preuves.

`test_agent_nodes.py` vérifie chaque nœud **isolément**. Ici on vérifie ce que
les nœuds ne peuvent pas garantir seuls : le **câblage**. Un nœud parfait relié
au mauvais endroit ne protège de rien.

Trois familles de tests, dans un ordre voulu :

  1. **Les 4 chemins** — le graphe traverse bien ses quatre parcours possibles.
  2. **Preuve P3** — aucun chemin n'atteint `apply` sans approbation humaine.
  3. **Preuve « sortie unique »** — aucun run ne se termine sans passer par `log`.

Les deux preuves sont vérifiées **deux fois, de deux façons différentes** :

  - *topologiquement*, en inspectant le graphe compilé : c'est la garantie forte,
    valable pour toute exécution, y compris celles auxquelles on n'a pas pensé ;
  - *dynamiquement*, en exécutant le graphe sur un large jeu de décisions
    (dont des valeurs absurdes) : c'est la garantie que le code se comporte comme
    la topologie le promet.

Une preuve statique seule laisserait passer un aiguillage qui ment ; une preuve
dynamique seule ne couvrirait que les cas testés. Les deux ensemble tiennent.

Aucun LLM n'est appelé : `diagnose` est encore un stub en phase 3.1. Quand il
appellera Groq (étape 3.3), c'est ici qu'il faudra le mocker.

⚠️ Le 4ᵉ test prévu par le PROGRESS pour cette étape — pause sur `interrupt()`
puis reprise après redémarrage du process — n'est pas dans ce fichier : il exige
le checkpointer, qui arrive à l'étape 3.2. Il viendra avec lui.
"""

import pytest

import agent.graph
from agent.graph import (
    BRANCHE_ANOMALIES,
    BRANCHE_RAS,
    BRANCHE_SANS_DECISION,
    build_agent,
    build_graph,
    route_after_detect,
    route_after_propose,
)
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    log_entry,
    new_state,
)

# --- Deux profils de batch, construits sur le comportement du stub -----------
# `profile` pose des nulls sur les colonnes de position 1, 5, 9… (position % 4 == 1).
# Une seule colonne → aucun écart ; quatre colonnes → un écart. Les tests
# vérifient cette hypothèse au lieu de la supposer (cf. test_preconditions).
SCHEMA_SANS_ECART = [{"name": "c0"}]
SCHEMA_AVEC_ECART = [{"name": f"c{i}"} for i in range(4)]


def etat(schema, **surcharges):
    state = new_state(
        dataset="jouet", layer="bronze", table="UNE.TABLE", batch_id="2018-04-29"
    )
    state["schema_history"] = schema
    state.update(surcharges)
    return state


def parcours(resultat) -> list[str]:
    """La suite des nœuds traversés, lue dans le journal.

    C'est le journal qui sert de trace d'exécution, et non un mock : s'il est
    incomplet, les tests de chemin échouent. La complétude du journal (P5) est
    donc vérifiée indirectement par tous les tests de ce fichier.
    """
    return [entree["node"] for entree in resultat["logs"]]


def lancer(schema, **surcharges):
    return build_agent().invoke(etat(schema, **surcharges))


# --- 0. Les hypothèses sur lesquelles reposent les autres tests ---------------


def test_preconditions_des_deux_profils():
    """Sans cette vérification, un changement du stub `profile` rendrait tous les
    tests de chemin faussement verts : ils passeraient par la branche « rien
    d'anormal » en croyant tester autre chose."""
    assert lancer(SCHEMA_SANS_ECART)["anomalies"] == []
    assert len(lancer(SCHEMA_AVEC_ECART)["anomalies"]) == 1


# --- 1. Les quatre chemins ----------------------------------------------------


def test_chemin_rien_danormal():
    resultat = lancer(SCHEMA_SANS_ECART)
    assert parcours(resultat) == ["profile", "detect", "log"]
    # ni LLM ni humain dérangés
    assert resultat["diagnosis"] is None
    assert resultat["human_decision"] is None


def test_chemin_refuse():
    resultat = lancer(SCHEMA_AVEC_ECART, human_decision=DECISION_REJECTED)
    assert parcours(resultat) == ["profile", "detect", "diagnose", "propose", "log"]
    # un refus n'écrit rien, nulle part
    assert resultat["applied_fix"] is None
    assert resultat["validation"] is None
    assert resultat["contract_version"] is None


def test_chemin_amende():
    resultat = lancer(
        SCHEMA_AVEC_ECART, human_decision=DECISION_AMEND, contract_version="v1"
    )
    assert parcours(resultat) == [
        "profile",
        "detect",
        "diagnose",
        "propose",
        "amend",
        "log",
    ]
    # le contrat bouge, les données non — c'est toute la différence avec `apply`
    assert resultat["contract_version"] == "v2"
    assert resultat["applied_fix"] is None
    assert resultat["validation"] is None


def test_chemin_approuve():
    resultat = lancer(
        SCHEMA_AVEC_ECART, human_decision=DECISION_APPROVED, decided_by="hoda"
    )
    assert parcours(resultat) == [
        "profile",
        "detect",
        "diagnose",
        "propose",
        "apply",
        "validate",
        "log",
    ]
    # seul chemin qui écrit, et seul chemin qui re-mesure derrière
    assert resultat["applied_fix"] is not None
    assert resultat["validation"]["status"] == "success"
    # le contrat, lui, n'a pas bougé
    assert resultat["contract_version"] is None


def test_les_quatre_chemins_sont_distincts():
    """Quatre parcours réellement différents — sinon deux tests ci-dessus
    vérifieraient la même chose sans qu'on s'en aperçoive."""
    chemins = {
        tuple(parcours(lancer(schema, **surcharges)))
        for schema, surcharges in [
            (SCHEMA_SANS_ECART, {}),
            (SCHEMA_AVEC_ECART, {"human_decision": DECISION_REJECTED}),
            (SCHEMA_AVEC_ECART, {"human_decision": DECISION_AMEND}),
            (SCHEMA_AVEC_ECART, {"human_decision": DECISION_APPROVED}),
        ]
    }
    assert len(chemins) == 4


# --- 2. Preuve P3 : aucun chemin vers `apply` sans approbation ---------------

# Un échantillon volontairement hostile : fautes de frappe, casse, espaces,
# traduction, valeurs d'un autre système, chaîne vide. Aucune ne doit ouvrir
# `apply` — seule la constante exacte le fait.
DECISIONS_INVALIDES = [
    None,
    "",
    "approve",
    "Approved",
    "APPROVED",
    " approved",
    "approved ",
    "approuvé",
    "oui",
    "yes",
    "true",
    "1",
    "amend",
    "reject",
    "validated",
    "approved; DROP TABLE",
]


def aretes_entrantes(graphe, cible):
    return [(a.source, a.data) for a in graphe.edges if a.target == cible]


def test_p3_topologie_apply_na_quune_entree():
    """La garantie forte : elle vaut pour **toute** exécution, y compris celles
    auxquelles personne n'a pensé. C'est ce qui distingue un garde-fou
    structurel d'un garde-fou testé par échantillonnage."""
    entrees = aretes_entrantes(build_agent().get_graph(), "apply")
    assert entrees == [("propose", DECISION_APPROVED)]


def test_p3_topologie_amend_ne_mene_pas_a_apply():
    """Amender une règle ne donne aucun droit d'écriture sur les données."""
    graphe = build_agent().get_graph()
    depuis_amend = {a.target for a in graphe.edges if a.source == "amend"}
    assert depuis_amend == {"log"}
    assert "apply" not in depuis_amend


def test_p3_topologie_diagnose_ne_mene_pas_a_apply():
    """Le LLM ne peut rien déclencher : sa seule sortie est la soumission."""
    graphe = build_agent().get_graph()
    assert {a.target for a in graphe.edges if a.source == "diagnose"} == {"propose"}


@pytest.mark.parametrize("decision", DECISIONS_INVALIDES)
@pytest.mark.parametrize("schema", [SCHEMA_SANS_ECART, SCHEMA_AVEC_ECART])
def test_p3_execution_apply_jamais_atteint_sans_approbation(
    monkeypatch, decision, schema
):
    """La garantie dynamique : le code se comporte-t-il comme la topologie le
    promet ? On espionne `apply` plutôt que d'utiliser le vrai, pour prouver
    l'**inatteignabilité** et non le fait qu'il se défende une fois atteint —
    ce sont deux propriétés différentes, et c'est la première qu'énonce P3."""
    atteintes = []

    def apply_espion(state):
        atteintes.append(state["human_decision"])
        return {"applied_fix": "(espion)", "logs": [log_entry("apply", "espion")]}

    monkeypatch.setattr(agent.graph, "apply", apply_espion)
    resultat = build_agent().invoke(etat(schema, human_decision=decision))

    assert atteintes == [], f"apply atteint avec human_decision={decision!r}"
    assert "apply" not in parcours(resultat)


def test_p3_execution_apply_atteint_avec_approbation(monkeypatch):
    """Le pendant du test précédent. Sans lui, une erreur de câblage qui rendrait
    `apply` inatteignable **en toutes circonstances** passerait pour un succès :
    tous les tests P3 seraient verts et l'agent ne corrigerait plus jamais rien."""
    atteintes = []

    def apply_espion(state):
        atteintes.append(state["human_decision"])
        return {"applied_fix": "(espion)", "logs": [log_entry("apply", "espion")]}

    monkeypatch.setattr(agent.graph, "apply", apply_espion)
    build_agent().invoke(etat(SCHEMA_AVEC_ECART, human_decision=DECISION_APPROVED))

    assert atteintes == [DECISION_APPROVED]


def test_p3_amend_natteint_jamais_apply_a_lexecution(monkeypatch):
    atteintes = []
    monkeypatch.setattr(
        agent.graph,
        "apply",
        lambda state: (
            atteintes.append(state) or {"logs": [log_entry("apply", "espion")]}
        ),
    )
    resultat = build_agent().invoke(
        etat(SCHEMA_AVEC_ECART, human_decision=DECISION_AMEND, contract_version="v1")
    )
    assert atteintes == []
    assert "amend" in parcours(resultat)


# --- 3. Preuve « sortie unique » : tout run passe par `log` -------------------


def test_sortie_unique_topologie():
    """`log` est le seul nœud relié à END. La complétude du journal n'est donc
    pas une discipline d'écriture : elle est structurelle."""
    graphe = build_agent().get_graph()
    assert {a.source for a in graphe.edges if a.target == "__end__"} == {"log"}


@pytest.mark.parametrize(
    "surcharges",
    [
        {"schema": SCHEMA_SANS_ECART},
        {"schema": SCHEMA_AVEC_ECART, "human_decision": DECISION_REJECTED},
        {"schema": SCHEMA_AVEC_ECART, "human_decision": DECISION_AMEND},
        {"schema": SCHEMA_AVEC_ECART, "human_decision": DECISION_APPROVED},
    ],
)
def test_sortie_unique_execution(surcharges):
    schema = surcharges.pop("schema")
    trace = parcours(lancer(schema, **surcharges))
    assert trace[-1] == "log", "un run s'est terminé sans journaliser"
    assert trace.count("log") == 1, "le journal de fin a été écrit plusieurs fois"


@pytest.mark.parametrize("decision", DECISIONS_INVALIDES)
def test_sortie_unique_meme_avec_une_decision_absurde(decision):
    """Une décision incompréhensible ne doit pas faire disparaître la trace :
    c'est justement le run qu'on voudra pouvoir relire."""
    assert parcours(lancer(SCHEMA_AVEC_ECART, human_decision=decision))[-1] == "log"


# --- 4. Les aiguillages, testés directement ----------------------------------


def test_route_after_detect():
    assert route_after_detect({"anomalies": [{"x": 1}]}) == BRANCHE_ANOMALIES
    assert route_after_detect({"anomalies": []}) == BRANCHE_RAS


@pytest.mark.parametrize(
    "decision,attendu",
    [
        (DECISION_APPROVED, DECISION_APPROVED),
        (DECISION_AMEND, DECISION_AMEND),
        (DECISION_REJECTED, DECISION_REJECTED),
    ],
)
def test_route_after_propose_decisions_valides(decision, attendu):
    assert route_after_propose({"human_decision": decision}) == attendu


@pytest.mark.parametrize("decision", DECISIONS_INVALIDES)
def test_route_after_propose_defaut_sans_decision(decision):
    """Le défaut n'est pas `rejected` mais `sans décision` : « l'humain a dit
    non » et « personne n'a répondu » sont deux situations différentes, et les
    confondre fausserait le journal."""
    assert route_after_propose({"human_decision": decision}) == BRANCHE_SANS_DECISION


def test_un_aiguillage_qui_deraille_fait_echouer_le_run(monkeypatch):
    """Le `path_map` n'est pas décoratif : une branche inconnue arrête le run au
    lieu de router au hasard. Sans cette propriété, une refonte des aiguillages
    pourrait ouvrir un chemin vers `apply` sans qu'aucun test ne le voie."""
    monkeypatch.setattr(agent.graph, "route_after_propose", lambda state: "apply")
    with pytest.raises(Exception):
        build_graph().compile().invoke(etat(SCHEMA_AVEC_ECART))
