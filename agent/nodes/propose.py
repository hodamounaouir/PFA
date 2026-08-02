"""Nœud `propose` — la pause de validation humaine (stub, phase 3.1).

C'est le nœud central du projet : **rien ne s'applique sans passer par ici**.
Structurellement, `diagnose` n'a qu'une seule sortie — `propose` — et `apply`
n'a qu'une seule entrée — `propose` avec `approved`. C'est ce que prouve le
test P3.

À l'étape 5, ce nœud appellera `interrupt()` : le graphe s'arrête, son état est
sauvegardé par le checkpointer, et il ne repart qu'une fois la décision injectée
(`scripts/decide.py`, puis les boutons Streamlit en phase 6). Pour l'instant il
ne fait que journaliser, ce qui permet de parcourir les 3 branches en test avant
même d'avoir branché le checkpointer.

L'humain a **trois réponses possibles**, et la distinction entre les deux « non »
est ce qui empêche le contrat de vieillir :

  - `approved`        → la donnée est fausse          → `apply` corrige
  - `amend_contract`  → la donnée est juste,
                        c'est la règle qui a vieilli  → `amend` passe le contrat en v2
  - `rejected`        → rien à changer, cas isolé     → `log` seul, signature mise en silence
"""

from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    AgentState,
    log_entry,
)

# Ordre d'affichage à l'humain — du plus fréquent au plus rare.
CHOIX = (DECISION_APPROVED, DECISION_AMEND, DECISION_REJECTED)


def build_proposal(state: AgentState) -> dict:
    """La proposition soumise à l'humain — future charge utile de `interrupt()`.

    Isolée dans sa propre fonction pour trois raisons : elle est testable sans
    le graphe, elle deviendra telle quelle le payload de `interrupt()`, et c'est
    elle que Streamlit affichera en phase 6. Une seule définition de « ce qu'on
    montre à l'humain ».

    Le champ **`impact` est le plus important de tous** : sans lui, personne ne
    peut juger. « 1 ligne sur 351 » paraît négligeable jusqu'à voir qu'elle
    déplace un indicateur métier de 54 %. Il sera calculé en phase 5.1.
    """
    diagnosis = state["diagnosis"] or {}
    return {
        # de quoi on parle
        "dataset": state["dataset"],
        "layer": state["layer"],
        "table": state["table"],
        "batch_id": state["batch_id"],
        # ce qui a été constaté (faits) puis supposé (LLM)
        "anomalies": state["anomalies"],
        "root_cause": diagnosis.get("root_cause"),
        "proposed_fix": diagnosis.get("proposed_fix"),
        "explanation": diagnosis.get("explanation"),
        # de quoi décider
        "impact": "non calculé (stub)",
        "past_incidents": state["past_incidents"],
        "choix": list(CHOIX),
    }


def propose(state: AgentState) -> dict:
    proposal = build_proposal(state)
    # Ce nœud ne décide rien et ne touche pas à `human_decision` : la décision
    # vient de l'extérieur, jamais de l'agent. C'est toute la différence entre
    # un système de suggestion et un système autonome.
    return {
        "logs": [
            log_entry(
                "propose",
                "proposition soumise à l'humain (stub, sans interrupt)",
                anomalies=len(proposal["anomalies"]),
                fix=proposal["proposed_fix"],
                antecedents=len(proposal["past_incidents"]),
            )
        ]
    }
