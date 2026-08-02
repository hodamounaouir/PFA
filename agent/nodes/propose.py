"""Nœud `propose` — la pause de validation humaine (phase 3.2).

C'est le nœud central du projet : **rien ne s'applique sans passer par ici**.
Structurellement, `diagnose` n'a qu'une seule sortie — `propose` — et `apply`
n'a qu'une seule entrée — `propose` avec `approved`. C'est ce que prouve le
test P3.

Ce nœud appelle `interrupt()` : le graphe s'arrête, son état est sauvegardé par
le checkpointer, et il ne repart qu'une fois la décision injectée
(`scripts/decide.py`, puis les boutons Streamlit en phase 6).

**Conséquence assumée** : `propose` ne peut plus être appelé comme une fonction
ordinaire. Hors de toute exécution de graphe, `interrupt()` lève un `RuntimeError`
(« Called get_config outside of a runnable context »). Ce n'est pas une gêne,
c'est la vérité du nœud : une étape dont la raison d'être est de suspendre n'a
pas de sens isolée. La partie testable seule a été extraite dans
`build_proposal()` et `lire_reponse()` ; le reste se teste au niveau du graphe.

Cas voisin à ne pas confondre : **dans** un graphe compilé mais sans
checkpointer, `interrupt()` ne lève pas — le run s'arrête ici et ne peut plus
repartir, faute d'état persisté. Le mode dégradé est donc « bloqué », jamais
« passe outre » : sans persistance, `apply` reste inatteignable.

Aucun contournement n'est prévu, pas même pour les tests (règle R3 du
`CONTRIBUTING`) : s'il existait un chemin où `propose` ne s'arrête pas, la
garantie du projet ne serait plus vérifiable — elle serait seulement probable.

⚠️ À la reprise, LangGraph **ré-exécute le nœud depuis le début** : `interrupt()`
ne repart pas « après » l'appel, il rejoue la fonction et retourne cette fois la
valeur injectée. Tout ce qui précède l'appel tourne donc deux fois. C'est sans
conséquence ici (`build_proposal` est une fonction pure), mais ce nœud ne devra
jamais faire d'écriture avant son `interrupt()`.

L'humain a **trois réponses possibles**, et la distinction entre les deux « non »
est ce qui empêche le contrat de vieillir :

  - `approved`        → la donnée est fausse          → `apply` corrige
  - `amend_contract`  → la donnée est juste,
                        c'est la règle qui a vieilli  → `amend` passe le contrat en v2
  - `rejected`        → rien à changer, cas isolé     → `log` seul, signature mise en silence
"""

from datetime import datetime, timezone

from langgraph.types import interrupt

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
    """La proposition soumise à l'humain — la charge utile de `interrupt()`.

    Isolée dans sa propre fonction pour trois raisons : elle est testable sans
    le graphe, elle est telle quelle le payload de `interrupt()`, et c'est elle
    que Streamlit affichera en phase 6. Une seule définition de « ce qu'on montre
    à l'humain ».

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


def lire_reponse(reponse) -> dict:
    """Traduit ce qu'a injecté l'humain en champs d'état.

    Deux formes acceptées, parce qu'elles répondent à deux besoins :

      - une **chaîne** — `"approved"` — pour le cas courant en ligne de commande ;
      - un **dictionnaire** — `{"decision": ..., "decided_by": ..., "fix_override": ...}`
        — dès qu'on veut tracer qui a décidé, ou substituer sa propre correction.

    Toute autre forme (un nombre, `None`, un objet inattendu) est traitée comme
    une **absence de décision** : on ne devine pas ce que l'humain a voulu dire.
    L'aiguillage renverra alors le run vers `log`, sans rien écrire — même
    principe que le défaut de `route_after_propose`.
    """
    if isinstance(reponse, str):
        reponse = {"decision": reponse}
    if not isinstance(reponse, dict):
        return {"human_decision": None, "decided_by": None, "fix_override": None}

    decision = reponse.get("decision", reponse.get("human_decision"))
    return {
        # aucune normalisation (casse, espaces) : une décision approximative doit
        # être rejetée, pas rattrapée. « Approved » n'est pas « approved ».
        "human_decision": decision if isinstance(decision, str) else None,
        "decided_by": reponse.get("decided_by"),
        "fix_override": reponse.get("fix_override"),
    }


def propose(state: AgentState) -> dict:
    proposal = build_proposal(state)

    # ⏸ Le graphe s'arrête ici. L'état est persisté par le checkpointer, et
    # l'exécution ne reprendra que sur injection d'une décision — depuis un autre
    # process, éventuellement des jours plus tard.
    #
    # Ce nœud ne décide rien : il transmet ce qu'on lui a répondu. La décision
    # vient de l'extérieur, jamais de l'agent. C'est toute la différence entre
    # un système de suggestion et un système autonome.
    reponse = lire_reponse(interrupt(proposal))

    return {
        **reponse,
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "logs": [
            log_entry(
                "propose",
                "décision humaine reçue",
                anomalies=len(proposal["anomalies"]),
                fix=proposal["proposed_fix"],
                antecedents=len(proposal["past_incidents"]),
                decision=reponse["human_decision"],
                decideur=reponse["decided_by"],
            )
        ],
    }
