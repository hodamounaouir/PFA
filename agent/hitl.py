"""La voie **unique** de reprise d'un run en pause (phase 6.1).

Un run s'arrête sur `propose` et attend. Deux interfaces le reprennent : la
ligne de commande (`scripts/decide.py`) et l'écran de validation Streamlit. Elles
doivent passer **exactement par le même code** — non par souci d'élégance, mais
parce qu'une seconde voie de reprise serait une seconde façon de contourner P3.

Le jour où un bouton écrirait sa propre injection de décision, la garantie
« aucun chemin n'atteint `apply` sans approbation » ne vaudrait plus que pour
les chemins qu'on a testés.

## Ce module ne parle à personne

Aucun `print`, aucun composant d'interface : il rend des **dictionnaires**. La
mise en forme appartient à l'appelant — un terminal et un navigateur n'ont pas
les mêmes besoins, et mêler les deux obligerait l'un à dépendre de l'autre.

## Une erreur est une donnée, pas une exception

`trancher()` rend `{"ok": False, "code": …, "erreur": "…"}` plutôt que de lever
sur un refus prévisible (fil inconnu, correction réécrite sur un refus).
Streamlit afficherait une trace là où l'utilisateur attend une phrase, et un
script devrait l'intercepter pour la transformer en message. Les pannes réelles,
elles, remontent normalement.

Le **code** accompagne la phrase parce que les deux interfaces n'ont pas le même
vocabulaire : le terminal veut dire « utilisez `--fix` », le navigateur veut
désactiver un bouton. Ce module ne connaît ni l'un ni l'autre — il nomme la
situation, chacun la traduit.
"""

from typing import Optional

from langgraph.types import Command

from agent.graph import (
    CHECKPOINT_DB,
    agent_persistant,
    proposition_en_attente,
    thread,
)
from agent.state import (
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
    DEMANDE_QUESTION,
)

# Les situations qu'une interface peut vouloir traiter à sa façon.
DECISION_INCONNUE = "decision_inconnue"
CORRECTION_SANS_APPROBATION = "correction_sans_approbation"
AUCUNE_PROPOSITION = "aucune_proposition"
QUESTION_VIDE = "question_vide"
PLAFOND_ATTEINT = "plafond_atteint"

# Les trois réponses qui **tranchent** — elles terminent le run.
DECISIONS = (DECISION_APPROVED, DECISION_AMEND, DECISION_REJECTED)


def proposition(thread_id: str, db=CHECKPOINT_DB) -> Optional[dict]:
    """La proposition qui attend sur ce fil, ou `None`.

    Sert aux deux interfaces avant de décider : on ne demande pas à quelqu'un de
    trancher sans lui montrer d'abord ce qu'il tranche.
    """
    with agent_persistant(db) as app:
        etat = app.get_state(thread(thread_id))
        for tache in etat.tasks:
            for interruption in tache.interrupts or ():
                return interruption.value
    return None


def trancher(
    thread_id: str,
    decision: str,
    par: Optional[str] = None,
    fix_override: Optional[str] = None,
    db=CHECKPOINT_DB,
) -> dict:
    """Injecte une décision humaine et laisse le graphe finir son parcours.

    Rend `{ok, decision, parcours, applied_fix, contract_version, en_attente}`
    — ou `{ok: False, erreur}` si la demande n'a pas de sens.
    """
    if decision not in DECISIONS:
        return {
            "ok": False,
            "code": DECISION_INCONNUE,
            "erreur": f"décision inconnue : {decision!r} — attendu "
            f"{', '.join(DECISIONS)}",
        }

    # ⚠️ `fix_override` n'a de sens que sur une approbation : amender un contrat
    # ou refuser n'écrit rien dans les données, donc il n'y a **pas de SQL à
    # réécrire**. L'accepter en silence laisserait croire le contraire à qui
    # vient de taper une correction.
    if fix_override and decision != DECISION_APPROVED:
        return {
            "ok": False,
            "code": CORRECTION_SANS_APPROBATION,
            "erreur": "une correction réécrite n'a de sens qu'avec une "
            "approbation — les deux autres réponses n'écrivent rien",
        }

    with agent_persistant(db) as app:
        config = thread(thread_id)
        if _rien_en_attente(app, config):
            return {
                "ok": False,
                "code": AUCUNE_PROPOSITION,
                "erreur": f"aucun run en attente pour le fil {thread_id!r}",
            }

        resultat = app.invoke(
            Command(
                resume={
                    "decision": decision,
                    "decided_by": par,
                    "fix_override": fix_override,
                }
            ),
            config,
        )

    return {
        "ok": True,
        "decision": decision,
        "parcours": [entree["node"] for entree in resultat["logs"]],
        "applied_fix": resultat["applied_fix"],
        "contract_version": resultat["contract_version"],
        # Un run peut se ré-interrompre : une autre proposition attend derrière.
        "en_attente": proposition_en_attente(resultat) is not None,
    }


def questionner(
    thread_id: str, question: str, par: Optional[str] = None, db=CHECKPOINT_DB
) -> dict:
    """Pose une question **sans trancher** — le graphe repart vers `diagnose`.

    C'est la seule branche qui **remonte** dans le graphe. Elle existe parce
    qu'un humain à qui on ne laisse que trois boutons approuve vite et mal
    (`DESIGN.md` §5.3) : pouvoir demander « pourquoi ? » est ce qui rend
    l'approbation informée.
    """
    if not (question or "").strip():
        return {
            "ok": False,
            "code": QUESTION_VIDE,
            "erreur": "une question vide n'en est pas une",
        }

    with agent_persistant(db) as app:
        config = thread(thread_id)
        if _rien_en_attente(app, config):
            return {
                "ok": False,
                "code": AUCUNE_PROPOSITION,
                "erreur": f"aucun run en attente pour le fil {thread_id!r}",
            }

        resultat = app.invoke(
            Command(
                resume={
                    "decision": DEMANDE_QUESTION,
                    "question": question,
                    "decided_by": par,
                }
            ),
            config,
        )

    suite = proposition_en_attente(resultat)
    if suite is None:
        # Le run s'est terminé au lieu de revenir : plafond d'échanges atteint.
        # Rien n'a été écrit, et c'est la direction sûre — mais il faut le dire,
        # sinon l'humain attendrait une réponse qui ne viendra pas.
        return {
            "ok": False,
            "code": PLAFOND_ATTEINT,
            "erreur": "plafond d'échanges atteint — le run s'est clos sans "
            "décision. Rien n'a été écrit ; relancez un run pour reprendre.",
        }

    return {
        "ok": True,
        "reponse": suite["conversation"][-1]["message"],
        "questions_restantes": suite["questions_restantes"],
        "conversation": suite["conversation"],
    }


def _rien_en_attente(app, config) -> bool:
    """Y a-t-il vraiment une pause sur ce fil ?

    Vérifié **avant** d'injecter : `Command(resume=…)` sur un fil qui n'attend
    rien relancerait le graphe depuis le début, donc referait un profilage et
    une détection — et l'humain croirait avoir tranché une proposition qui
    n'existait plus.
    """
    etat = app.get_state(config)
    return not any(tache.interrupts for tache in etat.tasks)
