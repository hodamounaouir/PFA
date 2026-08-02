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

from agent.state import DECISION_AMEND, AgentState, log_entry


def _version_suivante(actuelle: str | None) -> str:
    """`v1` → `v2`, et `None` → `v1` si la table n'avait pas encore de contrat."""
    if not actuelle:
        return "v1"
    try:
        return f"v{int(actuelle.lstrip('v')) + 1}"
    except ValueError:
        # version non numérotée : on ne devine pas, on repart proprement
        return "v1"


def amend(state: AgentState) -> dict:
    # Même seconde barrière que dans `apply` : on ne modifie une règle que sur
    # décision humaine explicite. Un contrat amendé par erreur rendrait l'agent
    # aveugle à une vraie anomalie — silencieusement.
    if state["human_decision"] != DECISION_AMEND:
        raise RuntimeError(
            "amend atteint sans décision d'amendement "
            f"(human_decision={state['human_decision']!r})"
        )

    depuis = state["contract_version"]
    vers = _version_suivante(depuis)
    return {
        # aucune clé de données n'est retournée : ni profile, ni anomalies,
        # ni validation. C'est ce qui distingue `amend` d'`apply`.
        "contract_version": vers,
        "logs": [
            log_entry(
                "amend",
                "contrat amendé (stub, aucune écriture sur les données)",
                table=state["table"],
                depuis=depuis,
                vers=vers,
                decideur=state["decided_by"],
            )
        ],
    }
