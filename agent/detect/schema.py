"""Famille *schéma* — les colonnes ne sont plus les mêmes (phase 4.3).

Compare les colonnes du lot du jour à celles du dernier schéma connu. C'est la
famille qui attrape `schema_drift_j45` — `payment_value` renommé en `amount` —
et elle le fait **sans seuil** : une colonne est là ou elle n'y est pas.

## Deux références, et le choix se justifie

`_SCHEMA_HISTORY` n'est écrite que par l'ingestion (phase 2.1) : elle ne couvre
donc que **Bronze**. Silver et Gold n'y figurent pas. Plutôt que de se taire sur
les deux tiers du pipeline, la famille retombe sur les colonnes du **contrat**,
qui existent pour toutes les couches.

L'ordre est important : l'historique d'abord, le contrat ensuite. L'historique
dit ce qui a été *observé hier* ; le contrat dit ce qu'un humain a *signé*, il y
a peut-être des semaines. Sur Bronze, une colonne ajoutée avant-hier et validée
depuis figure dans l'historique mais pas forcément dans un contrat plus ancien —
comparer au contrat la signalerait comme nouvelle à chaque run.

## Un renommage n'est pas détecté ici

Une colonne disparue **et** une colonne apparue le même jour, c'est très
probablement un renommage. Cette famille n'en dit rien : elle rapporte les deux
faits séparément. Supposer est le travail de `diagnose` (le LLM), trancher celui
de l'humain. Le partage est le même que pour les tables renommées, en 4.3
*inventaire* : **le code constate, le modèle suppose, l'humain décide.**
"""

from agent.detect import COHERENCE, SCHEMA, ecart


def detecter(state: dict) -> list[dict]:
    """Les colonnes apparues et disparues depuis la dernière observation."""
    profil = state.get("profile") or {}
    if not profil:
        return []

    aujourd_hui = set(profil.get("columns") or {})
    connues, origine = _reference(state)
    # Aucune référence : première observation de la table. Tout serait
    # « nouveau », ce qui n'apprendrait rien — on se tait plutôt que d'inonder
    # le premier run de faux écarts.
    if not connues:
        return []

    table = state["table"]
    ecarts = []

    for disparue in sorted(connues - aujourd_hui):
        ecarts.append(
            ecart(
                SCHEMA,
                table,
                type="colonne_disparue",
                dama=COHERENCE,
                colonne=disparue,
                observe=None,
                reference=origine,
                colonnes_connues=sorted(connues),
            )
        )

    for nouvelle in sorted(aujourd_hui - connues):
        ecarts.append(
            ecart(
                SCHEMA,
                table,
                type="colonne_nouvelle",
                dama=COHERENCE,
                colonne=nouvelle,
                observe=nouvelle,
                reference=origine,
                colonnes_connues=sorted(connues),
            )
        )

    return ecarts


def _reference(state: dict) -> tuple[set, str]:
    """Les colonnes connues, et d'où elles viennent.

    Rendre la provenance et pas seulement les noms : `diagnose` et l'humain
    n'interprètent pas de la même façon « absente du schéma d'hier » et
    « absente du contrat signé il y a un mois ».
    """
    historique = state.get("schema_history") or []
    if historique:
        return {c["name"] for c in historique if "name" in c}, "_SCHEMA_HISTORY"

    clauses = (state.get("contract") or {}).get("columns") or {}
    if clauses:
        return set(clauses), "contrat"

    return set(), "aucune"
