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

from agent.llm import MODELE, diagnostiquer, repondre
from agent.corrections import controler as controler_p6
from agent.corrections import correction_par_defaut
from agent.sql_guard import controler
from agent.tools.read_past_incidents import incidents_similaires, resumer
from agent.state import AgentState, echange, log_entry


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
        # ⚠️ **Frontière R2, et elle a changé de nature en 4.4.** `past_incidents`
        # porte le JSON complet des anomalies passées — donc potentiellement des
        # valeurs de données. On ne le transmet pas : `resumer()` énumère champ
        # par champ ce qui sort, exactement comme cette fonction le fait pour le
        # profil. Et `incidents_similaires` restreint à ce qui partage une
        # signature avec les écarts du jour : au-delà, le contexte grossit sans
        # que le diagnostic s'améliore.
        "incidents_similaires_passes": _memoire(state),
        "contrat_version": state["contract_version"],
        # le diagnostic déjà rendu, quand l'humain revient poser une question
        "diagnostic_deja_rendu": state["diagnosis"],
    }


def _memoire(state: AgentState) -> list:
    """Les incidents passés que le modèle a le droit de voir, et eux seuls."""
    return resumer(incidents_similaires(state["past_incidents"], state["anomalies"]))


def question_en_attente(state: AgentState) -> str | None:
    """La dernière réplique, si c'est l'humain qui a parlé et attend une réponse.

    C'est ce qui distingue les deux modes du nœud : premier passage (personne n'a
    encore rien dit → on diagnostique) ou retour depuis `propose` (l'humain a posé
    une question → on y répond). Le nœud ne devine pas d'où il vient, il regarde
    l'état.
    """
    conversation = state["conversation"]
    if conversation and conversation[-1]["role"] == "humain":
        return conversation[-1]["message"]
    return None


def _repondre_a_la_question(state: AgentState, question: str) -> dict:
    """Mode « dialogue » : l'humain veut comprendre avant de trancher.

    Le diagnostic **n'est pas retouché**. Une réponse à une question éclaire, elle
    ne remplace pas le diagnostic initial — et surtout, si le LLM réécrivait son
    diagnostic à chaque échange, la proposition changerait sous les yeux de
    l'humain pendant qu'il réfléchit. La révision d'un diagnostic sur objection
    est une autre fonctionnalité, à traiter en phase 5 si elle s'avère utile.
    """
    try:
        reponse = repondre(
            construire_contexte(state), state["conversation"][:-1], question
        )
    except Exception as exc:  # noqa: BLE001 — même mode dégradé que le diagnostic
        reponse = (
            "Je ne peux pas répondre pour le moment (le modèle est indisponible). "
            "Les écarts constatés restent affichés : ils ne dépendent pas du modèle."
        )
        return {
            "conversation": [echange("agent", reponse)],
            "logs": [
                log_entry(
                    "diagnose",
                    "réponse indisponible — l'écart reste consultable",
                    erreur=f"{type(exc).__name__}: {exc}"[:200],
                )
            ],
        }

    return {
        "conversation": [echange("agent", reponse)],
        "logs": [
            log_entry(
                "diagnose",
                "réponse à une question de l'humain",
                echanges=len(state["conversation"]) + 1,
                modele=MODELE,
            )
        ],
    }


def diagnose(state: AgentState) -> dict:
    # Deux modes. L'humain qui revient poser une question passe par ici aussi :
    # c'est ce qui garde **un seul nœud** en contact avec le LLM (règle R1).
    question = question_en_attente(state)
    if question is not None:
        return _repondre_a_la_question(state, question)

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

    rendu = diagnostic.model_dump()

    # Garde-fou SQL (4.4) — **première ligne de défense, pas la dernière.** On
    # constate, on attache, on laisse passer : c'est `apply` qui refusera
    # d'exécuter (phase 5). Le but est que l'humain voie le problème **avant**
    # de décider, pas qu'il découvre après coup pourquoi sa décision est
    # inapplicable. Le diagnostic est conservé tel quel — l'amputer priverait le
    # lecteur du raisonnement qui l'a produit, qui reste utile même si le SQL
    # proposé est mauvais.
    alertes = controler(rendu.get("proposed_fix"), state["table"])
    if alertes:
        rendu["alertes_sql"] = alertes

    # Garde-fou P6 (5.2), montré **avant** la décision. `apply` refusera de
    # toute façon — mais découvrir le refus après avoir approuvé serait vexant
    # et surtout inutile : l'humain doit pouvoir réécrire la correction tout de
    # suite, puisque son autorité, elle, n'est pas soumise à P6.
    inventions = controler_p6(
        rendu.get("proposed_fix"), state["anomalies"], state["profile"]
    )
    if inventions:
        rendu["alertes_p6"] = inventions
        # Et on lui montre le geste sûr, plutôt que de le laisser sans issue.
        rendu["correction_par_defaut"] = correction_par_defaut(anomalies[0])

    journal = log_entry(
        "diagnose",
        "diagnostic produit" + (" (correction inacceptable)" if inventions else ""),
        anomalies=len(anomalies),
        modele=MODELE,
        incidents_cites=len(_memoire(state)),
    )
    if alertes:
        journal["alertes_sql"] = alertes
    if inventions:
        journal["alertes_p6"] = inventions

    return {"diagnosis": rendu, "logs": [journal]}
