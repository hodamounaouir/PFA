"""Les contrats sur disque : écrire, relire, versionner (phase 4.2.4).

Un contrat vit dans `contracts/<dataset>/<TABLE>.v<N>.yaml`, **versionné dans
git**. C'est un choix déjà tranché ([ADR 010](../../docs/adr/010-agent-generique.md)) :
les contrats sont de la connaissance métier, pas de la donnée. Ils se relisent
dans une pull request, se comparent d'une version à l'autre, et se restaurent.

## Lecture et écriture au même endroit, et pourquoi

Ce module fait les deux. Ce n'est pas de la commodité : le **format** du fichier
n'existe qu'ici, donc il ne peut pas se désynchroniser entre celui qui écrit et
celui qui relit. Un lecteur et un écrivain dans deux fichiers séparés dérivent —
c'est la même leçon que le schéma du graphe, dessiné à la main puis désynchronisé,
qui est aujourd'hui généré depuis le code.

## `charger()` ne rend que du **validé**

C'est la garantie structurelle de la phase 4.2, et elle est du même rang que R3
(« aucun chemin vers `Apply` sans décision humaine »). Un contrat proposé décrit
ce que la machine a *observé* ; il n'a aucune autorité. Si `detect` pouvait
l'appliquer, la validation humaine deviendrait décorative — le système se
donnerait à lui-même la permission qu'il est censé demander.

Un contrat en attente n'est pas invisible pour autant : `lister()` le montre,
avec son statut. « Aucun contrat » et « un contrat qui attend ta signature » sont
deux situations différentes, et les confondre serait un état silencieux.

## Écrire n'écrase jamais une décision

Rejouer une découverte sur une table dont la proposition n'est pas encore
validée est normal — le fichier est remplacé. Le faire sur une table **déjà
validée** détruirait le travail d'un humain : c'est refusé, bruyamment.

## Le nom du fichier n'est pas l'identité

Le contrat porte son `table` et sa `version` **dans son contenu**, et le
chargeur vérifie qu'ils correspondent au nom du fichier. Sans ce contrôle, un
`git mv` malheureux ferait appliquer les clauses de `RAW.ORDERS` à
`RAW.CUSTOMERS` — silencieusement, et avec des violations partout.
"""

import re
from pathlib import Path
from typing import Optional

import yaml

from agent.contracts.proposer import APPROUVE, STATUTS

CONTRACTS_DIR = Path(__file__).resolve().parent.parent.parent / "contracts"

# `RAW.ORDERS.v1` -> table `RAW.ORDERS`, version 1. Le point de la table est
# conservé pour que le fichier reste trouvable par le nom qu'on cherche.
NOM_FICHIER = re.compile(r"^(?P<table>.+)\.v(?P<version>\d+)$")


class ContratInvalide(Exception):
    """Le fichier est illisible, incomplet, ou ne dit pas ce que son nom annonce."""


def _exiger(condition: bool, message: str) -> None:
    if not condition:
        raise ContratInvalide(message)


def chemin(
    dataset: str, table: str, version: int, dossier: Path = CONTRACTS_DIR
) -> Path:
    return dossier / dataset / f"{table}.v{version}.yaml"


def _lire(source: Path) -> dict:
    """Charge et valide un fichier de contrat. Lève plutôt que de rendre du faux."""
    try:
        brut = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as erreur:
        raise ContratInvalide(f"{source} : YAML illisible — {erreur}") from erreur

    _exiger(
        isinstance(brut, dict), f"{source} : le fichier doit contenir un objet YAML"
    )
    _exiger(
        brut.get("status") in STATUTS,
        f"{source} : `status` vaut {brut.get('status')!r}, "
        f"attendu l'un de {', '.join(STATUTS)}",
    )
    _exiger(isinstance(brut.get("columns"), dict), f"{source} : `columns` manquant")

    correspondance = NOM_FICHIER.match(source.stem)
    _exiger(
        correspondance is not None,
        f"{source} : nom attendu `<TABLE>.v<N>.yaml`",
    )
    # Le nom du fichier n'est pas l'identité : un `git mv` malheureux ferait
    # sinon appliquer les clauses d'une table à une autre, silencieusement.
    _exiger(
        brut.get("table") == correspondance["table"],
        f"{source} : le fichier annonce la table {correspondance['table']!r} "
        f"mais son contenu dit {brut.get('table')!r}",
    )
    _exiger(
        brut.get("version") == int(correspondance["version"]),
        f"{source} : le fichier annonce la version {correspondance['version']} "
        f"mais son contenu dit {brut.get('version')!r}",
    )
    return brut


def lister(dataset: str, dossier: Path = CONTRACTS_DIR) -> list[dict]:
    """Tout ce qui est sur disque pour ce dataset, validé ou non.

    Rend `[{"table", "version", "status", "path"}]`, trié par table puis par
    version. C'est ce qui permet de distinguer « aucun contrat » de « un contrat
    qui attend une signature » — deux situations que `charger()` rend
    identiques, et qu'il serait dangereux de confondre.
    """
    racine = dossier / dataset
    if not racine.is_dir():
        return []

    trouves = []
    for fichier in sorted(racine.glob("*.yaml")):
        contrat = _lire(fichier)
        trouves.append(
            {
                "table": contrat["table"],
                "version": contrat["version"],
                "status": contrat["status"],
                "path": fichier,
            }
        )
    return sorted(trouves, key=lambda c: (c["table"], c["version"]))


def charger(dataset: str, table: str, dossier: Path = CONTRACTS_DIR) -> Optional[dict]:
    """Le contrat **validé** le plus récent pour cette table, ou `None`.

    `None` signifie « aucune clause n'a autorité ici » — soit qu'aucun contrat
    n'existe, soit qu'aucun n'a été validé. Dans les deux cas, `detect` se
    rabat sur ses autres piliers (l'historique du schéma, la dérive
    statistique) plutôt que d'appliquer ce que personne n'a signé.

    Un contrat `proposed` n'est **jamais** rendu ici. Il décrit ce que la
    machine a observé, pas ce qui a été décidé : l'appliquer reviendrait à se
    donner à soi-même la permission qu'on est censé demander.
    """
    validés = [
        c
        for c in lister(dataset, dossier)
        if c["table"] == table and c["status"] == APPROUVE
    ]
    if not validés:
        return None
    return _lire(max(validés, key=lambda c: c["version"])["path"])


def ecrire(contrat: dict, dataset: str, dossier: Path = CONTRACTS_DIR) -> Path:
    """Écrit un contrat et rend son chemin. **N'écrase jamais un contrat validé.**

    Rejouer une découverte sur une table dont la proposition attend encore une
    signature est normal : le fichier est remplacé. Le faire sur une table déjà
    validée détruirait le travail d'un humain — c'est refusé.
    """
    table, version = contrat["table"], contrat["version"]
    destination = chemin(dataset, table, version, dossier)

    if destination.exists():
        existant = _lire(destination)
        _exiger(
            existant["status"] != APPROUVE,
            f"{destination} : contrat déjà validé — l'écraser effacerait une "
            f"décision humaine. Amendez-le en version {version + 1} (phase 5).",
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(
            contrat,
            # `sort_keys=False` : l'ordre est celui du raisonnement — la table,
            # son statut, d'où elle vient, ses colonnes, puis ce qui cloche. Un
            # tri alphabétique mettrait `warnings` en dernier par hasard plutôt
            # que par intention, et `columns` avant `status`.
            sort_keys=False,
            # ⚠️ Sans `allow_unicode`, `são paulo` s'écrit `s\xE3o paulo` dans le
            # fichier. Le contrat deviendrait illisible **précisément** sur le
            # cas que le projet existe pour montrer, et l'humain ne pourrait pas
            # valider ce qu'il ne peut pas lire.
            allow_unicode=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    return destination
