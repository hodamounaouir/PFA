"""Proposer un contrat à partir d'un profil (phase 4.2.2).

Un **contrat** dit ce qui *devrait* être vrai d'une table : cette colonne est
unique, celle-ci n'est jamais nulle, celle-là ne prend que ces valeurs. C'est le
troisième pilier de la détection ([ADR 010](../../docs/adr/010-agent-generique.md),
décision 3), et il attrape ce que les deux autres ratent :

    l'historique du schéma  ->  « cette table a-t-elle changé de forme ? »
    la dérive statistique   ->  « aujourd'hui ressemble-t-il aux jours d'avant ? »
    le contrat              ->  « est-ce conforme à ce qu'on a décidé ? »

Une colonne à 30 % de nulls depuis toujours ne fait dériver aucune statistique —
rien ne bouge. Seul un contrat qui dit « jamais nulle » la signale.

## Ce module **propose**, il ne grave rien

Le document rendu porte `status: proposed`, et c'est le point le plus important
du fichier. Ce qu'on mesure est **descriptif** (« observé entre 0 et 13 664 ») ;
ce qu'un contrat affirme est **normatif** (« 13 664 est une vraie borne métier »).
Le passage de l'un à l'autre n'est pas un calcul, c'est une décision — et c'est
le moment où le métier entre dans le système (4.2.5).

## La découverte critique ce qu'elle trouve

Un générateur naïf enregistrerait ce qu'il observe. Sur `customer_city`, il
écrirait :

    accepted_values: [sao paulo, são paulo]

et graverait l'anomalie comme légitime : le cas d'école du projet serait perdu
avant d'avoir commencé. La détection de collisions tourne donc **pendant** la
proposition, pas après.

Et quand elle trouve quelque chose, elle **retire la clause** au lieu de
l'assortir d'un avertissement. La nuance décide de tout : un avertissement se
survole, une clause absente ne peut pas être approuvée par distraction.

## Trois refus de proposer, et ce qu'ils protègent

| Situation | Ce qui n'est pas proposé | Pourquoi |
|---|---|---|
| collision sémantique observée | `accepted_values` | graverait l'anomalie comme légitime |
| top-K tronqué (`coverage < 1`) | `accepted_values` | la liste est **incomplète** : le contrat rejetterait des valeurs parfaitement normales |
| colonne de texte libre | `accepted_values` | on n'énumère pas des commentaires clients ; nulls et longueurs, rien d'autre |

Le deuxième est le plus sournois. `top_values` rend les *K* valeurs les plus
fréquentes ; si elles ne couvrent que 60 % des lignes, les 40 % restants sont
des valeurs légitimes **absentes de la liste**. Un contrat construit là-dessus
crierait dès le lendemain, sur des données saines.

## Ce qui est proposé même quand c'est déjà violé

`unique: true` sur un identifiant portant des doublons, `no_semantic_collisions`
sur une colonne qui en porte. Ce n'est pas une contradiction : un contrat dit ce
qui **devrait** être vrai, et l'avertissement dit que ça ne l'est pas encore.
C'est précisément la question à poser à l'humain — « nettoie-t-on, ou
accepte-t-on ? » — et l'escamoter reviendrait à choisir à sa place.
"""

from typing import Optional

from agent.characterize import (
    CATEGORIEL,
    IDENTIFIANT,
    INDETERMINE,
    NUMERIQUE,
    TEMPOREL,
    TEXTE_LIBRE,
    grouper_collisions,
)

VERSION_INITIALE = 1

# Tant qu'un humain n'a pas tranché, aucune clause n'est normative.
PROPOSE = "proposed"
# Ce que l'humain a validé — le seul état qu'un run de surveillance applique.
APPROUVE = "approved"
STATUTS = (PROPOSE, APPROUVE)

# Les motifs d'avertissement. Nommés plutôt que rédigés : ils seront comptés,
# filtrés et affichés (phase 6), et une phrase libre ne se compte pas.
COLLISION = "semantic_collision"
DOUBLONS = "duplicates_observed"
PREUVE_PARTIELLE = "partial_evidence"
NOMBRES_ILLISIBLES = "unreadable_numbers"
AUCUNE_DONNEE = "no_data"


def _avertir(colonne: str, motif: str, detail: str) -> dict:
    return {"column": colonne, "kind": motif, "detail": detail}


def _jamais_nulle(stats: dict) -> bool:
    """Aucune valeur manquante observée sur la fenêtre de référence.

    Proposer `not_null` là-dessus est un **saut** : l'absence de nul observé ne
    prouve pas qu'il ne peut pas y en avoir. C'est assumé — c'est une
    *proposition*, que l'humain valide, et c'est elle qui attrapera l'irruption
    de nulls du J60 dès le premier jour au lieu d'attendre que la statistique
    s'en émeuve.
    """
    return not stats.get("null_count")


def _clauses_identifiant(nom, stats, row_count, avertissements):
    distinct = stats.get("distinct") or 0
    if distinct < row_count:
        avertissements.append(
            _avertir(
                nom,
                DOUBLONS,
                f"{row_count - distinct} doublon(s) déjà présents sur la fenêtre "
                f"de référence ({distinct} valeurs distinctes pour {row_count} lignes)",
            )
        )
    # Proposée quand même : c'est ce qui *devrait* être vrai, et l'écart est le
    # sujet de la conversation avec l'humain.
    return {"unique": True, "not_null": True}


def _clauses_categoriel(nom, stats, row_count, avertissements):
    clauses = {"no_semantic_collisions": True}
    if _jamais_nulle(stats):
        clauses["not_null"] = True

    top = stats.get("top")
    if top is None:
        avertissements.append(
            _avertir(nom, PREUVE_PARTIELLE, "aucune valeur relevée sur cette colonne")
        )
        return clauses

    valeurs = [entree["value"] for entree in top]
    grappes = grouper_collisions(valeurs)
    if grappes:
        detail = " ; ".join(
            f"{' / '.join(g['values'])} -> {g['normalized']!r}" for g in grappes
        )
        avertissements.append(
            _avertir(
                nom,
                COLLISION,
                f"{len(grappes)} grappe(s) de valeurs qui n'en font qu'une : {detail}",
            )
        )
        # Pas de `accepted_values` : les graver légitimerait la collision.
        return clauses

    couverture = stats.get("coverage")
    if couverture is None or couverture < 1.0:
        avertissements.append(
            _avertir(
                nom,
                PREUVE_PARTIELLE,
                f"les valeurs relevées ne couvrent que {couverture:.0%} des lignes"
                if couverture is not None
                else "couverture inconnue",
            )
        )
        # La liste est incomplète : la graver ferait rejeter des valeurs saines.
        return clauses

    clauses["accepted_values"] = sorted(valeurs)
    return clauses


def _clauses_numerique(nom, stats, row_count, avertissements):
    clauses = {}
    if _jamais_nulle(stats):
        clauses["not_null"] = True

    taux = stats.get("numeric_rate")
    if taux is not None and taux < 1.0:
        avertissements.append(
            _avertir(
                nom,
                NOMBRES_ILLISIBLES,
                f"{1 - taux:.0%} des valeurs renseignées ne se lisent pas comme "
                f"un nombre — dérive de format probable",
            )
        )

    # ⚠️ `numeric_min`/`numeric_max`, jamais `min`/`max` : en Bronze ces
    # derniers sont **lexicographiques** (`"8000" < "90"`). Une borne
    # lexicographique gravée dans un contrat ne veut rien dire.
    mini, maxi = stats.get("numeric_min"), stats.get("numeric_max")
    if mini is not None and maxi is not None:
        clauses["between"] = [mini, maxi]
    return clauses


def _clauses_temporel(nom, stats, row_count, avertissements):
    clauses = {}
    if _jamais_nulle(stats):
        clauses["not_null"] = True
    # La fraîcheur, les dates futures et les trous demandent des mesures que
    # 4.1.4 n'a pas encore livrées. Ne rien proposer vaut mieux que proposer une
    # clause qu'on ne saurait pas vérifier.
    return clauses


def _clauses_texte_libre(nom, stats, row_count, avertissements):
    # Nulls seulement. **Jamais** `accepted_values` : énumérer des commentaires
    # clients n'aurait aucun sens, et les faire figurer dans un contrat
    # versionné dans git en ferait sortir la donnée du système observé.
    return {"not_null": True} if _jamais_nulle(stats) else {}


def _clauses_indetermine(nom, stats, row_count, avertissements):
    avertissements.append(
        _avertir(
            nom,
            AUCUNE_DONNEE,
            "colonne vide sur la fenêtre de référence — aucun contrôle proposé",
        )
    )
    return {}


CLAUSES_PAR_ROLE = {
    IDENTIFIANT: _clauses_identifiant,
    CATEGORIEL: _clauses_categoriel,
    NUMERIQUE: _clauses_numerique,
    TEMPOREL: _clauses_temporel,
    TEXTE_LIBRE: _clauses_texte_libre,
    INDETERMINE: _clauses_indetermine,
}


def proposer(fiche: dict) -> Optional[dict]:
    """Un contrat proposé, à partir d'une fiche de `profile_table`.

    Rend `None` si la fiche est absente — une table qui n'existe pas n'a pas de
    contrat à proposer, et c'est la famille *inventaire* de `detect` qui dira
    pourquoi.

    Le document porte `status: "proposed"` : **aucune clause n'est normative**
    tant qu'un humain n'a pas tranché (4.2.5). `warnings` porte ce que la
    découverte a critiqué — c'est la partie qu'il faut lire en premier.
    """
    if not fiche:
        return None

    row_count = fiche.get("row_count") or 0
    avertissements: list[dict] = []
    colonnes = {}

    for nom, stats in (fiche.get("columns") or {}).items():
        role = stats.get("role") or INDETERMINE
        construire = CLAUSES_PAR_ROLE.get(role, _clauses_indetermine)
        clauses = construire(nom, stats, row_count, avertissements)
        colonnes[nom] = {"role": role, **clauses}

    return {
        "table": fiche.get("table"),
        "version": VERSION_INITIALE,
        "status": PROPOSE,
        # De quoi le contrat a été tiré : sans ça, personne ne peut refaire le
        # raisonnement six semaines plus tard, ni savoir si la fenêtre était
        # propre au moment où les clauses ont été écrites.
        "source": {"batch_id": fiche.get("batch_id"), "row_count": row_count},
        "columns": colonnes,
        "warnings": avertissements,
    }
