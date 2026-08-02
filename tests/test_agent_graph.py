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
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    log_entry,
    new_state,
)

RACINE = Path(__file__).resolve().parent.parent

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


LANCEUR = """
import sys
from agent.graph import agent_persistant, thread, proposition_en_attente
from agent.state import new_state

s = new_state("jouet", "bronze", "UNE.TABLE", "2018-04-29")
s["schema_history"] = [{{"name": f"c{{i}}"}} for i in range(4)]
with agent_persistant({db!r}) as app:
    r = app.invoke(s, thread("survivant"))
    sys.exit(0 if proposition_en_attente(r) is not None else 1)
"""


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
        [sys.executable, "-c", LANCEUR.format(db=str(db))],
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
        [sys.executable, "-c", LANCEUR.format(db=str(db))],
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
        [sys.executable, "-c", LANCEUR.format(db=str(db))],
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
