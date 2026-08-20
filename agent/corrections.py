"""Ce qu'une correction a le droit de faire (phase 5.2) — l'invariant P6.

Face à `8000` dans une colonne à [1–100], l'agent **ne peut pas savoir** s'il
s'agit de 80,00 € saisis en centimes, d'une faute de frappe, ou d'une vraie
grosse commande. Proposer « remplacer 8000 par 80 », c'est **fabriquer de la
donnée qui n'a jamais existé** — et une donnée fabriquée est pire qu'une donnée
fausse : la fausse se voit, la fabriquée est cohérente.

## Une liste blanche de gestes, pas une liste noire d'interdits

Quatre corrections sont autorisées, et rien d'autre :

    ISOLER       marquer les lignes (quarantaine) — la donnée reste intacte
    NULLIFIER    `SET <colonne> = NULL` — on efface, on n'invente pas
    NORMALISER   `SET <colonne> = <une valeur DÉJÀ PRÉSENTE dans la colonne>`
    EXCLURE      ne touche pas Bronze — agit sur l'agrégat en aval

La leçon de 4.1.6 s'applique : une liste noire ne protège que de ce qu'on a
pensé à y mettre. Ici la charge est inversée — ce qui ne ressemble à aucun de
ces gestes est refusé, y compris ce qu'on n'a pas imaginé.

## ⭐ `NORMALISER` est ce qui sauve le fil rouge

Sans lui, la règle « seul `NULL` peut être écrit » interdirait la correction que
le projet existe pour montrer : `são paulo` → `sao paulo`. Ce qui distingue ce
geste d'une invention est vérifiable — **la valeur écrite est déjà dans la
colonne**. On ne crée rien, on choisit parmi ce qui existe. `80` dans une
colonne qui ne l'a jamais porté, lui, sort de nulle part.

## Ce qui est refusé, et qui surprend

`SET city = LOWER(city)` est refusé. Ce n'est pas une invention, mais ce n'est
pas non plus une correction : c'est une **transformation de toute la colonne**,
appliquée aussi aux lignes saines. Sa place est dans le modèle Silver (dbt), là
où elle sera relue, versionnée et testée — pas dans un `UPDATE` ponctuel dont
personne ne saura six mois plus tard qu'il a tourné.

*L'agent corrige des lignes ; dbt transforme des colonnes.*

## P6 contraint l'agent, **pas l'humain**

Décision déjà prise dans l'en-tête d'`apply` et respectée ici : si l'humain
réécrit la correction (`fix_override`), P6 ne s'applique pas. Il peut avoir
appelé le fournisseur ; il a l'autorité pour affirmer une valeur, l'agent ne
l'a pas. Les autres garde-fous, eux, restent — ils protègent de l'accident, pas
du jugement.
"""

import re
from typing import Optional

ISOLER = "isoler"
NULLIFIER = "mettre_a_null"
NORMALISER = "normaliser"
EXCLURE = "exclure_de_l_agregat"

GESTES = {
    ISOLER: "marquer les lignes en quarantaine — la donnée brute reste intacte",
    NULLIFIER: "vider la valeur et marquer la ligne — on efface, on n'invente pas",
    NORMALISER: "remplacer par une écriture déjà présente dans la colonne",
    EXCLURE: "exclure des agrégats en aval — Bronze n'est pas touché",
}

# `SET a = 1, b = 'x' WHERE …` — on capture le bloc d'affectations. Ce n'est
# **pas** un parseur SQL, et c'est assumé : une analyse syntaxique complète
# donnerait une fausse impression d'exhaustivité, alors qu'un moteur accepte des
# formes qu'aucun parseur maison ne couvre. On cherche des motifs, on le dit, et
# la garantie de fond reste structurelle — `apply` est inatteignable sans
# approbation (P3).
BLOC_SET = re.compile(r"\bSET\b(.*?)(?:\bWHERE\b|$)", re.IGNORECASE | re.DOTALL)


def _affectations(sql: str) -> list[tuple[str, str]]:
    """Les couples `(colonne, expression)` d'un `UPDATE … SET …`."""
    bloc = BLOC_SET.search(sql or "")
    if not bloc:
        return []

    couples = []
    for morceau in bloc.group(1).split(","):
        if "=" not in morceau:
            continue
        colonne, _, expression = morceau.partition("=")
        couples.append((colonne.strip().strip('"').upper(), expression.strip()))
    return couples


def _litteral(expression: str) -> Optional[str]:
    """La valeur d'une expression **littérale**, ou `None` si c'en est une autre.

    Une fonction, un calcul, une référence à une autre colonne rendent `None` —
    et c'est ce qui fait refuser `prix / 100` comme `LOWER(city)` : dans les deux
    cas, ce qui sera écrit n'est pas connu au moment où on décide.
    """
    texte = expression.strip().rstrip(";").strip()
    if re.fullmatch(r"'([^']*)'", texte):
        return texte[1:-1]
    if re.fullmatch(r"[+-]?\d+(\.\d+)?", texte):
        return texte
    return None


def valeurs_deja_presentes(colonne: str, anomalies: list, profil: dict) -> set:
    """Ce que la colonne contient déjà — le seul vivier où puiser une valeur.

    Deux sources, toutes deux **mesurées** : le top-K du profil (ce qu'on a vu),
    et les écritures d'une grappe de collision (ce qu'on a vu autrement). Jamais
    une liste écrite à la main, jamais une valeur du contrat — un contrat dit ce
    qui *devrait* être, pas ce qui *est*, et écrire une valeur admise mais jamais
    observée resterait une invention.
    """
    presentes = set()

    stats = ((profil or {}).get("columns") or {}).get(colonne) or {}
    for entree in stats.get("top") or []:
        if "value" in entree:
            presentes.add(str(entree["value"]))

    for anomalie in anomalies or []:
        if (anomalie.get("colonne") or "").upper() != colonne:
            continue
        observe = anomalie.get("observe")
        if isinstance(observe, (list, tuple)):
            presentes.update(str(v) for v in observe)
        reference = anomalie.get("reference")
        if anomalie.get("type") == "collision_semantique" and isinstance(
            reference, str
        ):
            # La forme normalisée d'une grappe : c'est *elle* qu'on veut écrire,
            # et elle est par construction l'une des écritures observées.
            presentes.add(reference)

    return presentes


def controler(sql: Optional[str], anomalies: list, profil: dict) -> list[str]:
    """Ce qui, dans ce SQL, **inventerait** une valeur. Vide = rien à signaler.

    Ne regarde que les colonnes **diagnostiquées** : écrire dans une autre
    colonne, c'est marquer une ligne (quarantaine), et c'est autorisé. La donnée
    d'origine, elle, n'est pas touchée.
    """
    if not sql or not isinstance(sql, str):
        return []

    diagnostiquees = {
        (a.get("colonne") or "").upper() for a in (anomalies or []) if a.get("colonne")
    }
    refus = []

    for colonne, expression in _affectations(sql):
        if colonne not in diagnostiquees:
            continue  # colonne de marquage : c'est de l'isolement, pas une invention

        if expression.strip().rstrip(";").strip().upper() == "NULL":
            continue

        valeur = _litteral(expression)
        if valeur is None:
            refus.append(
                f"{colonne} = {expression.strip()} : ce qui sera écrit n'est pas "
                f"connu au moment de décider — une correction agit sur des lignes, "
                f"une transformation de colonne appartient au modèle dbt"
            )
            continue

        presentes = valeurs_deja_presentes(colonne, anomalies, profil)
        if valeur not in presentes:
            refus.append(
                f"{colonne} = {expression.strip()} : cette valeur n'a jamais été "
                f"observée dans la colonne — l'agent la fabriquerait (P6)"
            )

    return refus


def correction_par_defaut(ecart: dict) -> dict:
    """Le geste sûr pour cet écart, quand le modèle n'en propose pas d'acceptable.

    ⭐ Sur une valeur hors bornes, le défaut est **isoler + exclure**, jamais
    remplacer : c'est la seule réponse qui ne suppose rien sur ce que la valeur
    aurait dû être. La donnée brute reste en Bronze pour l'audit, et l'agrégat
    cesse d'être faux — les deux moitiés du problème, sans en inventer une.
    """
    type_ = ecart.get("type")
    colonne = ecart.get("colonne")

    if type_ == "hors_bornes":
        gestes = [ISOLER, EXCLURE]
        pourquoi = (
            "la valeur peut être une erreur d'unité, une faute de frappe ou une "
            "vraie valeur extrême — rien ne permet de trancher, donc rien ne "
            "permet de la remplacer"
        )
    elif type_ == "collision_semantique":
        gestes = [NORMALISER]
        pourquoi = (
            "les écritures de la grappe existent toutes dans la colonne : en "
            "choisir une n'invente rien"
        )
    elif type_ in ("nulls_interdits", "doublons"):
        gestes = [ISOLER]
        pourquoi = "isoler les lignes concernées laisse la donnée brute intacte"
    else:
        gestes = [ISOLER]
        pourquoi = "à défaut de geste évident, on marque sans rien modifier"

    return {
        "gestes": gestes,
        "colonne": colonne,
        "pourquoi": pourquoi,
        "interdit": "remplacer par une valeur devinée (invariant P6)",
    }
