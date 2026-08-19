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

Les deux dernières familles sont arrivées avec l'étape 3.2 :

  4. **La pause** — le graphe s'arrête vraiment sur `propose` et n'écrit rien
     tant que personne n'a répondu.
  5. **La reprise après mort du process** — la preuve que la pause est réelle et
     non un `return` déguisé : le run est lancé dans un process séparé qu'on
     laisse mourir, puis repris depuis un autre, y compris par `scripts/decide.py`.
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from langgraph.types import Command

import agent.graph
from agent.graph import (
    BRANCHE_ANOMALIES,
    BRANCHE_RAS,
    BRANCHE_SANS_DECISION,
    agent_persistant,
    build_agent,
    build_graph,
    proposition_en_attente,
    route_after_detect,
    route_after_propose,
    thread,
)
from agent.nodes.propose import MAX_ECHANGES
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    DEMANDE_QUESTION,
    log_entry,
    new_state,
)

# Le double de `profile_table` (cf. conftest.py) : depuis 4.3 c'est lui, et non
# plus l'état, qui décide des colonnes que la mesure rendra. pytest place le
# dossier des tests sur `sys.path`, d'où l'import direct du conftest.
from conftest import PROFIL_FACTICE, REFERENCES

RACINE = Path(__file__).resolve().parent.parent

# Même piège que dans `test_agent_nodes.py` : `agent.nodes.diagnose` désigne la
# **fonction** réexportée, pas le module. On va chercher le module explicitement.
diagnose_mod = importlib.import_module("agent.nodes.diagnose")

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
    # Depuis 4.3, la forme du lot se pilote là où la mesure a lieu.
    PROFIL_FACTICE.colonnes = [c["name"] for c in schema]
    state.update(surcharges)

    # `profile` charge lui-même les références et **écrase** ce que l'appelant
    # aurait posé dans l'état : c'est le nœud qui fait autorité, pas le test.
    # Une surcharge de version se traduit donc en contrat signé côté double —
    # la version vient désormais d'où elle vient vraiment.
    if surcharges.get("contract_version"):
        REFERENCES.contrat = {
            "table": state["table"],
            "version": surcharges["contract_version"],
            "status": "approved",
            "columns": {},
        }
    return state


def parcours(resultat) -> list[str]:
    """La suite des nœuds traversés, lue dans le journal.

    C'est le journal qui sert de trace d'exécution, et non un mock : s'il est
    incomplet, les tests de chemin échouent. La complétude du journal (P5) est
    donc vérifiée indirectement par tous les tests de ce fichier.
    """
    return [entree["node"] for entree in resultat["logs"]]


# Une réponse vide : l'humain a répondu, mais rien d'exploitable n'en sort.
#
# On n'utilise pas `None` — `Command(resume=None)` lève un `UnboundLocalError`
# **dans LangGraph 1.2.9** (`_loop.py`, `resume_is_map` référencé avant
# affectation). Ce n'est donc pas un cas injectable ici ; il reste couvert au
# niveau unitaire par `lire_reponse(None)` et `route_after_propose`.
SANS_DECISION = {}


def lancer(schema, reponse=SANS_DECISION, **surcharges):
    """Un run complet, en répondant `reponse` si l'agent demande à l'humain.

    Depuis l'étape 3.2, le graphe **s'arrête vraiment** sur `propose`. Les tests
    ne peuvent donc plus pré-remplir `human_decision` dans l'état initial : ils
    doivent injecter la décision comme le fera `scripts/decide.py`, par
    `Command(resume=…)`. C'est plus proche du réel — et surtout, la décision
    passe désormais par le seul chemin qui existe en production.

    Par défaut, la réponse est vide : le run repart mais n'écrit rien.
    """
    with agent_persistant(":memory:") as app:
        config = thread("test")
        resultat = app.invoke(etat(schema, **surcharges), config)
        if proposition_en_attente(resultat) is None:
            return resultat
        return app.invoke(Command(resume=reponse), config)


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
    resultat = lancer(SCHEMA_AVEC_ECART, reponse=DECISION_REJECTED)
    assert parcours(resultat) == ["profile", "detect", "diagnose", "propose", "log"]
    # un refus n'écrit rien, nulle part
    assert resultat["applied_fix"] is None
    assert resultat["validation"] is None
    assert resultat["contract_version"] is None


def test_chemin_amende():
    resultat = lancer(SCHEMA_AVEC_ECART, reponse=DECISION_AMEND, contract_version="v1")
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
        SCHEMA_AVEC_ECART,
        reponse={"decision": DECISION_APPROVED, "decided_by": "hoda"},
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
    # qui a décidé, et quand — ce que `INCIDENTS` conservera en phase 4.4
    assert resultat["decided_by"] == "hoda"
    assert resultat["decided_at"]


def test_les_quatre_chemins_sont_distincts():
    """Quatre parcours réellement différents — sinon deux tests ci-dessus
    vérifieraient la même chose sans qu'on s'en aperçoive."""
    chemins = {
        tuple(parcours(lancer(schema, **surcharges)))
        for schema, surcharges in [
            (SCHEMA_SANS_ECART, {}),
            (SCHEMA_AVEC_ECART, {"reponse": DECISION_REJECTED}),
            (SCHEMA_AVEC_ECART, {"reponse": DECISION_AMEND}),
            (SCHEMA_AVEC_ECART, {"reponse": DECISION_APPROVED}),
        ]
    }
    assert len(chemins) == 4


# --- 2. Preuve P3 : aucun chemin vers `apply` sans approbation ---------------

# Un échantillon volontairement hostile : fautes de frappe, casse, espaces,
# traduction, valeurs d'un autre système, chaîne vide. Aucune ne doit ouvrir
# `apply` — seule la constante exacte le fait.
DECISIONS_INVALIDES = [
    # `None` est absent volontairement : il n'est pas injectable via
    # `Command(resume=…)` en LangGraph 1.2.9 (cf. `SANS_DECISION` plus haut).
    # Il est couvert au niveau unitaire, dans `test_agent_nodes.py`.
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
    resultat = lancer(schema, reponse=decision)

    assert atteintes == [], f"apply atteint avec une décision {decision!r}"
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
    lancer(SCHEMA_AVEC_ECART, reponse=DECISION_APPROVED)

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
    resultat = lancer(SCHEMA_AVEC_ECART, reponse=DECISION_AMEND, contract_version="v1")
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
        {"schema": SCHEMA_AVEC_ECART, "reponse": DECISION_REJECTED},
        {"schema": SCHEMA_AVEC_ECART, "reponse": DECISION_AMEND},
        {"schema": SCHEMA_AVEC_ECART, "reponse": DECISION_APPROVED},
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
    assert parcours(lancer(SCHEMA_AVEC_ECART, reponse=decision))[-1] == "log"


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
        lancer(SCHEMA_AVEC_ECART, reponse=DECISION_REJECTED)


def test_un_graphe_sans_checkpointer_reste_bloque_sur_propose():
    """Oublier le checkpointer ne **contourne pas** la pause : le run s'arrête
    quand même sur `propose`, mais sans nulle part où sauvegarder son état, il ne
    pourra jamais repartir.

    C'est le point important : le mode dégradé est « bloqué », pas « passe
    outre ». Une exécution sans persistance ne peut donc pas atteindre `apply`.
    """
    resultat = build_graph().compile().invoke(etat(SCHEMA_AVEC_ECART))

    assert parcours(resultat) == ["profile", "detect", "diagnose"]
    assert "apply" not in parcours(resultat)
    assert resultat["human_decision"] is None


# --- 4 bis. Le dialogue avant la décision ------------------------------------
#
# Un humain à qui on ne laisse que trois boutons approuve vite et mal. Pouvoir
# demander « pourquoi ? » avant de trancher est ce qui rend l'approbation
# informée — et c'est la meilleure réponse à la question de jury « et s'il
# approuve sans lire ? ».
#
# Ce que ces tests doivent garantir avant tout : **discuter ne rapproche pas de
# l'écriture**. On peut poser dix questions, `apply` reste inatteignable tant que
# le mot exact n'a pas été prononcé.


def dialoguer(app, config, *echanges):
    """Enchaîne des questions puis une décision, comme le ferait `decide.py`."""
    resultat = None
    for e in echanges:
        message = (
            {"decision": DEMANDE_QUESTION, "question": e} if isinstance(e, str) else e
        )
        resultat = app.invoke(Command(resume=message), config)
    return resultat


def test_une_question_ramene_le_graphe_a_diagnose():
    """La seule branche du graphe qui **remonte**."""
    with agent_persistant(":memory:") as app:
        config = thread("t")
        app.invoke(etat(SCHEMA_AVEC_ECART), config)
        resultat = dialoguer(app, config, "Pourquoi le job amont ?")

    assert proposition_en_attente(resultat) is not None, "le graphe devait re-demander"
    assert parcours(resultat) == [
        "profile",
        "detect",
        "diagnose",
        "propose",
        "diagnose",  # ← la question est repassée par le nœud du LLM
    ]


def test_le_dialogue_saccumule_et_survit_aux_tours():
    with agent_persistant(":memory:") as app:
        config = thread("t")
        app.invoke(etat(SCHEMA_AVEC_ECART), config)
        resultat = dialoguer(app, config, "Première ?", "Deuxième ?")

    conversation = proposition_en_attente(resultat)["conversation"]
    assert [e["role"] for e in conversation] == ["humain", "agent", "humain", "agent"]
    assert conversation[0]["message"] == "Première ?"
    assert conversation[2]["message"] == "Deuxième ?"


def test_la_proposition_reaffiche_le_dialogue_deja_tenu():
    """C'est ce qui permet de reprendre le fil le lendemain, depuis un autre poste."""
    with agent_persistant(":memory:") as app:
        config = thread("t")
        app.invoke(etat(SCHEMA_AVEC_ECART), config)
        resultat = dialoguer(app, config, "Pourquoi ?")

    proposal = proposition_en_attente(resultat)
    assert proposal["conversation"]
    assert proposal["questions_restantes"] == MAX_ECHANGES - 2
    # la proposition elle-même n'a pas changé : discuter n'altère pas ce qui est
    # proposé, sinon elle bougerait sous les yeux de l'humain pendant qu'il réfléchit
    assert proposal["proposed_fix"]


def test_discuter_nécrit_rien():
    """Dix questions ne modifient ni les données, ni le contrat, ni la validation."""
    with agent_persistant(":memory:") as app:
        config = thread("t")
        app.invoke(etat(SCHEMA_AVEC_ECART, contract_version="v1"), config)
        resultat = dialoguer(app, config, "Q1 ?", "Q2 ?", "Q3 ?")

    assert resultat["applied_fix"] is None
    assert resultat["validation"] is None
    assert resultat["contract_version"] == "v1"


def test_p3_tient_apres_une_longue_discussion(monkeypatch):
    """**Le test qui compte pour cette fonctionnalité.** Discuter n'est pas
    approuver : quel que soit le nombre d'échanges, `apply` reste inatteignable
    tant que le mot exact n'a pas été prononcé."""
    atteintes = []
    monkeypatch.setattr(
        agent.graph,
        "apply",
        lambda state: (
            atteintes.append(state) or {"logs": [log_entry("apply", "espion")]}
        ),
    )
    with agent_persistant(":memory:") as app:
        config = thread("t")
        app.invoke(etat(SCHEMA_AVEC_ECART), config)
        dialoguer(app, config, *[f"Question {i} ?" for i in range(5)])
        assert atteintes == [], "apply atteint pendant une simple discussion"

        # et il le devient dès que la décision tombe
        dialoguer(app, config, {"decision": DECISION_APPROVED})
    assert len(atteintes) == 1


def test_p3_topologie_inchangee_malgre_la_nouvelle_branche():
    """La 4ᵉ issue ne doit pas avoir ouvert de chemin vers `apply`."""
    entrees = aretes_entrantes(build_agent().get_graph(), "apply")
    assert entrees == [("propose", DECISION_APPROVED)]


def test_la_question_remonte_bien_vers_diagnose_et_nulle_part_ailleurs():
    graphe = build_agent().get_graph()
    depuis_propose = {a.data: a.target for a in graphe.edges if a.source == "propose"}
    assert depuis_propose[DEMANDE_QUESTION] == "diagnose"


@pytest.mark.parametrize("question_vide", ["", "   ", None])
def test_une_question_vide_nen_est_pas_une(question_vide):
    """Sans question exploitable, on ne relance pas le modèle pour rien : le run
    retombe sur « sans décision » et se termine sans rien écrire."""
    with agent_persistant(":memory:") as app:
        config = thread("t")
        app.invoke(etat(SCHEMA_AVEC_ECART), config)
        resultat = app.invoke(
            Command(resume={"decision": DEMANDE_QUESTION, "question": question_vide}),
            config,
        )

    assert proposition_en_attente(resultat) is None
    assert parcours(resultat)[-1] == "log"
    assert resultat["applied_fix"] is None


def test_le_plafond_dechanges_ferme_le_run_sans_decision():
    """Sans plafond, la boucle `propose → diagnose → propose` peut tourner sans
    fin — notamment si le modèle est en panne et répond « je ne peux pas » à
    chaque tour. Au-delà, le run se clôt **sans rien écrire** : direction sûre.
    """
    with agent_persistant(":memory:") as app:
        config = thread("t")
        app.invoke(etat(SCHEMA_AVEC_ECART), config)
        # MAX_ECHANGES/2 questions produisent MAX_ECHANGES entrées (question + réponse)
        resultat = dialoguer(
            app, config, *[f"Q{i} ?" for i in range(MAX_ECHANGES // 2)]
        )
        assert proposition_en_attente(resultat) is not None, (
            "on ne doit pas encore être coupé"
        )

        resultat = dialoguer(app, config, "La question de trop ?")

    assert proposition_en_attente(resultat) is None, "le run devait se clore"
    assert resultat["human_decision"] is None
    assert resultat["applied_fix"] is None
    assert parcours(resultat)[-1] == "log"
    # la question restée sans réponse est quand même conservée : le journal doit
    # montrer qu'on a coupé la parole à l'humain
    assert resultat["conversation"][-1]["message"] == "La question de trop ?"


def test_une_panne_du_modele_ne_casse_pas_le_dialogue(monkeypatch):
    """Même mode dégradé que pour le diagnostic : l'agent dit qu'il ne peut pas
    répondre, et les faits restent affichés."""

    def en_panne(contexte, conversation, question):
        raise ConnectionError("Groq injoignable")

    monkeypatch.setattr(diagnose_mod, "repondre", en_panne)

    with agent_persistant(":memory:") as app:
        config = thread("t")
        app.invoke(etat(SCHEMA_AVEC_ECART), config)
        resultat = dialoguer(app, config, "Pourquoi ?")

    proposal = proposition_en_attente(resultat)
    assert proposal is not None, "le run doit rester ouvert malgré la panne"
    assert "ne peux pas répondre" in proposal["conversation"][-1]["message"]
    assert proposal["anomalies"], "les faits ne dépendent pas du modèle"


# --- 5. La pause et la reprise (étape 3.2) -----------------------------------


def test_le_graphe_sarrete_sur_propose():
    """Sans réponse injectée, le run **ne va pas au bout** : il attend."""
    with agent_persistant(":memory:") as app:
        config = thread("t")
        resultat = app.invoke(etat(SCHEMA_AVEC_ECART), config)

        assert proposition_en_attente(resultat) is not None
        # arrêté *avant* d'avoir journalisé quoi que ce soit de `propose`
        assert parcours(resultat) == ["profile", "detect", "diagnose"]
        assert app.get_state(config).next == ("propose",)


def test_la_pause_porte_de_quoi_decider():
    """La charge utile de l'interruption est la proposition complète — c'est elle
    que `scripts/decide.py` affiche, et que Streamlit affichera en phase 6."""
    with agent_persistant(":memory:") as app:
        resultat = app.invoke(etat(SCHEMA_AVEC_ECART), thread("t"))
        proposal = proposition_en_attente(resultat)

    assert proposal["choix"] == [DECISION_APPROVED, DECISION_AMEND, DECISION_REJECTED]
    assert proposal["anomalies"]
    assert proposal["proposed_fix"]
    assert proposal["impact"]


def test_un_graphe_en_pause_nécrit_rien():
    """Tant que l'humain n'a pas répondu, aucune donnée n'a bougé — ni correction,
    ni contrat, ni validation."""
    with agent_persistant(":memory:") as app:
        resultat = app.invoke(
            etat(SCHEMA_AVEC_ECART, contract_version="v1"), thread("t")
        )

    assert resultat["human_decision"] is None
    assert resultat["applied_fix"] is None
    assert resultat["validation"] is None
    assert resultat["contract_version"] == "v1"


def test_deux_runs_simultanes_ne_se_melangent_pas():
    """Chaque run a son `thread_id`. Sans cette séparation, une décision prise sur
    une table s'appliquerait à une autre — Airflow lancera l'agent sur les trois
    couches à chaque batch."""
    with agent_persistant(":memory:") as app:
        a, b = thread("table-a"), thread("table-b")
        app.invoke(etat(SCHEMA_AVEC_ECART, table="A"), a)
        app.invoke(etat(SCHEMA_AVEC_ECART, table="B"), b)

        # on ne répond que sur A
        fin_a = app.invoke(Command(resume=DECISION_APPROVED), a)
        etat_b = app.get_state(b)

        assert fin_a["table"] == "A"
        assert fin_a["human_decision"] == DECISION_APPROVED
        assert etat_b.next == ("propose",), "B ne devait pas bouger"


# --- 6. LA preuve : la pause survit à la mort du process ---------------------


# ⚠️ Ce script tourne dans un **vrai** process : les fixtures `autouse` de
# conftest.py ne s'y appliquent pas. Depuis 4.3, `profile` lit et écrit
# `OPS._PROFILES` et profile la table — sans rebranchement, ce lanceur ouvrirait
# une connexion Snowflake, et ce test porte sur la survie de la pause, pas sur
# la mesure. On importe les **mêmes** doubles que le reste de la suite plutôt
# que d'en réécrire ici : deux définitions du même décor finiraient par diverger,
# et c'est le lanceur — celui qu'on relit le moins — qui mentirait.
LANCEUR = """
import sys
sys.path.insert(0, {tests!r})

import importlib

from conftest import MEMOIRE_FACTICE, PROFIL_FACTICE, REFERENCES

# `import agent.nodes.profile` rendrait la **fonction** réexportée, pas le
# module — le piège déjà documenté dans conftest.py et test_tools.py. Ici il se
# manifeste par un `AttributeError` franc ; ailleurs il a rendu des monkeypatch
# silencieusement sans effet. Troisième occurrence : la réexportation coûte.
profile_mod = importlib.import_module("agent.nodes.profile")

profile_mod.profile_table = PROFIL_FACTICE
profile_mod.ops.MemoireOps = lambda *a, **k: MEMOIRE_FACTICE
# Les fixtures `autouse` ne franchissent pas la frontière du process : les
# doubles des références (4.3) doivent être réinstallés ici, sinon le run
# ouvrirait une vraie connexion — et le test de survie à la mort du process
# mesurerait le réseau au lieu de la reprise.
profile_mod.charger_registre = lambda dataset: REFERENCES
profile_mod.ouvrir = lambda nom: REFERENCES
profile_mod.fermer = lambda connecteur: None
profile_mod.loader.charger = lambda ds, t: REFERENCES.contrat

from agent.graph import agent_persistant, thread, proposition_en_attente
from agent.state import new_state

s = new_state("jouet", "bronze", "UNE.TABLE", "2018-04-29")
with agent_persistant({db!r}) as app:
    r = app.invoke(s, thread("survivant"))
    sys.exit(0 if proposition_en_attente(r) is not None else 1)
"""

DOSSIER_TESTS = str(Path(__file__).resolve().parent)


def test_la_pause_survit_a_la_mort_du_process(tmp_path):
    """**Le test qui compte.** Un `interrupt()` qui ne survit pas au redémarrage
    ne serait qu'un `return` déguisé : la pause paraîtrait marcher en démo et
    perdrait tout en production, où Airflow lance le run et où l'humain répond
    des heures plus tard, depuis un autre poste.

    On lance donc le run dans un **process séparé**, on le laisse mourir, puis on
    reprend depuis celui-ci. Rien n'est partagé entre les deux sinon le fichier
    de checkpoints.
    """
    db = tmp_path / "checkpoints.sqlite"

    lancement = subprocess.run(
        [sys.executable, "-c", LANCEUR.format(db=str(db), tests=DOSSIER_TESTS)],
        cwd=RACINE,
        env={**os.environ, "PYTHONPATH": str(RACINE)},
        capture_output=True,
        text=True,
    )
    assert lancement.returncode == 0, f"le lanceur a échoué : {lancement.stderr[-800:]}"
    assert db.exists(), "aucun checkpoint écrit sur disque"

    # Le process qui a lancé le run est mort. On reprend depuis un autre.
    with agent_persistant(db) as app:
        config = thread("survivant")
        assert app.get_state(config).next == ("propose",), (
            "la proposition n'a pas survécu"
        )

        resultat = app.invoke(
            Command(resume={"decision": DECISION_APPROVED, "decided_by": "hoda"}),
            config,
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
    assert resultat["decided_by"] == "hoda"


def test_le_script_decide_reprend_un_run_lance_ailleurs(tmp_path):
    """La même preuve, mais par le chemin réel : `scripts/decide.py`. C'est la
    seule voie de reprise du projet, et celle que rejoueront les boutons
    Streamlit en phase 6 — donc celle qui doit être testée, pas une variante."""
    db = tmp_path / "checkpoints.sqlite"

    subprocess.run(
        [sys.executable, "-c", LANCEUR.format(db=str(db), tests=DOSSIER_TESTS)],
        cwd=RACINE,
        env={**os.environ, "PYTHONPATH": str(RACINE)},
        check=True,
        capture_output=True,
    )

    decision = subprocess.run(
        [sys.executable, "-m", "scripts.decide", "survivant", "approve", "--by", "hoda"]
        + ["--db", str(db)],
        cwd=RACINE,
        env={**os.environ, "PYTHONPATH": str(RACINE)},
        capture_output=True,
        text=True,
    )

    assert decision.returncode == 0, decision.stderr[-800:]
    assert "approved" in decision.stdout
    assert "apply" in decision.stdout

    # et le run est bien terminé : plus rien en attente
    with agent_persistant(db) as app:
        assert app.get_state(thread("survivant")).next == ()


def test_decide_refuse_un_thread_inconnu(tmp_path):
    resultat = subprocess.run(
        [sys.executable, "-m", "scripts.decide", "inexistant", "approve"]
        + ["--db", str(tmp_path / "vide.sqlite")],
        cwd=RACINE,
        env={**os.environ, "PYTHONPATH": str(RACINE)},
        capture_output=True,
        text=True,
    )
    assert resultat.returncode == 1
    assert "Aucun run en attente" in resultat.stdout


def test_decide_refuse_une_correction_reecrite_sans_approbation(tmp_path):
    """`--fix` sur un refus ou un amendement laisserait croire qu'une correction
    va tourner, alors que ces deux chemins n'écrivent rien dans les données."""
    db = tmp_path / "checkpoints.sqlite"
    subprocess.run(
        [sys.executable, "-c", LANCEUR.format(db=str(db), tests=DOSSIER_TESTS)],
        cwd=RACINE,
        env={**os.environ, "PYTHONPATH": str(RACINE)},
        check=True,
        capture_output=True,
    )

    resultat = subprocess.run(
        [sys.executable, "-m", "scripts.decide", "survivant", "reject"]
        + ["--fix", "UPDATE …", "--db", str(db)],
        cwd=RACINE,
        env={**os.environ, "PYTHONPATH": str(RACINE)},
        capture_output=True,
        text=True,
    )
    assert resultat.returncode == 1
    assert "--fix" in resultat.stdout
