"""Famille *contrat* — le lot viole ce qu'un humain a signé (phase 4.3).

Le contrat est le **3ᵉ pilier de détection**, à côté du z-score et des tests
dbt. Sa force sur les deux autres : il attrape une anomalie **dès le premier
lot**, sans historique à constituer. Sa faiblesse : il ne voit que ce qui a été
écrit, d'où les quatre autres familles.

Ce qui est vérifié ici, clause par clause :

    not_null         → le lot porte-t-il des valeurs manquantes ?
    unique           → porte-t-il des doublons ?
    between          → une valeur sort-elle des bornes de référence ?
    accepted_values  → une valeur hors de la liste close ?

## Ce qui n'est **pas** vérifié ici : `no_semantic_collisions`

La clause existe dans les contrats, mais c'est la famille *sémantique* qui la
constate — et elle le fait sur **toute** colonne catégorielle, contrat ou pas.
Deux raisons de ne pas la dupliquer :

1. un même fait produirait **deux** écarts, donc deux propositions à trancher
   pour une seule anomalie, et un taux d'approbation faussé au benchmark ;
2. surtout, São Paulo doit être vu même sur une table **sans contrat signé**.
   Faire dépendre la détection du fil rouge d'une signature humaine, ce serait
   la rendre optionnelle.

## Seul un contrat **validé** arrive ici

`charger()` ne rend jamais un contrat `proposed` (garantie de 4.2.4). Cette
famille ne voit donc que des clauses signées : elle ne peut pas appliquer ce
qu'un humain n'a pas relu. Sans contrat, elle ne rend rien — et ce silence est
correct, ce n'est pas un « tout va bien ».
"""

from agent.detect import COMPLETUDE, CONTRAT, EXACTITUDE, UNICITE, VALIDITE, ecart


def detecter(state: dict) -> list[dict]:
    """Les clauses du contrat que le lot du jour ne respecte pas."""
    contrat = state.get("contract") or {}
    profil = state.get("profile") or {}
    clauses_par_colonne = contrat.get("columns") or {}
    if not clauses_par_colonne or not profil:
        return []

    table = state["table"]
    lignes = profil.get("row_count") or 0
    ecarts = []

    for colonne, clauses in clauses_par_colonne.items():
        stats = (profil.get("columns") or {}).get(colonne)
        # Colonne du contrat absente du lot : c'est une dérive de **schéma**,
        # pas une violation de clause. La signaler ici la ferait compter deux
        # fois — et sous une dimension DAMA qui n'est pas la sienne.
        if stats is None:
            continue

        ecarts += _verifier(table, colonne, clauses, stats, lignes)
    return ecarts


def _verifier(table, colonne, clauses, stats, lignes) -> list[dict]:
    trouves = []

    manquantes = stats.get("null_count") or 0
    if clauses.get("not_null") and manquantes:
        trouves.append(
            ecart(
                CONTRAT,
                table,
                type="nulls_interdits",
                dama=COMPLETUDE,
                colonne=colonne,
                observe=manquantes,
                reference=0,
                # Le **taux** et non le décompte : un lot deux fois plus gros
                # porterait deux fois plus de nulls sans que l'anomalie ait
                # changé d'échelle, et la signature basculerait pour rien.
                ampleur=stats.get("null_rate"),
                clause="not_null",
                taux=stats.get("null_rate"),
            )
        )

    # Unicité : sur le lot, `distinct` compte les valeurs **non nulles**, d'où
    # la soustraction. Sans elle, une colonne unique portant des nulls
    # paraîtrait toujours en doublon — un faux positif permanent, exactement ce
    # qui apprend à ignorer un agent.
    distinctes = stats.get("distinct")
    if clauses.get("unique") and distinctes is not None and lignes:
        attendues = lignes - manquantes
        if distinctes < attendues:
            trouves.append(
                ecart(
                    CONTRAT,
                    table,
                    type="doublons",
                    dama=UNICITE,
                    colonne=colonne,
                    observe=distinctes,
                    reference=attendues,
                    ampleur=(attendues - distinctes) / attendues if attendues else None,
                    clause="unique",
                    doublons=attendues - distinctes,
                )
            )

    bornes = clauses.get("between")
    if bornes:
        trouves += _hors_bornes(table, colonne, bornes, stats)

    admises = clauses.get("accepted_values")
    if admises:
        trouves += _hors_liste(table, colonne, admises, stats)

    return trouves


def _hors_bornes(table, colonne, bornes, stats) -> list[dict]:
    """Les bornes du contrat, comparées aux bornes **numériques** du lot.

    ⚠️ `numeric_min`/`numeric_max`, jamais `min`/`max` : sur Bronze ces derniers
    sont lexicographiques (`"8000" < "90"`), et les comparer à des bornes
    numériques rendrait un verdict différent selon la couche — c'est le piège
    de 4.1.5, et le contrat grave d'ailleurs déjà les bonnes.
    """
    bas, haut = bornes
    observes = (stats.get("numeric_min"), stats.get("numeric_max"))
    if observes == (None, None):
        return []

    sorties = [v for v in observes if v is not None and (v < bas or v > haut)]
    if not sorties:
        return []

    return [
        ecart(
            CONTRAT,
            table,
            type="hors_bornes",
            dama=EXACTITUDE,
            colonne=colonne,
            observe=list(observes),
            reference=list(bornes),
            # De combien on sort, relativement à la largeur admise : 8000 dans
            # [1–100] et 8 dans [1–2] ne sont pas la même anomalie, alors que
            # leurs valeurs brutes ne le disent pas.
            ampleur=max(abs(v - _borne_la_plus_proche(v, bornes)) for v in sorties)
            / (abs(haut - bas) or 1),
            clause="between",
        )
    ]


def _hors_liste(table, colonne, admises, stats) -> list[dict]:
    """Les valeurs observées qui n'appartiennent pas à la liste close.

    On ne regarde que le top-K : une valeur illégitime rare peut donc échapper.
    C'est assumé — mais l'inverse ne l'est pas, et c'est ce qui compte : **toute
    valeur rapportée ici a réellement été vue**. Un écart faux, l'humain
    apprendrait à s'en méfier ; un écart manqué, il ne le saura jamais.
    """
    valeurs = stats.get("top") or []
    if not valeurs:
        return []

    connues = set(admises)
    intruses = [e["value"] for e in valeurs if e.get("value") not in connues]
    if not intruses:
        return []

    return [
        ecart(
            CONTRAT,
            table,
            type="valeur_non_admise",
            dama=VALIDITE,
            colonne=colonne,
            observe=intruses,
            reference=sorted(connues),
            ampleur=len(intruses),
            clause="accepted_values",
            coverage=stats.get("coverage"),
        )
    ]


def _borne_la_plus_proche(valeur: float, bornes) -> float:
    """De quelle borne la valeur s'est écartée — celle qu'elle a franchie.

    Sans ça, l'ampleur d'un dépassement se mesurerait contre une borne
    arbitraire : une valeur trop **basse** paraîtrait d'autant plus grave que la
    borne haute est éloignée, ce qui n'a aucun sens.
    """
    bas, haut = bornes
    return bas if valeur < bas else haut
