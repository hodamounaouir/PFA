"""Amender un contrat : la donnée est juste, c'est la règle qui a vieilli (5.3).

C'est le miroir d'`apply`, et le mécanisme **anti-obsolescence** du contrat :

    apply  →  la donnée est fausse  →  écrit dans les DONNÉES
    amend  →  la règle est fausse   →  écrit dans le CONTRAT

Sans cette branche, un contrat figé finit par crier à chaque évolution normale du
métier — un nouveau moyen de paiement, une borne qui bouge, une ville qui
apparaît. L'équipe s'habitue à ignorer les alertes, et l'agent meurt en silence.

## Relâcher, et seulement ce qui a été violé

Chaque écart de la famille *contrat* désigne **une clause précise**. On ne
relâche que celle-là :

    nulls_interdits       retire `not_null`
    doublons              retire `unique`
    hors_bornes           élargit `between` jusqu'à englober ce qui a été observé
    valeur_non_admise     ajoute les valeurs vues à `accepted_values`
    collision_semantique  retire `no_semantic_collisions`

Élargir plutôt que retirer, quand c'est possible : une borne étendue continue de
protéger contre la valeur suivante, une clause supprimée ne protège plus de
rien. *Un amendement doit desserrer la règle, pas l'abandonner.*

## Le diff est le livrable, autant que le fichier

Ce qui a changé est journalisé clause par clause, avec l'avant et l'après. Un
contrat qui évolue sans trace devient au bout de six mois un ensemble de règles
que plus personne ne sait justifier — et qu'on n'ose donc plus modifier.
"""

import copy

from agent.contracts.proposer import APPROUVE


def _numerique(valeur) -> bool:
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


def relacher(contrat: dict, anomalies: list) -> list[dict]:
    """Desserre les clauses violées **en place**. Rend le diff, clause par clause.

    Modifie le contrat reçu : l'appelant lui a déjà donné une copie et un
    numéro de version. Rendre un nouveau dictionnaire obligerait à recopier ce
    qui n'a pas changé, et c'est justement ce qu'un diff sert à éviter.
    """
    colonnes = contrat.get("columns") or {}
    diffs = []

    for anomalie in anomalies or []:
        colonne = anomalie.get("colonne")
        clauses = colonnes.get(colonne)
        if clauses is None:
            continue

        diff = _relacher_une(clauses, anomalie)
        if diff:
            diffs.append({"colonne": colonne, **diff})

    return diffs


def _relacher_une(clauses: dict, anomalie: dict) -> dict:
    type_ = anomalie.get("type")

    if type_ == "nulls_interdits" and clauses.get("not_null"):
        clauses.pop("not_null")
        return {"clause": "not_null", "avant": True, "apres": None}

    if type_ == "doublons" and clauses.get("unique"):
        clauses.pop("unique")
        return {"clause": "unique", "avant": True, "apres": None}

    if type_ == "collision_semantique" and clauses.get("no_semantic_collisions"):
        clauses.pop("no_semantic_collisions")
        return {"clause": "no_semantic_collisions", "avant": True, "apres": None}

    if type_ == "hors_bornes" and clauses.get("between"):
        avant = list(clauses["between"])
        observees = [v for v in (anomalie.get("observe") or []) if _numerique(v)]
        if not observees:
            return {}
        # ⭐ On **élargit**, on ne supprime pas : la borne étendue continue de
        # protéger contre la valeur suivante. Retirer la clause reviendrait à
        # renoncer à surveiller la colonne pour une valeur qu'on a acceptée une
        # fois.
        clauses["between"] = [
            min(avant[0], *observees),
            max(avant[1], *observees),
        ]
        return {"clause": "between", "avant": avant, "apres": clauses["between"]}

    if type_ == "valeur_non_admise" and clauses.get("accepted_values") is not None:
        avant = list(clauses["accepted_values"])
        nouvelles = [v for v in (anomalie.get("observe") or []) if v not in avant]
        if not nouvelles:
            return {}
        clauses["accepted_values"] = sorted(avant + nouvelles)
        return {
            "clause": "accepted_values",
            "avant": avant,
            "apres": clauses["accepted_values"],
            "ajoutees": nouvelles,
        }

    return {}


def version_suivante(contrat: dict, decide_par) -> dict:
    """Une copie du contrat, en version N+1, signée par qui a décidé.

    **Signée d'emblée** : contrairement à la découverte, qui propose et attend,
    l'amendement *est* la décision humaine — elle vient d'être prise dans
    `propose`. Laisser la v2 en `proposed` obligerait à re-signer ce qu'on vient
    de trancher, et l'ancienne règle continuerait de crier entre-temps.
    """
    nouveau = copy.deepcopy(contrat)
    nouveau["version"] = int(contrat.get("version") or 1) + 1
    nouveau["status"] = APPROUVE
    nouveau["approved_by"] = decide_par
    # Les avertissements de la découverte portaient sur la v1 : les recopier
    # ferait croire que la nouvelle version les a hérités.
    nouveau["warnings"] = []
    return nouveau
