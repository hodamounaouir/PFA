"""Nœud `diagnose` — le seul nœud qui appelle le LLM (phase 3.3).

Répartition des rôles, à ne jamais brouiller :

    detect    (code)  →  QUOI      « telle colonne : 30,1 % de nulls, seuil 10 % »
    diagnose  (LLM)   →  POURQUOI  « probable échec du job amont »

Si le LLM faisait la détection, elle cesserait d'être reproductible et le
benchmark de la phase 8 n'aurait plus de sens. Il reçoit des **agrégats**, jamais
des lignes : il raisonne sur des chiffres, pas sur des clients.

Deux garde-fous que ce nœud tient :

  - **Ne jamais inventer une valeur.** Face à une valeur hors bornes, l'agent ne
    peut pas savoir si `8000` vaut `80,00` ou vraiment `8000`. Proposer une
    substitution, c'est fabriquer de la donnée. Il propose donc d'**isoler**,
    de **mettre à NULL** ou d'**exclure d'un agrégat** — jamais de deviner.
    C'est écrit noir sur blanc dans les consignes envoyées au modèle
    (`agent/llm.py`) ; la barrière dure, elle, sera dans `apply` (phase 5.2).
  - **Un échec ne tue pas le run.** Réseau coupé, clé absente, quota dépassé,
    JSON illisible, champ manquant : `diagnosis` reste à None et le run continue
    vers `propose`. L'humain voit alors les **faits** — que `detect` a établis
    sans LLM — et décide sans explication. C'est un mode dégradé, pas une
    panne : le plus important, l'écart constaté, est toujours là.

Enrichi en phase 4.4 : le contexte recevra aussi `past_incidents` renseignés,
la mémoire, qui permet de citer un incident identique déjà tranché (objectif O7).
"""

from agent.llm import MODELE, diagnostiquer
from agent.state import AgentState, log_entry


def construire_contexte(state: AgentState) -> dict:
    """Ce que le modèle a le droit de voir. **C'est ici que R2 se tient.**

    Le profil produit par `profile` ne contient déjà que des agrégats — mais
    cette fonction ne s'en remet pas à cette promesse : elle **choisit** champ
    par champ ce qui part. Le jour où un profil transportera un échantillon de
    lignes (tentation réelle en phase 4), il ne franchira pas cette barrière
    sans qu'on ait modifié ce code exprès.
    """
    profil = state["profile"]
    return {
        "table": state["table"],
        "couche": state["layer"],
        "lot": state["batch_id"],
        "lignes_dans_le_lot": profil.get("row_count"),
        "colonnes_profilees": sorted(profil.get("columns", {})),
        "ecarts_constates": state["anomalies"],
        "incidents_similaires_passes": state["past_incidents"],
        "contrat_version": state["contract_version"],
    }


def diagnose(state: AgentState) -> dict:
    anomalies = state["anomalies"]

    # Le graphe ne route pas ici sans écart, mais un nœud ne doit jamais
    # supposer d'où il vient.
    if not anomalies:
        return {
            "diagnosis": None,
            "logs": [log_entry("diagnose", "aucun écart à diagnostiquer")],
        }

    try:
        diagnostic = diagnostiquer(construire_contexte(state))
    except Exception as exc:  # noqa: BLE001 — tout échec mène au même mode dégradé
        # On ne distingue pas les causes : réseau, quota, parsing, champ manquant
        # produisent la même conséquence. Le type de l'erreur est journalisé pour
        # pouvoir enquêter, mais il ne change pas le comportement.
        return {
            "diagnosis": None,
            "logs": [
                log_entry(
                    "diagnose",
                    "diagnostic indisponible — à traiter manuellement",
                    erreur=f"{type(exc).__name__}: {exc}"[:200],
                    anomalies=len(anomalies),
                )
            ],
        }

    return {
        "diagnosis": diagnostic.model_dump(),
        "logs": [
            log_entry(
                "diagnose",
                "diagnostic produit",
                anomalies=len(anomalies),
                modele=MODELE,
            )
        ],
    }
