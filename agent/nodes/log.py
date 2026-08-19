"""Nœud `log` — la sortie unique du graphe, et son seul point d'écriture (4.4).

**Tous** les chemins passent par ici avant END — y compris « rien d'anormal » et
« refusé ». Ce n'est pas de la discipline, c'est topologique : aucun run ne peut
se terminer sans laisser de trace, et un test le prouve depuis la phase 3.

Journaliser un run qui n'a rien trouvé n'est pas de la comptabilité :

  - un faux positif est une **donnée de mesure** — la précision de la phase 8 se
    calcule sur les incidents `rejected` ;
  - c'est cette ligne que relira le **filtre de silence** pour ne plus
    resoumettre une signature déjà refusée ;
  - et « l'agent n'a rien signalé » deviendrait indistinguable de « l'agent n'a
    pas tourné », ce qui est le pire état d'un système de surveillance.

## Une écriture qui échoue ne perd pas le run

Si `INCIDENTS` est injoignable, le nœud journalise l'échec et rend la main : le
graphe se termine normalement. Le raisonnement est le même que pour la panne du
LLM en 3.3 — la trace est précieuse, mais la perdre ne doit pas emporter le
travail déjà fait, ni empêcher l'humain de voir ce qui a été constaté.

Conséquence assumée et **dite** : ce run-là ne comptera pas au benchmark. Mieux
vaut un trou signalé qu'un run avalé.
"""

import uuid

from agent.incidents import signature, texte
from agent.state import AgentState, log_entry

# ⚠️ On importe les **fonctions**, pas le module : `agent.tools` réexporte chaque
# tool sous le nom de son module, si bien que `from agent.tools import write_log`
# rend le `StructuredTool` et non le module qui le contient. Quatrième occurrence
# de ce piège dans le projet (conftest, test_tools, le lanceur de sous-processus,
# ici) — il coûte à chaque fois une erreur qui ne ressemble pas à sa cause.
from agent.tools.write_log import ecrire, serialiser


def log(state: AgentState) -> dict:
    validation = state["validation"] or {}
    anomalies = state["anomalies"] or []
    signatures = [texte(signature(a)) for a in anomalies]

    incident = {
        "incident_id": str(uuid.uuid4()),
        "dataset": state["dataset"],
        "layer": state["layer"],
        "table_name": state["table"],
        "batch_id": state["batch_id"],
        "anomalies": serialiser(anomalies),
        "signatures": serialiser(signatures),
        "diagnosis": serialiser(state["diagnosis"]),
        "proposed_fix": (state["diagnosis"] or {}).get("proposed_fix"),
        "human_decision": state["human_decision"],
        "decided_by": state["decided_by"],
        "decided_at": state["decided_at"],
        "applied_fix": state["applied_fix"],
        "validation_status": validation.get("status"),
        "duration_s": None,
    }

    journal = {
        # ce qui a été constaté
        "anomalies": len(anomalies),
        "signatures": signatures,
        # ce que l'humain a répondu — None si le run n'a jamais eu à demander
        "decision": state["human_decision"],
        "decideur": state["decided_by"],
        # ce qui a été fait, selon la branche empruntée
        "applied_fix": state["applied_fix"],
        "contract_version": state["contract_version"],
        "validation": validation.get("status"),
        # combien d'étapes ce run a traversées
        "etapes": len(state["logs"]) + 1,
    }

    try:
        journal["incident_id"] = ecrire(incident)
        message = "run journalisé dans INCIDENTS"
    except Exception as exc:  # noqa: BLE001 — voir l'en-tête : on ne perd pas le run
        journal["incident_id"] = None
        journal["echec_ecriture"] = f"{type(exc).__name__}: {exc}"
        message = "run terminé — journal INCIDENTS indisponible"

    return {"logs": [log_entry("log", message, **journal)]}
