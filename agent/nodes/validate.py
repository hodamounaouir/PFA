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

from agent.incidents import signature, texte
from agent.nodes.detect import FAMILLES
from agent.state import AgentState, log_entry
from agent.tools.profile_table import profile_table

VALIDATION_OK = "success"

# ⚠️ Le nom vient du cahier (§5.5) et il est explicite à dessein : *manual
# review*, pas *failed*. Une vérification en échec n'appelle pas une
# re-tentative mais un humain — et le nom du statut est le premier endroit où
# cette règle se lit.
VALIDATION_ECHEC = "failed_manual_review"
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

    # ⭐ On **re-mesure**, on ne suppose pas. Un `validate` qui se contenterait
    # de croire `apply` sur parole ne vérifierait rien : il confirmerait que la
    # requête a tourné, pas qu'elle a eu l'effet attendu — et c'est exactement
    # la différence entre « corrigé » et « cru corrigé ».
    fiche = profile_table.invoke(
        {
            "dataset": state["dataset"],
            "table": state["table"],
            "batch_id": state["batch_id"],
        }
    )
    if fiche is None:
        return _echec(
            state, "la table a disparu entre la correction et sa vérification"
        )

    # La détection est rejouée sur le nouveau profil, avec **les mêmes
    # références**. Comparer par *signature* plutôt que par valeur permet de
    # traiter les cinq familles d'un coup : ce qu'on veut savoir n'est pas « la
    # valeur a-t-elle changé » mais « l'écart existe-t-il encore ».
    apres = _redetecter({**state, "profile": fiche})
    attendues = {texte(signature(a)) for a in anomalies}
    restantes = sorted(attendues & {texte(signature(a)) for a in apres})

    principal = anomalies[0]
    metric = f"{principal.get('type')}({principal.get('colonne')})"

    if restantes:
        return _echec(
            state,
            f"{len(restantes)} écart(s) toujours présent(s) après correction",
            metric=metric,
            avant=principal.get("observe"),
            restantes=restantes,
        )

    return {
        "validation": {
            "status": VALIDATION_OK,
            "metric": metric,
            "before": principal.get("observe"),
            "after": _valeur_apres(principal, fiche),
        },
        "logs": [
            log_entry(
                "validate",
                "correction vérifiée par re-profilage",
                status=VALIDATION_OK,
                metric=metric,
                ecarts_restants=0,
            )
        ],
    }


def _redetecter(etat: dict) -> list:
    """Les écarts que les familles trouvent sur le profil re-mesuré.

    On appelle les familles et **non le nœud `detect`** : celui-ci applique le
    filtre de silence et écrit une ligne de journal. Ni l'un ni l'autre n'a de
    sens ici — un écart tu par une décision passée reste un écart non corrigé,
    et le journal de `validate` n'est pas celui de `detect`.
    """
    trouves = []
    for _nom, detecter in FAMILLES:
        try:
            trouves += detecter(etat)
        except Exception:  # noqa: BLE001 — une famille en panne ne vaut pas un succès
            continue
    return trouves


def _valeur_apres(principal: dict, fiche: dict):
    """Ce que la métrique vaut maintenant, quand on sait où la lire.

    `None` est une réponse honnête : toutes les anomalies ne portent pas sur une
    mesure de colonne, et inventer une valeur « après » ferait croire à une
    vérification plus précise qu'elle ne l'est.
    """
    colonne = principal.get("colonne")
    stats = ((fiche.get("columns") or {}).get(colonne)) or {}
    metrique = (principal.get("details") or {}).get("metrique")
    if metrique and metrique in stats:
        return stats[metrique]
    return None


def _echec(state, raison: str, **extra) -> dict:
    """La correction n'a pas eu l'effet attendu.

    ⚠️ **Aucune re-tentative automatique.** Un agent qui réessaie tout seul
    écrirait deux fois sans qu'un humain ait revu quoi que ce soit — alors même
    que la première écriture vient d'échouer à faire ce qu'elle promettait. Le
    run se termine, l'incident est marqué, et c'est un humain qui rouvre.
    """
    return {
        "validation": {
            "status": VALIDATION_ECHEC,
            "metric": extra.get("metric"),
            "before": extra.get("avant"),
            "after": None,
            "raison": raison,
        },
        "logs": [
            log_entry(
                "validate",
                f"vérification en échec — {raison}",
                status=VALIDATION_ECHEC,
                table=state["table"],
                **{k: v for k, v in extra.items() if k != "avant"},
            )
        ],
    }
