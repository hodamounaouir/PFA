"""Nœud `apply` — applique la correction approuvée (stub, phase 3.1).

**Le seul nœud du graphe qui écrit dans tes données.** Un sur huit. Tous les
autres lisent, mesurent, raisonnent ou journalisent.

Il n'a qu'une seule arête entrante : `propose` avec `human_decision == approved`.
C'est ce que prouve le test P3, et c'est la garantie centrale du projet.

L'humain peut approuver **sa propre** correction plutôt que celle proposée
(`fix_override`). Sans cette possibilité, il irait corriger à la main dans la
base : la donnée serait juste, mais `INCIDENTS` ne le saurait pas, et le journal
deviendrait faux. C'est donc la traçabilité qui impose de l'accepter.

Réel en phase 5.3 — les vérifications, toutes exécutées **même après
approbation humaine**, parce qu'un humain peut approuver sans lire :

  | Vérification                                   | SQL de l'agent | SQL de l'humain |
  |------------------------------------------------|----------------|-----------------|
  | ne touche que la table diagnostiquée           | oui            | **oui**         |
  | pas de `DROP`/`TRUNCATE`/`DELETE` sans `WHERE` | oui            | **oui**         |
  | ne jamais **inventer une valeur** (test P4)    | oui            | **non**         |

La dernière ligne est volontaire : la règle « ne jamais inventer une valeur »
contraint l'**agent**, pas l'humain. L'agent ne peut pas savoir si `8000` valait
`80` ; toi, tu peux avoir appelé le fournisseur. Tu as l'autorité pour affirmer
une valeur, lui ne l'a pas. Les deux autres garde-fous restent : ils protègent
contre l'accident, pas contre le jugement.

Plus le comptage des lignes avant/après, conservé dans le journal, le tout dans
une transaction : si une vérification saute en cours de route, rien n'est écrit.
"""

from agent.corrections import controler
from agent.sql_guard import controler as controler_sql
from agent.tools._connecteur import connecteur_pour
from agent.state import DECISION_APPROVED, AgentState, log_entry


def apply(state: AgentState) -> dict:
    # Garde-fou P3, seconde barrière. La topologie du graphe interdit déjà
    # d'arriver ici sans approbation — cette vérification couvre le cas où le
    # graphe serait mal recâblé un jour. Si elle se déclenche, c'est un **bug de
    # câblage**, pas un cas métier : on arrête le run bruyamment plutôt que de
    # toucher aux données.
    if state["human_decision"] != DECISION_APPROVED:
        raise RuntimeError(
            "apply atteint sans approbation humaine "
            f"(human_decision={state['human_decision']!r}) — violation de P3"
        )

    # La correction de l'humain prime sur celle de l'agent. On trace laquelle a
    # tourné : en phase 8, le rapport « proposée telle quelle / réécrite /
    # refusée » mesure trois choses différentes — l'agent a bien vu ET bien
    # proposé, il a bien vu mais mal proposé, il n'aurait pas dû alerter.
    propose_par_agent = (state["diagnosis"] or {}).get("proposed_fix")
    reecrite = bool(state["fix_override"])
    fix = state["fix_override"] or propose_par_agent

    # ⭐ Garde-fou P6 (phase 5.2) — **il s'applique après l'approbation, et c'est
    # tout son intérêt.** Un humain peut approuver sans lire ; la règle « ne
    # jamais inventer une valeur » ne protège que si elle survit à un « oui ».
    #
    # Mais elle ne s'applique qu'au SQL **de l'agent**. Si l'humain a réécrit la
    # correction, il engage son autorité : il peut avoir appelé le fournisseur,
    # l'agent ne le peut pas. Les autres garde-fous restent pour les deux — ils
    # protègent de l'accident, pas du jugement.
    refus = [] if reecrite else controler(fix, state["anomalies"], state["profile"])

    if refus:
        # On **ne lève pas** : ce n'est pas un bug de câblage mais un cas métier
        # — le modèle a proposé quelque chose d'inacceptable. Le run doit se
        # terminer normalement par `log`, sinon la trace de ce refus serait
        # perdue au moment précis où elle est la plus instructive.
        sortie = _refus(
            state, fix, refus, "correction REFUSÉE malgré l'approbation — invariant P6"
        )
        sortie["logs"][0]["recours"] = (
            "réécrivez la correction avec --fix : votre autorité n'est pas "
            "soumise à P6, celle de l'agent l'est"
        )
        return sortie

    # Les deux garde-fous qui valent pour **tout le monde**, agent comme humain :
    # ils protègent de l'accident, pas du jugement. Le renommage de table est la
    # seule exception DDL, et seulement si un écart d'inventaire l'appelle
    # (décision 14) — une exception qu'aucun fait ne justifie n'en est pas une.
    bornes = controler_sql(
        fix, state["table"], renommage_autorise=_renommage_constate(state)
    )
    if bornes:
        return _refus(
            state, fix, bornes, "correction REFUSÉE — hors des bornes d'apply"
        )

    if not fix:
        # Rien à appliquer : le diagnostic n'a rien proposé (LLM en panne), et
        # l'humain a approuvé un vide. On le dit plutôt que d'écrire `NULL`.
        return _refus(
            state,
            fix,
            ["aucune correction à appliquer"],
            "rien à appliquer — approbation sans correction",
        )

    with connecteur_pour(state["dataset"], state["table"]) as (connecteur, declaree):
        mesures = connecteur.appliquer(
            fix, state["table"], declaree.batch_column, state["batch_id"]
        )

    return {
        "applied_fix": fix,
        "logs": [
            log_entry(
                "apply",
                "correction appliquée",
                table=state["table"],
                fix=fix,
                reecrite_par_humain=reecrite,
                decideur=state["decided_by"],
                **mesures,
            )
        ],
    }


def _renommage_constate(state: AgentState) -> bool:
    """Un écart d'inventaire réclame-t-il de restaurer un nom de table ?

    L'autorisation DDL ne se donne pas parce que le SQL en a la forme, mais
    parce qu'un **fait constaté** l'appelle. Sans ça, il suffirait au modèle
    d'écrire un renommage de table pour franchir un garde-fou qui existe
    précisément pour l'en empêcher.
    """
    return any(
        a.get("famille") == "inventaire"
        and a.get("type") in ("renommage_probable", "table_absente")
        for a in state["anomalies"] or []
    )


def _refus(state: AgentState, fix, motifs: list, message: str) -> dict:
    """Un refus : rien n'est écrit, tout est journalisé.

    On **ne lève pas** — voir le refus P6 plus haut : `log` est la sortie unique,
    et une exception ferait perdre la trace au moment où elle instruit le plus.
    """
    return {
        "applied_fix": None,
        "logs": [
            log_entry(
                "apply",
                message,
                table=state["table"],
                fix_refuse=fix,
                refus=motifs,
                decideur=state["decided_by"],
            )
        ],
    }
