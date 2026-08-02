"""Nœud `log` — la sortie unique du graphe (stub, phase 3.1).

**Tous** les chemins passent par ici avant END — y compris « rien d'anormal » et
« refusé ». Ce n'est pas de la discipline, c'est topologique : aucun run ne peut
se terminer sans laisser de trace, et un test le prouve à l'étape 8.

Journaliser un refus n'est pas un détail administratif :

  - un faux positif est une **donnée de mesure** — sans lui, la précision de la
    phase 8 est incalculable ;
  - c'est cette ligne que relira le filtre de silence (phase 4.4) pour ne plus
    resoumettre une signature déjà refusée par un humain.

Réel en phase 4.4 : écrit une ligne dans `OPS.INCIDENTS` (append-only). Ce nœud
est le seul point d'écriture du journal métier — d'où l'intérêt qu'il soit aussi
le seul point de sortie.
"""

from agent.state import AgentState, log_entry


def log(state: AgentState) -> dict:
    validation = state["validation"] or {}
    return {
        "logs": [
            log_entry(
                "log",
                "run terminé (stub, aucune écriture dans INCIDENTS)",
                # ce qui a été constaté
                anomalies=len(state["anomalies"]),
                # ce que l'humain a répondu — None si le run n'a jamais eu à demander
                decision=state["human_decision"],
                decideur=state["decided_by"],
                # ce qui a été fait, selon la branche empruntée
                applied_fix=state["applied_fix"],
                contract_version=state["contract_version"],
                validation=validation.get("status"),
                # combien d'étapes ce run a traversées
                etapes=len(state["logs"]) + 1,
            )
        ]
    }
