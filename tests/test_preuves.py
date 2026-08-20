"""Les cinq preuves du projet (phase 5.4) — **des livrables, pas de l'hygiène**.

Ce fichier existe pour être **lu**, pas seulement exécuté. Chaque test y énonce
une garantie du système en une phrase, et la démontre sur le graphe **assemblé**
— pas sur une fonction isolée.

    P3   aucun chemin n'atteint `apply` sans approbation humaine
    P4   une valeur inventée est refusée MÊME approuvée
    P5   la pause survit à la mort du process
    P6   `apply` reste dans ses bornes, agent comme humain
    P7   `amend` ne touche jamais aux données

## Pourquoi un troisième angle, alors que ces preuves existent ailleurs

C'est la méthode du projet, adoptée en 3.4 : *chaque preuve est établie deux
fois, une fois **topologiquement** (l'inspection du graphe compilé, qui vaut
pour toute exécution y compris celles auxquelles on n'a pas pensé) et une fois
**dynamiquement** (une exécution réelle sur des décisions hostiles)*. Une preuve
statique seule laisserait passer un aiguillage qui ment ; une preuve dynamique
seule ne couvrirait que les cas testés.

Ce fichier ajoute le troisième : **le système assemblé, de bout en bout**. Les
deux autres angles vivent dans `test_agent_graph.py` (topologie et exécution)
et dans les fichiers de chaque mécanisme. Ici, on vérifie que les garanties
tiennent quand tout est branché ensemble — c'est ce qu'on montre à un jury, et
c'est ce qui casserait en premier si une phase ultérieure défaisait l'une
d'elles sans s'en apercevoir.

    uv run pytest -k preuve      # les cinq, et rien d'autre
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from langgraph.types import Command

from agent.graph import agent_persistant, proposition_en_attente, thread
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    new_state,
)
from conftest import PROFIL_FACTICE, REFERENCES

# ⚠️ `agent.nodes.diagnose` désigne la **fonction** réexportée, pas le module :
# `import agent.nodes.diagnose as m` rend silencieusement le mauvais objet, et
# le `monkeypatch` qui suit lève un `AttributeError` qui ne ressemble pas à sa
# cause. Cinquième occurrence du piège dans le projet.
diagnose_mod = importlib.import_module("agent.nodes.diagnose")

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_TESTS = str(Path(__file__).resolve().parent)
ENV_PYTHONPATH = os.pathsep.join([str(RACINE), DOSSIER_TESTS])

# Quatre colonnes : la 2ᵉ porte une collision sémantique, donc l'agent trouve
# quelque chose et s'arrête sur `propose`. Une seule colonne : il ne trouve rien.
AVEC_ECART = ["c0", "c1", "c2", "c3"]


def run(reponse, colonnes=AVEC_ECART, contrat=None, db=":memory:"):
    """Un run complet du graphe assemblé, avec la décision `reponse`."""
    PROFIL_FACTICE.deja_profiles.clear()
    PROFIL_FACTICE.colonnes = list(colonnes)
    REFERENCES.contrat = contrat

    etat = new_state("olist", "bronze", "RAW.ORDERS", "2018-04-29")
    with agent_persistant(db) as app:
        config = thread("preuve")
        resultat = app.invoke(etat, config)
        if proposition_en_attente(resultat) is None:
            return resultat
        return app.invoke(Command(resume=reponse), config)


def noeuds(resultat) -> list[str]:
    return [entree["node"] for entree in resultat["logs"]]


CONTRAT_AMENDABLE = {
    "table": "RAW.ORDERS",
    "version": 1,
    "status": "approved",
    "columns": {"c1": {"no_semantic_collisions": True}},
    "warnings": [],
}


# ===========================================================================
# P3 — aucun chemin n'atteint `apply` sans approbation humaine
# ===========================================================================


@pytest.mark.parametrize(
    "decision",
    [
        DECISION_REJECTED,
        DECISION_AMEND,
        {},  # l'humain a répondu, mais rien d'exploitable
        "APPROVED",  # la casse compte : on ne devine pas
        "oui",  # une valeur inventée par un client mal écrit
        {"decision": "approuvé"},
    ],
)
def test_preuve_P3_apply_est_inatteignable_sans_approbation(decision):
    """**Garantie : l'agent n'écrit dans vos données que si vous avez dit oui.**

    C'est la garantie centrale du projet — celle qui distingue un agent d'un
    script automatique. Elle est éprouvée ici sur le système entier, avec des
    décisions hostiles : une casse différente, un synonyme, une réponse vide.
    Aucune ne doit être interprétée comme une approbation.

    En cas de doute sur la décision, le défaut est `log`, jamais `apply` : *un
    run qui finit à tort en « rien fait » se rattrape ; une écriture faite à
    tort, non.*
    """
    resultat = run(decision, contrat=CONTRAT_AMENDABLE)
    assert "apply" not in noeuds(resultat)
    assert resultat["applied_fix"] is None
    assert REFERENCES.corrections == [], "une écriture est partie sans approbation"


def test_preuve_P3_la_reciproque_tient():
    """Sans elle, un `apply` devenu **inatteignable en toutes circonstances**
    passerait pour un succès — et la preuve ci-dessus ne prouverait rien."""
    resultat = run(DECISION_APPROVED)
    assert "apply" in noeuds(resultat)


# ===========================================================================
# P4 — une valeur inventée est refusée MÊME approuvée
# ===========================================================================


def test_preuve_P4_une_valeur_inventee_est_refusee_malgre_l_approbation(monkeypatch):
    """**Garantie : l'agent ne fabrique jamais une donnée, même autorisé à le faire.**

    Face à `8000` dans une colonne à [1–100], il ne peut pas savoir s'il s'agit
    de 80,00 € en centimes, d'une faute de frappe ou d'une vraie grosse
    commande. Le garde-fou s'exécute **après** le « oui » humain : un humain
    peut approuver sans lire, et *une règle qui cède devant une approbation ne
    protège de rien*.

    Le recours existe et il est dit : réécrire la correction avec `--fix`.
    L'humain, lui, a l'autorité d'affirmer une valeur.
    """
    from agent.llm import Diagnostic

    monkeypatch.setattr(
        diagnose_mod,
        "diagnostiquer",
        lambda contexte: Diagnostic(
            root_cause="valeur aberrante",
            proposed_fix="UPDATE RAW.ORDERS SET c1 = 'brasilia' WHERE c1 = 'são paulo'",
            explanation="?",
        ),
    )

    resultat = run(DECISION_APPROVED)

    assert "apply" in noeuds(resultat), "le test doit passer PAR apply pour prouver"
    assert resultat["applied_fix"] is None
    assert REFERENCES.corrections == []


# ===========================================================================
# P5 — la pause survit à la mort du process
# ===========================================================================


LANCEUR_PREUVE = """
import sys
sys.path.insert(0, {tests!r})
from agent.graph import agent_persistant, thread, proposition_en_attente
from agent.state import new_state
from conftest import PROFIL_FACTICE

PROFIL_FACTICE.colonnes = ["c0", "c1", "c2", "c3"]
s = new_state("olist", "bronze", "RAW.ORDERS", "2018-04-29")
with agent_persistant({db!r}) as app:
    r = app.invoke(s, thread("preuve-p5"))
    sys.exit(0 if proposition_en_attente(r) is not None else 1)
"""


def test_preuve_P5_la_pause_survit_a_la_mort_du_process(tmp_path):
    """**Garantie : une proposition attend indéfiniment, sans process vivant.**

    Un `interrupt()` qui ne survivrait pas au redémarrage ne serait qu'un
    `return` déguisé : la pause paraîtrait marcher en démo et perdrait tout en
    production, où Airflow lance le run la nuit et où l'humain répond le
    lendemain, depuis un autre poste.

    On lance donc le run dans un **process séparé**, on le laisse mourir, et on
    reprend depuis celui-ci — seul le fichier de checkpoints est partagé.
    """
    db = tmp_path / "checkpoints.sqlite"

    lancement = subprocess.run(
        [sys.executable, "-c", LANCEUR_PREUVE.format(db=str(db), tests=DOSSIER_TESTS)],
        cwd=RACINE,
        env={**os.environ, "PYTHONPATH": ENV_PYTHONPATH},
        capture_output=True,
        text=True,
    )
    assert lancement.returncode == 0, lancement.stderr[-800:]

    # Le process qui a créé la pause est mort. On reprend depuis un autre.
    with agent_persistant(db) as app:
        etat = app.get_state(thread("preuve-p5"))
        assert etat.next == ("propose",), "la pause n'a pas survécu"

        resultat = app.invoke(
            Command(resume={"decision": DECISION_REJECTED, "decided_by": "hoda"}),
            thread("preuve-p5"),
        )

    assert resultat["human_decision"] == DECISION_REJECTED
    assert resultat["decided_by"] == "hoda"


# ===========================================================================
# P6 — `apply` reste dans ses bornes, agent comme humain
# ===========================================================================


@pytest.mark.parametrize(
    "fix",
    [
        "DROP TABLE RAW.ORDERS",
        "TRUNCATE TABLE RAW.ORDERS",
        "DELETE FROM RAW.ORDERS",
        "UPDATE MARTS.FCT_DAILY_SALES SET x = NULL WHERE y",
    ],
)
def test_preuve_P6_apply_refuse_de_sortir_de_ses_bornes(monkeypatch, fix):
    """**Garantie : l'agent ne détruit rien et ne sort pas de sa table.**

    Ces deux règles protègent de l'**accident**, pas du jugement : elles
    s'appliquent donc au SQL de l'agent **comme** à celui que l'humain
    réécrirait. C'est ce qui les distingue de P4, qui ne contraint que l'agent.
    """
    from agent.llm import Diagnostic

    monkeypatch.setattr(
        diagnose_mod,
        "diagnostiquer",
        lambda contexte: Diagnostic(root_cause="?", proposed_fix=fix, explanation="?"),
    )

    resultat = run({"decision": DECISION_APPROVED, "fix_override": fix})

    assert resultat["applied_fix"] is None
    assert REFERENCES.corrections == []


# ===========================================================================
# P7 — `amend` ne touche jamais aux données
# ===========================================================================


def test_preuve_P7_amender_ne_modifie_aucune_ligne():
    """**Garantie : corriger la règle ne corrige pas la donnée.**

    C'est toute la différence entre les deux « oui » du projet :

        approved        la donnée est fausse   → écrit dans les DONNÉES
        amend_contract  la règle est fausse    → écrit dans le CONTRAT

    Vérifié **par comptage**, et non par inspection de l'état : ce qui compte
    n'est pas qu'`amend` déclare ne rien écrire, mais qu'aucune ligne n'ait
    bougé. Sans cette branche, un contrat figé finirait par crier à chaque
    évolution normale du métier, l'équipe s'habituerait à ignorer les alertes,
    et l'agent mourrait en silence.
    """
    avant = REFERENCES.compter()

    resultat = run(DECISION_AMEND, contrat=CONTRAT_AMENDABLE)

    assert "amend" in noeuds(resultat) and "apply" not in noeuds(resultat)
    assert REFERENCES.compter() == avant, "des lignes ont bougé"
    assert REFERENCES.corrections == [], "une écriture est partie"
    assert resultat["applied_fix"] is None
    # Seul le contrat change — et il change vraiment, sinon la preuve serait
    # celle d'un nœud qui ne fait rien du tout.
    assert resultat["contract_version"] == 2
    assert [c["version"] for c in REFERENCES.contrats_ecrits] == [2]
