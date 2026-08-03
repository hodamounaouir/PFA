"""Garde-fou de la suite de tests : **aucun test n'appelle un vrai LLM**.

La règle vient du `CONTRIBUTING` — la CI doit être déterministe, gratuite, et
tourner sans clé API. Jusqu'ici elle reposait sur la discipline : chaque test
appelant `diagnose` devait penser à simuler le modèle. On l'a vérifié à nos
dépens en écrivant l'étape 3.3 : trois helpers l'avaient oublié, la suite est
passée de 6 à 172 secondes, et les tests dépendaient soudain du réseau, d'un
quota et du bon vouloir d'un modèle.

Une règle qu'on peut oublier n'est pas une règle. Cette fixture `autouse`
remplace donc la couture LLM pour **toute** la suite : un test qui oublierait de
simuler le modèle obtient une réponse factice au lieu d'un appel réseau.

Les tests qui veulent un autre comportement (un modèle en panne, un modèle qui
enregistre ce qu'il reçoit) redéfinissent simplement la même couture ; leur
`monkeypatch` s'applique après celui-ci et l'emporte.
"""

import importlib

import pytest

from agent.llm import Diagnostic

# `agent.nodes.__init__` réexporte les fonctions sous le nom de leur module :
# `agent.nodes.diagnose` désigne la **fonction**, pas le module. On va donc
# chercher le module explicitement, sans quoi le `monkeypatch` ne remplacerait
# rien — silencieusement, en laissant partir de vrais appels réseau.
diagnose_mod = importlib.import_module("agent.nodes.diagnose")

DIAGNOSTIC_FACTICE = Diagnostic(
    root_cause="(diagnostic factice — aucun LLM appelé en test)",
    proposed_fix="Isoler en quarantaine les lignes concernées.",
    explanation="(explication factice)",
)


@pytest.fixture(autouse=True)
def pas_de_vrai_llm(monkeypatch):
    monkeypatch.setattr(
        diagnose_mod, "diagnostiquer", lambda contexte: DIAGNOSTIC_FACTICE
    )
    # Second usage du modèle : répondre à une question de l'humain avant qu'il
    # tranche. Même nœud, même règle — donc même simulation.
    monkeypatch.setattr(
        diagnose_mod,
        "repondre",
        lambda contexte, conversation, question: f"(réponse factice à : {question})",
    )


@pytest.fixture(autouse=True)
def aucun_client_groq(monkeypatch):
    """Seconde barrière : interdire la **création** d'un client Groq.

    La fixture précédente neutralise la seule couture LLM connue aujourd'hui.
    Celle-ci couvre celles de demain : si un appel au modèle apparaît ailleurs
    — dans un nœud, un tool, un script — la suite échoue bruyamment au lieu de
    partir sur l'API sans que personne ne le remarque.

    C'est le même raisonnement que pour les garde-fous du graphe : on préfère un
    échec visible à un comportement silencieux qu'on ne découvre qu'à la facture.
    """

    def refus():
        raise AssertionError(
            "Un test a tenté d'ouvrir un client Groq. Les tests ne doivent jamais "
            "appeler un vrai LLM — simulez `diagnostiquer` (cf. tests/conftest.py)."
        )

    monkeypatch.setattr("agent.llm._client", refus)
