"""Tool `generate_dq_rule` — un écart constaté devient un test dbt (4.1.8, §5.6).

C'est le dernier tool du cahier, et celui qui change la nature de l'agent : il ne
se contente plus de corriger la donnée, il **durcit le pipeline**. Une anomalie
attrapée une fois par l'agent devient une règle que dbt vérifiera tout seul, sans
LLM, sans humain, à chaque run — donc gratuitement et pour toujours.

## Aucun SQL ici, et ce n'est pas un hasard

Le garde-fou du socle relit tout `agent/` : aucune requête ne doit y apparaître
(ADR 010, décision 7). Ce module n'émet donc que du **YAML**, et la seule règle
que dbt ne sait pas exprimer nativement — la collision sémantique — est un *test
générique maison* écrit une fois à la main dans `dbt/tests/generic/`. L'agent se
contente de l'appeler par son nom.

C'est la bonne frontière, pas un contournement : le SQL qu'exécute dbt vit dans
le projet dbt, celui qu'exécute l'agent vit derrière le connecteur. Aucun des
deux n'a de raison d'habiter ici.

## L'agent propose la règle, il ne l'installe pas

La sortie est un **fragment**, destiné à être relu puis réintégré par un humain.
Écrire directement dans `_staging.yml` reviendrait à laisser l'agent modifier les
tests qui décident si le pipeline est vert — c'est-à-dire à lui laisser changer
la définition de « ça marche ». Même raisonnement qu'à la décision 14 pour le
registre : *un agent qui réécrit ses propres critères décide de ce qu'il
surveille.*

Conséquence pratique pour le benchmark (phase 8) : les règles réintégrées portent
`tags: [generated]`, et le bras « baseline » s'exécute avec
`--exclude tag:generated`. Sans ça, la baseline attraperait des anomalies grâce à
l'agent, et la comparaison mesurerait l'agent contre lui-même.

## Bronze est une *source*, pas un modèle

`RAW.ORDERS` n'est pas un modèle dbt mais une table de la source `raw` : le YAML
n'a pas la même forme (`sources:` et non `models:`). Se tromper produirait un
fragment que dbt refuse d'analyser — et l'erreur ne ressemblerait pas à sa cause.
"""

import json
from typing import Optional

import yaml
from langchain_core.tools import tool

# Type d'écart -> (test dbt, dimension DAMA). Les quatre dimensions que le cahier
# demande de couvrir en 4.5 : complétude, unicité, validité (« format »),
# cohérence.
#
# La table est indexée sur ce que l'écart **signifie**, pas sur la famille qui
# l'a trouvé : des nulls constatés par le contrat et des nulls constatés par la
# dérive statistique appellent le même test.
TESTS_PAR_TYPE = {
    "nulls_interdits": ("not_null", "completude"),
    "doublons": ("unique", "unicite"),
    "valeur_non_admise": ("accepted_values", "validite"),
    "collision_semantique": ("no_semantic_collisions", "coherence"),
}

# Métriques dont une dérive statistique se traduit par un test dbt. Une dérive de
# volume (`row_count`) n'en produit aucun : dbt ne sait pas dire « il y a moins
# de lignes que d'habitude », c'est une comparaison à un historique et non une
# propriété du lot. Le dire plutôt que de générer une règle qui ne tient pas.
TESTS_PAR_METRIQUE = {
    "null_rate": ("not_null", "completude"),
    "null_count": ("not_null", "completude"),
}

# Le tag qui sépare le généré de la baseline figée en phase 2.
TAG = "generated"


class Cible:
    """Où le test s'attache : un modèle dbt, ou une table de source."""

    def __init__(self, table: str):
        schema, _, nom = table.rpartition(".")
        self.schema = schema.upper()
        self.nom = nom.lower()
        # Bronze = la source `raw` (cf. dbt/models/staging/_sources.yml).
        self.est_source = self.schema == "RAW"

    @property
    def source(self) -> Optional[str]:
        return "raw" if self.est_source else None


def regle_pour(ecart: dict) -> Optional[dict]:
    """Le test dbt qui aurait attrapé cet écart, ou `None` s'il n'y en a pas.

    `None` est un résultat **légitime et fréquent** : une table absente, une
    colonne disparue, un volume qui s'effondre ne se traduisent en aucun test
    dbt. Rendre une règle bancale plutôt que rien produirait des tests qui
    échouent sans rien dire, et on apprendrait à les ignorer — exactement ce que
    la découverte évite déjà en retirant une clause faute de preuve (décision
    13a).
    """
    colonne = ecart.get("colonne")
    if not colonne:
        return None

    choix = TESTS_PAR_TYPE.get(ecart.get("type"))
    if choix is None and ecart.get("famille") == "statistique":
        choix = TESTS_PAR_METRIQUE.get((ecart.get("details") or {}).get("metrique"))
    if choix is None:
        return None

    nom_test, dama = choix
    return {
        "table": ecart.get("table"),
        "colonne": colonne.lower(),
        "test": nom_test,
        "dama": dama,
        "arguments": _arguments(nom_test, ecart),
        "origine": _origine(ecart),
    }


def _arguments(nom_test: str, ecart: dict) -> dict:
    """Ce que le test attend en plus de son nom.

    Seul `accepted_values` en a : la liste close. On la reprend de la
    **référence** de l'écart — c'est-à-dire du contrat qu'un humain a signé — et
    non des valeurs observées, qui contiennent justement l'intruse.
    """
    if nom_test != "accepted_values":
        return {}
    admises = ecart.get("reference")
    return {"values": list(admises)} if isinstance(admises, (list, tuple)) else {}


def _origine(ecart: dict) -> str:
    """La phrase qui explique, dans le YAML, d'où vient la règle.

    Un test généré sans provenance est un test que personne n'ose supprimer six
    mois plus tard, faute de savoir ce qu'il protège.
    """
    return (
        f"généré depuis un écart {ecart.get('famille')}/{ecart.get('type')} "
        f"constaté sur le lot {ecart.get('batch_id') or '(non précisé)'}"
    )


def rendre_yaml(regles: list) -> str:
    """Le fragment dbt correspondant à ces règles, prêt à être relu.

    Les règles d'une même table sont regroupées, et les colonnes triées : deux
    exécutions sur les mêmes écarts doivent produire **le même texte**, sinon un
    `git diff` deviendrait illisible et personne ne relirait plus rien.
    """
    par_cible: dict = {}
    for regle in regles:
        if regle is None:
            continue
        cible = Cible(regle["table"])
        cle = (cible.est_source, cible.nom)
        par_cible.setdefault(cle, {}).setdefault(regle["colonne"], []).append(regle)

    modeles, sources = [], []
    for (est_source, nom), colonnes in sorted(par_cible.items()):
        entree = {
            "name": nom,
            "columns": [
                {
                    "name": colonne,
                    "data_tests": [
                        _test_yaml(r) for r in sorted(liste, key=lambda r: r["test"])
                    ],
                }
                for colonne, liste in sorted(colonnes.items())
            ],
        }
        (sources if est_source else modeles).append(entree)

    document: dict = {"version": 2}
    if modeles:
        document["models"] = modeles
    if sources:
        document["sources"] = [{"name": "raw", "tables": sources}]

    return yaml.safe_dump(
        document,
        sort_keys=False,
        allow_unicode=True,  # `são paulo` doit rester lisible : on ne relit pas
        default_flow_style=False,  # ce qu'on ne peut pas lire (leçon de 4.2.4)
    )


def _test_yaml(regle: dict):
    """Un test, sous la forme que dbt attend.

    Sans argument, dbt accepte le nom nu (`- not_null`) — mais on garde toujours
    la forme longue : elle porte le `tags`, sans lequel le bras baseline de la
    phase 8 ne pourrait pas exclure le généré.
    """
    corps = dict(regle["arguments"])
    corps["tags"] = [TAG, f"dama:{regle['dama']}"]
    return {regle["test"]: corps}


@tool
def generate_dq_rule(ecarts_json: str) -> str:
    """Le fragment YAML des tests dbt qui auraient attrapé ces écarts.

    `ecarts_json` est la liste d'écarts produite par `detect`, sérialisée — un
    `@tool` ne prend que des valeurs simples (ADR 004).

    Rend une chaîne vide si aucun écart ne se traduit en test dbt : c'est le cas
    d'une table absente ou d'une dérive de volume, et ce n'est pas une erreur.
    """
    ecarts = json.loads(ecarts_json) if ecarts_json else []
    regles = [r for r in (regle_pour(e) for e in ecarts) if r is not None]
    return rendre_yaml(regles) if regles else ""
