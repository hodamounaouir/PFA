"""Nœud `amend` — met à jour le contrat, jamais les données (stub, phase 3.1).

Ajouté par la révision du 2026-07-28. Il traite le cas où **la donnée est juste
et c'est la règle qui a vieilli** : un nouveau moyen de paiement apparaît, une
borne métier a bougé, une valeur inconnue est en réalité légitime.

C'est le miroir d'`apply` :

    apply  →  la donnée est fausse  →  écrit dans les DONNÉES
    amend  →  la règle est fausse   →  écrit dans le CONTRAT

Sans cette branche, un contrat figé finit par crier à chaque évolution normale
du métier, l'équipe s'habitue à ignorer les alertes, et l'agent meurt. C'est le
mécanisme anti-obsolescence.

Réel en phase 5.3 : écrit `contracts/<dataset>/<table>.v2.yaml` et journalise le
diff de clause. Un test prouvera qu'aucune ligne de données n'a bougé (comptage
avant/après inchangé).
"""

from agent.contracts.amend import relacher, version_suivante
from agent.contracts.loader import ecrire
from agent.state import DECISION_AMEND, AgentState, log_entry


def amend(state: AgentState) -> dict:
    # Même seconde barrière que dans `apply` : on ne modifie une règle que sur
    # décision humaine explicite. Un contrat amendé par erreur rendrait l'agent
    # aveugle à une vraie anomalie — silencieusement.
    if state["human_decision"] != DECISION_AMEND:
        raise RuntimeError(
            "amend atteint sans décision d'amendement "
            f"(human_decision={state['human_decision']!r})"
        )

    contrat = state["contract"] or {}
    if not contrat.get("columns"):
        # Amender ce qui n'existe pas n'aurait pas de sens : sans contrat signé,
        # l'écart ne vient pas d'une clause. On le dit plutôt que d'écrire un
        # fichier vide qui gouvernerait ensuite la surveillance.
        return {
            "logs": [
                log_entry(
                    "amend",
                    "aucun contrat validé à amender",
                    table=state["table"],
                    decideur=state["decided_by"],
                )
            ]
        }

    depuis = contrat.get("version")
    nouveau = version_suivante(contrat, state["decided_by"])
    diffs = relacher(nouveau, state["anomalies"])

    if not diffs:
        # Aucune clause n'a bougé : écrire une v2 identique à la v1 encombrerait
        # l'historique d'une version qui ne dit rien. Un amendement qui
        # n'amende rien n'est pas un amendement.
        return {
            "logs": [
                log_entry(
                    "amend",
                    "aucune clause à relâcher — contrat inchangé",
                    table=state["table"],
                    version=depuis,
                    decideur=state["decided_by"],
                )
            ]
        }

    chemin = ecrire(nouveau, state["dataset"])

    return {
        # aucune clé de données n'est retournée : ni profile, ni anomalies,
        # ni validation. C'est ce qui distingue `amend` d'`apply`.
        "contract": nouveau,
        "contract_version": nouveau["version"],
        "logs": [
            log_entry(
                "amend",
                "contrat amendé — aucune écriture sur les données",
                table=state["table"],
                depuis=depuis,
                vers=nouveau["version"],
                fichier=str(chemin),
                diff=diffs,
                decideur=state["decided_by"],
            )
        ],
    }
