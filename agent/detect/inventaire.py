"""Famille *inventaire* — le registre ne décrit plus la réalité (phase 4.3).

La seule famille qui s'exerce **avant** de profiler quoi que ce soit, et la
seule qui puisse constater qu'il n'y a **rien** à profiler.

Sans elle, une table déclarée mais disparue ferait lever le connecteur et le run
planterait : personne ne saurait *pourquoi*, et l'anomalie la plus grave qui
puisse arriver serait masquée par ce qui ressemblerait à un bug. L'agent doit la
**constater**, pas trébucher dessus. C'est la même symétrie que dans le
connecteur (4.0) : ce qui est *observé* se constate, ce qui est *déclaré* échoue
bruyamment.

## Trois écarts

    table_absente        déclarée au registre, introuvable dans la base
    table_non_declaree   présente dans la base, surveillée par personne
    renommage_probable   la mienne a disparu ET une inconnue porte son schéma

Le troisième n'est qu'une **conjonction de faits** : « A absente, B nouvelle,
mêmes colonnes ». La famille ne dit pas « c'est un renommage » — c'est
`diagnose` qui le formule et l'humain qui tranche. Répartition constante dans
tout le projet : le code constate, le modèle suppose, l'humain décide.

## Ce que l'humain répond, et pourquoi il n'y a pas de 4ᵉ issue

Décision 14 de l'[ADR 010](../../docs/adr/010-agent-generique.md) : un renommage
recouvre deux situations que la machine ne peut pas distinguer.

    vrai renommage métier  → `rejected`  : l'humain corrige `datasets/*.yaml` en git
    renommage accidentel   → `approved`  : `apply` restaure le nom d'origine

L'agent n'écrit **jamais** dans le registre : celui-ci déclare un *périmètre de
surveillance*, et un agent qui réécrit son propre périmètre décide de ce qu'il
surveille. C'est l'autorité que le projet lui refuse, au même titre que
l'écriture sans approbation.
"""

from agent.detect import COMPLETUDE, COHERENCE, INVENTAIRE, ecart


def detecter(state: dict) -> list[dict]:
    """Ce que le registre déclare, confronté à ce que la base contient."""
    inventaire = state.get("inventory") or {}
    presentes = inventaire.get("present")
    # `None` = l'inventaire n'a pas été relevé (aucun connecteur, ou un run
    # monté à la main). Se taire, plutôt que de déduire d'une liste vide que
    # toutes les tables ont disparu — le faux positif le plus spectaculaire
    # qu'on puisse produire.
    if presentes is None:
        return []

    table = state["table"]
    presentes = set(presentes)
    declarees = set(inventaire.get("declared") or [])
    ecarts = []

    if table not in presentes:
        ecarts.append(
            ecart(
                INVENTAIRE,
                table,
                type="table_absente",
                dama=COMPLETUDE,
                observe=None,
                reference=table,
                tables_presentes=sorted(presentes),
            )
        )
        ecarts += _renommage(state, table, presentes, declarees, inventaire)

    for inconnue in sorted(presentes - declarees):
        ecarts.append(
            ecart(
                INVENTAIRE,
                table,
                type="table_non_declaree",
                dama=COHERENCE,
                observe=inconnue,
                reference=sorted(declarees),
            )
        )

    return ecarts


def _renommage(state, table, presentes, declarees, inventaire) -> list[dict]:
    """« A absente, B nouvelle, mêmes colonnes » — un fait, pas une conclusion."""
    connues = _colonnes_connues(state)
    if not connues:
        # Sans schéma connu, on ne peut rien rapprocher. L'absence reste
        # signalée par l'appelant : c'est elle qui compte, l'hypothèse n'est
        # qu'un service rendu au diagnostic.
        return []

    schemas = inventaire.get("schemas") or {}
    candidates = [
        nom
        for nom in sorted(presentes - declarees)
        if set(schemas.get(nom) or []) == connues
    ]
    return [
        ecart(
            INVENTAIRE,
            table,
            type="renommage_probable",
            dama=COHERENCE,
            observe=candidate,
            reference=table,
            colonnes_communes=sorted(connues),
        )
        for candidate in candidates
    ]


def _colonnes_connues(state: dict) -> set:
    """Le schéma de la table disparue : l'historique, sinon le contrat.

    Même ordre de préférence que la famille *schéma*, et pour la même raison :
    l'historique dit ce qui a été **observé** hier, le contrat ce qu'un humain a
    **signé** il y a peut-être des semaines.
    """
    historique = state.get("schema_history") or []
    if historique:
        return {c["name"] for c in historique if "name" in c}
    return set((state.get("contract") or {}).get("columns") or {})
