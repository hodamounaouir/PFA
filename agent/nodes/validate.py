"""Nœud `validate` — vérifie que la correction a eu l'effet attendu (stub, phase 3.1).

On ne croit **jamais** une correction sur parole : on la re-mesure. `apply` a pu
s'exécuter sans erreur SQL tout en ne réglant rien — une clause `WHERE` trop
étroite, une correction appliquée à la mauvaise couche.

Le principe le plus important de ce nœud est ce qu'il **ne fait pas** :

    en cas d'échec  →  validation_status = "failed_manual_review"
                       et l'humain reprend la main.
                       **Aucune re-tentative automatique.**

C'est une décision assumée (§5.3 du cahier). Une boucle de retry masquerait le
problème au lieu de le remonter : au bout de trois essais l'agent aurait
peut-être « réussi », sans que personne ne sache qu'il s'y est repris à trois
fois — ni pourquoi.

Réel en phase 5.3 : re-profilage de la table via le connecteur, puis comparaison
de la métrique fautive avant/après.
"""

from agent.state import AgentState, log_entry

VALIDATION_OK = "success"
VALIDATION_KO = "failed_manual_review"


def validate(state: AgentState) -> dict:
    anomalies = state["anomalies"]

    # Le graphe n'arrive ici qu'après `apply`, donc après un écart — mais un
    # nœud ne suppose jamais d'où il vient.
    if not anomalies:
        return {
            "validation": {
                "status": VALIDATION_OK,
                "metric": None,
                "before": None,
                "after": None,
            },
            "logs": [log_entry("validate", "rien à vérifier")],
        }

    principal = anomalies[0]
    metric = f"{principal.get('type')}({principal.get('colonne')})"

    return {
        "validation": {
            "status": VALIDATION_OK,  # le stub réussit toujours
            "metric": metric,
            "before": principal.get("observe"),
            # En 5.3 : la valeur re-mesurée après correction. Ici on simule un
            # retour à la référence attendue.
            "after": principal.get("reference"),
        },
        "logs": [
            log_entry(
                "validate",
                "correction vérifiée (stub, sans re-profilage)",
                status=VALIDATION_OK,
                metric=metric,
            )
        ],
    }
