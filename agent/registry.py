"""Le registre : ce que l'agent sait d'un dataset (phase 4.0).

Un registre est un fichier `datasets/<nom>.yaml`. Il répond à trois questions que
l'agent ne peut pas deviner tout seul :

    quelles tables surveiller ?  ·  laquelle porte le numéro de lot ?  ·  quelle couche ?

Tout le reste — les colonnes, les types, les volumes — vient de l'introspection,
donc du connecteur. C'est la ligne de partage de l'ADR 010 (décision 2) : ce qui
est *observable* est introspecté, ce qui est *déclaratif* est écrit par un humain.

Pourquoi un objet plutôt que le dict brut de PyYAML : parce qu'un registre mal
écrit doit échouer **au chargement**, avec un message qui nomme le fichier et le
champ fautif — et non trois nœuds plus loin par un `KeyError` sur `batch_column`.
Un run qui plante en plein diagnostic pour une virgule oubliée dans un YAML coûte
beaucoup plus cher à comprendre qu'un refus net au démarrage.

Usage :
    registre = charger("olist")
    for t in registre.tables_de("bronze"):
        ...
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"

# Les couches Medallion. La liste est fermée : une faute de frappe (`brnze`)
# doit être refusée, pas propagée jusque dans `INCIDENTS` où elle fausserait
# silencieusement toute analyse par couche.
COUCHES = ("bronze", "silver", "gold")


class RegistreInvalide(Exception):
    """Le registre est absent, illisible, ou incomplet."""


@dataclass(frozen=True)
class TableDeclaree:
    """Une table que l'humain a décidé de surveiller."""

    name: str
    layer: str
    # None = la table n'a pas de notion de lot (un agrégat Gold est reconstruit
    # en entier à chaque run). Le connecteur profile alors la table complète :
    # c'est le comportement correct, pas un cas dégradé.
    batch_column: Optional[str] = None


@dataclass(frozen=True)
class Registre:
    """Le contenu validé de `datasets/<name>.yaml`."""

    name: str
    connector: str
    tables: tuple[TableDeclaree, ...]

    def table(self, nom: str) -> Optional[TableDeclaree]:
        """La déclaration d'une table, ou None si elle n'est pas surveillée.

        Retourne None au lieu de lever : « cette table n'est pas déclarée » est
        une information que `detect` exploite (famille *inventaire* en 4.3), pas
        une erreur de programmation.
        """
        for t in self.tables:
            if t.name == nom:
                return t
        return None

    def tables_de(self, couche: str) -> tuple[TableDeclaree, ...]:
        """Les tables d'une couche, dans l'ordre du fichier."""
        return tuple(t for t in self.tables if t.layer == couche)

    @property
    def noms(self) -> tuple[str, ...]:
        """Les noms déclarés — la référence à laquelle `list_tables()` sera confrontée."""
        return tuple(t.name for t in self.tables)


def _exiger(condition: bool, message: str) -> None:
    if not condition:
        raise RegistreInvalide(message)


def _lire_table(brut: object, source: Path, position: int) -> TableDeclaree:
    ou = f"{source} (table #{position})"
    _exiger(
        isinstance(brut, dict), f"{ou} : chaque entrée de `tables` doit être un objet"
    )

    nom = brut.get("name")
    _exiger(isinstance(nom, str) and nom.strip() != "", f"{ou} : `name` manquant")

    couche = brut.get("layer")
    _exiger(
        couche in COUCHES,
        f"{source} : table `{nom}` — `layer` vaut {couche!r}, "
        f"attendu l'une de {', '.join(COUCHES)}",
    )

    batch = brut.get("batch_column")
    _exiger(
        batch is None or (isinstance(batch, str) and batch.strip() != ""),
        f"{source} : table `{nom}` — `batch_column` doit être une chaîne ou être absent",
    )

    inconnus = set(brut) - {"name", "layer", "batch_column"}
    # Un champ inconnu est presque toujours une faute de frappe (`bath_column`).
    # Le passer sous silence reviendrait à ignorer la déclaration de l'humain
    # sans le lui dire — et à profiler la table entière en croyant filtrer un lot.
    _exiger(
        not inconnus,
        f"{source} : table `{nom}` — champ(s) inconnu(s) : {sorted(inconnus)}",
    )

    return TableDeclaree(name=nom, layer=couche, batch_column=batch)


def charger(nom: str, dossier: Path = DATASETS_DIR) -> Registre:
    """Charge et valide `<dossier>/<nom>.yaml`.

    `dossier` est paramétrable pour que les tests branchent leurs propres
    registres sans rien déposer dans `datasets/`, qui reste réservé aux datasets
    réels du projet.
    """
    source = dossier / f"{nom}.yaml"
    if not source.is_file():
        disponibles = (
            sorted(p.stem for p in dossier.glob("*.yaml")) if dossier.is_dir() else []
        )
        raise RegistreInvalide(
            f"Registre introuvable : {source}"
            + (f" — disponibles : {', '.join(disponibles)}" if disponibles else "")
        )

    try:
        brut = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as erreur:
        raise RegistreInvalide(f"{source} : YAML illisible — {erreur}") from erreur

    _exiger(
        isinstance(brut, dict), f"{source} : le fichier doit contenir un objet YAML"
    )
    _exiger(isinstance(brut.get("name"), str), f"{source} : `name` manquant")
    _exiger(isinstance(brut.get("connector"), str), f"{source} : `connector` manquant")

    tables_brutes = brut.get("tables")
    _exiger(
        isinstance(tables_brutes, list) and tables_brutes,
        f"{source} : `tables` doit être une liste non vide — "
        f"un registre sans table ne surveille rien",
    )

    tables = tuple(
        _lire_table(t, source, i) for i, t in enumerate(tables_brutes, start=1)
    )

    doublons = sorted(
        {t.name for t in tables if [x.name for x in tables].count(t.name) > 1}
    )
    # Deux déclarations d'une même table, c'est deux `batch_column` possibles et
    # aucun moyen de savoir laquelle fait foi.
    _exiger(not doublons, f"{source} : table(s) déclarée(s) deux fois : {doublons}")

    return Registre(name=brut["name"], connector=brut["connector"], tables=tables)
