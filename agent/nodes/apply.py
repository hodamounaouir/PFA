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
    fix = state["fix_override"] or propose_par_agent

    return {
        "applied_fix": fix,
        "logs": [
            log_entry(
                "apply",
                "correction appliquée (stub, aucune écriture réelle)",
                table=state["table"],
                fix=fix,
                reecrite_par_humain=bool(state["fix_override"]),
                decideur=state["decided_by"],
            )
        ],
    }
