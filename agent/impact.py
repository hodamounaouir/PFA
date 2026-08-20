"""L'impact d'un écart — la ligne dont dépend la décision (phase 5.1).

> « 1 ligne sur 351 » semble négligeable jusqu'à voir « panier moyen 42,30 →
> 65,00 (+53,7 %) ».

Sans impact chiffré, l'humain ne décide pas : il approuve. Et un HITL où l'on
approuve sans juger n'est pas un HITL, c'est une signature. C'est la faiblesse
que `DESIGN.md` §5.3 anticipe (« et si l'humain approuve sans lire ? ») et le
champ le plus important de toute la proposition.

## Aucune requête, et ce n'est pas de la paresse

L'impact se calcule **sur ce que `profile` a déjà mesuré**. Un nœud qui
interrogerait la base au moment de proposer comparerait un lot mesuré tout à
l'heure à une base lue maintenant — l'écart affiché ne correspondrait alors ni à
ce qui a été détecté, ni à ce que l'humain verrait s'il regardait lui-même.

C'est la même règle que pour `detect` (4.3) et la fraîcheur (4.1.4), et elle a
ici une conséquence directe : **ce qui n'est pas mesurable est dit comme tel.**

## Trois degrés de certitude, jamais un chiffre inventé

    exact     on sait combien de lignes : `null_count`, doublons, top-K
    minimum   on sait qu'il y en a, pas combien : une borne dépassée ne dit pas
              par combien de lignes
    inconnu   la table entière est concernée, ou rien ne permet de compter

Annoncer « 1 ligne » quand on veut dire « au moins 1 » ferait refuser une
anomalie majeure sur la foi d'un chiffre qu'on a inventé. La nuance coûte un
champ ; l'omettre coûterait une mauvaise décision.

## Ce qu'on ne somme pas

Les lignes touchées par plusieurs écarts **ne s'additionnent pas** : la même
ligne peut porter un null et un doublon. On rapporte donc le maximum comme
en-tête, jamais un total — un total serait supérieur au lot lui-même dès que
deux écarts se recouvrent, et un impact de « 420 lignes sur 351 » détruirait la
confiance dans tout le reste de la proposition.

## L'aval attend la phase 7

L'effet sur les agrégats Gold — le « panier moyen +53,7 % » de l'exemple —
demande de remonter le lineage dbt. C'est l'objet de `lineage_impact` (7.1), où
PROGRESS le place explicitement. En attendant, **le champ existe et dit qu'il
n'est pas calculé** : un impact qui omettrait silencieusement l'aval laisserait
approuver une correction qui déplace un indicateur de moitié.
"""

from typing import Optional

EXACT = "exact"
MINIMUM = "minimum"
INCONNU = "inconnu"

AVAL_NON_CALCULE = (
    "non calculé — l'effet sur les agrégats aval demande le lineage dbt (phase 7.1)"
)


def _lignes(ecart: dict, profil: dict) -> tuple[Optional[int], str]:
    """Combien de lignes cet écart touche, et avec quelle certitude."""
    details = ecart.get("details") or {}
    colonne = ecart.get("colonne")
    stats = ((profil.get("columns") or {}).get(colonne)) or {}
    type_ = ecart.get("type")

    if type_ == "nulls_interdits":
        return stats.get("null_count") or ecart.get("observe"), EXACT
    if type_ == "doublons":
        return details.get("doublons"), EXACT
    if type_ == "collision_semantique":
        return details.get("lignes_concernees"), EXACT
    if type_ == "test_dbt_echoue":
        # dbt compte exactement les lignes fautives : c'est même tout ce qu'il
        # rend. On ne peut pas faire mieux, et on n'a pas besoin de mieux.
        observe = ecart.get("observe")
        return (observe, EXACT) if isinstance(observe, int) else (None, INCONNU)
    if type_ == "valeur_non_admise":
        return _lignes_des_valeurs(ecart.get("observe"), stats), EXACT
    if type_ == "hors_bornes":
        # `numeric_min`/`numeric_max` disent qu'une valeur sort, jamais combien.
        # « au moins 1 » est exact ; « 1 » serait faux.
        return 1, MINIMUM
    if type_ in ("table_absente", "colonne_disparue"):
        return profil.get("row_count"), INCONNU
    if type_ in ("derive_statistique", "rupture_de_constante"):
        # Une métrique qui dérive ne désigne pas des lignes : c'est le lot qui
        # a changé de forme. L'impact se lit dans la variation, pas dans un
        # décompte — voir `_variation`.
        return None, INCONNU
    return None, INCONNU


def _lignes_des_valeurs(valeurs, stats: dict) -> Optional[int]:
    """Les lignes portant ces valeurs, d'après le top-K déjà mesuré."""
    if not isinstance(valeurs, (list, tuple)):
        return None
    cherchees = set(valeurs)
    total = sum(
        entree.get("count", 0)
        for entree in stats.get("top") or []
        if entree.get("value") in cherchees
    )
    return total or None


def _variation(ecart: dict) -> Optional[dict]:
    """« 351 → 42 lignes (−88 %) » — l'impact d'une dérive, qui ne compte pas
    des lignes mais un déplacement.

    C'est la forme la plus lisible pour un humain pressé : deux nombres et un
    pourcentage disent en une ligne ce qu'un score `z` de 9,1 ne dit à personne.
    Le `z` reste dans l'écart pour qui veut la mesure ; ici on traduit.
    """
    avant, apres = ecart.get("reference"), ecart.get("observe")
    if not _nombre(avant) or not _nombre(apres):
        return None
    variation = {"avant": avant, "apres": apres, "delta": apres - avant}
    if avant:
        variation["variation_relative"] = (apres - avant) / abs(avant)
    return variation


def _nombre(valeur) -> bool:
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


def pour_un_ecart(ecart: dict, profil: dict) -> dict:
    """L'impact d'un seul écart."""
    lignes, precision = _lignes(ecart, profil)
    total = profil.get("row_count")

    detail = {
        "table": ecart.get("table"),
        "colonne": ecart.get("colonne"),
        "type": ecart.get("type"),
        "dama": ecart.get("dama"),
        "lignes_concernees": lignes,
        "precision": precision,
        "part_du_lot": (lignes / total) if (lignes and total) else None,
    }
    variation = _variation(ecart)
    if variation:
        detail["variation"] = variation
    return detail


def estimer(anomalies: list, profil: dict) -> dict:
    """L'impact complet d'une proposition — ce que l'humain lit en premier.

    L'en-tête retient l'écart le **plus étendu**, pas le premier ni le plus
    récent : c'est celui qui décide si la correction vaut la peine d'être
    approuvée. Les autres restent listés en dessous.
    """
    anomalies = anomalies or []
    profil = profil or {}
    total = profil.get("row_count")

    details = [pour_un_ecart(e, profil) for e in anomalies]
    # ⚠️ Le **maximum**, jamais la somme : la même ligne peut porter un null et
    # un doublon, et « 420 lignes sur 351 » détruirait la confiance dans le
    # reste de la proposition.
    pires = [d for d in details if d["lignes_concernees"]]
    tete = max(pires, key=lambda d: d["lignes_concernees"]) if pires else None

    return {
        "lignes_du_lot": total,
        "ecart_le_plus_etendu": tete,
        "resume": _resume(tete, details, total),
        "par_ecart": details,
        "aval": AVAL_NON_CALCULE,
    }


def _resume(tete: Optional[dict], details: list, total) -> str:
    """Une phrase, en français, avec des nombres — jamais un adjectif.

    « impact modéré » ne veut rien dire et ne se conteste pas. « 51 lignes sur
    351 (14,5 %) » se vérifie, se discute, et se compare au run d'hier.
    """
    if not details:
        return "aucun écart soumis"

    if tete is None:
        variations = [d for d in details if d.get("variation")]
        if variations:
            v = variations[0]["variation"]
            relative = v.get("variation_relative")
            pourcent = f" ({relative:+.1%})" if relative is not None else ""
            return (
                f"{len(details)} écart(s) — {variations[0]['type']} : "
                f"{_court(v['avant'])} → {_court(v['apres'])}{pourcent}"
            )
        return f"{len(details)} écart(s) — nombre de lignes non déterminable"

    lignes = tete["lignes_concernees"]
    prefixe = "au moins " if tete["precision"] == MINIMUM else ""
    part = f" ({tete['part_du_lot']:.1%})" if tete["part_du_lot"] else ""
    sur = f" sur {total}" if total else ""
    colonne = f" · {tete['colonne']}" if tete["colonne"] else ""
    autres = f" · +{len(details) - 1} autre(s) écart(s)" if len(details) > 1 else ""
    return f"{prefixe}{lignes} ligne(s){sur}{part}{colonne} — {tete['dama']}{autres}"


def _court(valeur) -> str:
    """Un nombre lisible : `42` plutôt que `42.0`, `0.301` gardé tel quel."""
    if isinstance(valeur, float) and valeur == int(valeur):
        return str(int(valeur))
    return str(valeur)
