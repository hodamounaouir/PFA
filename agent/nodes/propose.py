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

L'humain a **trois décisions possibles**, et la distinction entre les deux « non »
est ce qui empêche le contrat de vieillir :

  - `approved`        → la donnée est fausse          → `apply` corrige
  - `amend_contract`  → la donnée est juste,
                        c'est la règle qui a vieilli  → `amend` passe le contrat en v2
  - `rejected`        → rien à changer, cas isolé     → `log` seul, signature mise en silence

Plus une **quatrième réponse qui n'est pas une décision** : `question`. Elle ne
clôt rien, elle diffère — le graphe repart vers `diagnose`, la réponse revient, et
la proposition attend de nouveau. Un humain à qui on ne laisse que trois boutons
approuve vite et mal ; celui qui peut demander « pourquoi ? » décide en
connaissance de cause. C'est la meilleure réponse à la question de jury « et s'il
approuve sans lire ? » : le dialogue est conservé dans l'état, donc dans le
journal, donc dans `INCIDENTS`.

**Discuter ne rapproche pas de l'écriture.** Dix questions n'ouvrent pas `apply` :
il garde son unique arête entrante, et un test le vérifie après une longue
discussion.
"""

from datetime import datetime, timezone

from langgraph.types import interrupt

from agent.impact import estimer

from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    DEMANDE_QUESTION,
    AgentState,
    echange,
    log_entry,
)

# Ordre d'affichage à l'humain — du plus fréquent au plus rare.
CHOIX = (DECISION_APPROVED, DECISION_AMEND, DECISION_REJECTED)

# Plafond d'échanges avant décision. Sans lui, la boucle propose → diagnose →
# propose peut tourner indéfiniment — notamment si le modèle est en panne et
# répond « je ne peux pas répondre » à chaque tour, ce que l'humain pourrait
# relancer sans fin.
#
# Au-delà, la question n'est pas traitée et le run se termine **sans décision** :
# rien n'est écrit, tout est journalisé, et l'humain peut relancer un run. C'est
# la direction sûre — un run qui finit à tort en « rien fait » se rattrape.
MAX_ECHANGES = 10


def build_proposal(state: AgentState) -> dict:
    """La proposition soumise à l'humain — la charge utile de `interrupt()`.

    Isolée dans sa propre fonction pour trois raisons : elle est testable sans
    le graphe, elle est telle quelle le payload de `interrupt()`, et c'est elle
    que Streamlit affichera en phase 6. Une seule définition de « ce qu'on montre
    à l'humain ».

    Le champ **`impact` est le plus important de tous** : sans lui, personne ne
    peut juger. « 1 ligne sur 351 » paraît négligeable jusqu'à voir qu'elle
    déplace un indicateur métier de 54 % — et un humain qui ne peut pas juger
    n'approuve pas, il signe. Calculé depuis 5.1 par `agent/impact.py`, **sans
    aucune requête** : sur ce que `profile` a déjà mesuré, faute de quoi la
    proposition comparerait un lot d'il y a dix minutes à une base de maintenant.
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
        "impact": estimer(state["anomalies"], state["profile"]),
        "past_incidents": state["past_incidents"],
        "choix": list(CHOIX),
        # le dialogue déjà tenu, pour que l'humain reprenne où il en était même
        # s'il revient le lendemain depuis un autre poste
        "conversation": state["conversation"],
        "questions_restantes": max(0, MAX_ECHANGES - len(state["conversation"])),
    }


def lire_reponse(reponse) -> dict:
    """Traduit ce qu'a injecté l'humain en champs d'état.

    Deux formes acceptées, parce qu'elles répondent à deux besoins :

      - une **chaîne** — `"approved"` — pour le cas courant en ligne de commande ;
      - un **dictionnaire** — `{"decision": ..., "decided_by": ..., "fix_override": ...}`
        — dès qu'on veut tracer qui a décidé, ou substituer sa propre correction.

    Une troisième forme sert à **poser une question** plutôt qu'à décider :
    `{"decision": "question", "question": "pourquoi … ?"}`.

    Toute autre forme (un nombre, `None`, un objet inattendu) est traitée comme
    une **absence de décision** : on ne devine pas ce que l'humain a voulu dire.
    L'aiguillage renverra alors le run vers `log`, sans rien écrire — même
    principe que le défaut de `route_after_propose`.
    """
    if isinstance(reponse, str):
        reponse = {"decision": reponse}
    if not isinstance(reponse, dict):
        return {
            "human_decision": None,
            "decided_by": None,
            "fix_override": None,
            "question": None,
        }

    decision = reponse.get("decision", reponse.get("human_decision"))
    question = reponse.get("question")
    return {
        # aucune normalisation (casse, espaces) : une décision approximative doit
        # être rejetée, pas rattrapée. « Approved » n'est pas « approved ».
        "human_decision": decision if isinstance(decision, str) else None,
        "decided_by": reponse.get("decided_by"),
        "fix_override": reponse.get("fix_override"),
        # une question vide n'en est pas une : elle retombera en « sans décision »
        "question": question.strip()
        if isinstance(question, str) and question.strip()
        else None,
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
    question = reponse.pop("question")

    # Demander sans rien demander n'est pas une demande. Sans cette ligne,
    # `human_decision` resterait à "question" et l'aiguillage renverrait vers
    # `diagnose` — qui ne trouverait aucune question à traiter, re-diagnostiquerait,
    # et reviendrait ici : une boucle qui tourne sans que personne n'ait parlé.
    if reponse["human_decision"] == DEMANDE_QUESTION and not question:
        reponse["human_decision"] = None

    # --- L'humain demande à comprendre avant de trancher --------------------
    if reponse["human_decision"] == DEMANDE_QUESTION:
        if len(state["conversation"]) >= MAX_ECHANGES:
            # Plafond atteint : on ne traite pas la question et le run se termine
            # sans décision. Rien n'est écrit, tout est journalisé, l'humain peut
            # relancer un run. La question est quand même conservée dans le
            # dialogue : elle est restée sans réponse, le journal doit le montrer.
            return {
                "human_decision": None,
                "decided_by": reponse["decided_by"],
                "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "conversation": [echange("humain", question)],
                "logs": [
                    log_entry(
                        "propose",
                        f"plafond de {MAX_ECHANGES} échanges atteint — run clos sans décision",
                        question=question[:120],
                    )
                ],
            }

        # `human_decision` porte "question", qui n'est pas une décision : c'est ce
        # que verra l'aiguillage pour renvoyer vers `diagnose`. Rien d'autre n'est
        # touché — ni la correction, ni le contrat, ni la validation.
        return {
            "human_decision": DEMANDE_QUESTION,
            "decided_by": reponse["decided_by"],
            "conversation": [echange("humain", question)],
            "logs": [
                log_entry(
                    "propose",
                    "question posée par l'humain",
                    question=question[:120],
                    echange=len(state["conversation"]) + 1,
                )
            ],
        }

    # --- L'humain tranche ---------------------------------------------------
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
                echanges=len(state["conversation"]),
            )
        ],
    }
