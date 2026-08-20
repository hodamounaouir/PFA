"""Lire les verdicts de dbt (phase 4.5).

dbt teste déjà le pipeline à chaque run. Ses échecs sont des anomalies **déjà
confirmées** : inutile que l'agent les redécouvre, et surtout dommage qu'il les
ignore. Les faire entrer dans l'état, c'est leur donner accès à tout ce que
l'agent sait faire ensuite — le diagnostic, la mémoire, la signature, le journal.

## Deux fichiers, deux rôles

`run_results.json` dit **ce qui a échoué** (statut, nombre de lignes fautives).
`manifest.json` dit **de quoi il s'agit** : à quel modèle le test est attaché, sur
quelle colonne, et de quelle sorte il est (`not_null`, `unique`…).

Le second est indispensable. On pourrait découper le nom du test
(`not_null_stg_customers_customer_id`) — mais rien ne sépare le modèle de la
colonne dans cette chaîne, et un modèle nommé `customers_customer` la rendrait
ambiguë sans prévenir. Le manifest le dit sans deviner.

## Le nom du modèle n'est pas le nom de la table

dbt connaît `stg_customers` ; le registre déclare `STAGING.STG_CUSTOMERS`. La
correspondance se fait par **le registre**, pas par une table de schémas écrite
en dur : le jour où un dataset range son Silver ailleurs, rien ne bouge ici.
"""

import json
from pathlib import Path
from typing import Optional

# Sorte de test dbt -> dimension DAMA. C'est la réciproque exacte de la table de
# `agent/tools/generate_dq_rule.py` : ce que l'agent sait générer, il doit savoir
# le relire. Les garder cohérentes est une discipline, pas une contrainte
# technique — d'où le commentaire des deux côtés.
DAMA_PAR_TEST = {
    "not_null": "completude",
    "unique": "unicite",
    "accepted_values": "validite",
    "relationships": "coherence",
    "no_semantic_collisions": "coherence",
}

STATUTS_EN_ECHEC = ("fail", "error")


def lire_echecs(run_results: Path, manifest: Path, registre=None) -> list[dict]:
    """Les tests dbt en échec, enrichis de ce que le manifest en sait.

    Rend `[{table, colonne, test, sorte, dama, failures, statut}]`.

    Liste vide si l'un des deux fichiers manque : un run sans artefact dbt n'est
    pas un run sans échec, c'est un run dont on ne sait rien. Le dire par une
    liste vide est le comportement le moins trompeur — inventer un verdict à
    partir d'un fichier absent serait pire.
    """
    resultats = _charger(run_results)
    if not resultats:
        return []
    noeuds = (_charger(manifest) or {}).get("nodes", {})

    echecs = []
    for resultat in resultats.get("results", []):
        uid = resultat.get("unique_id", "")
        if (
            not uid.startswith("test.")
            or resultat.get("status") not in STATUTS_EN_ECHEC
        ):
            continue

        noeud = noeuds.get(uid, {})
        sorte = (noeud.get("test_metadata") or {}).get("name")
        echecs.append(
            {
                "table": _table_du_noeud(noeud, registre),
                "colonne": (noeud.get("column_name") or "").upper() or None,
                "test": noeud.get("name") or uid.rsplit(".", 1)[0],
                "sorte": sorte,
                "dama": DAMA_PAR_TEST.get(sorte, "exactitude"),
                "failures": resultat.get("failures"),
                "statut": resultat.get("status"),
            }
        )
    return echecs


def _charger(chemin: Path) -> Optional[dict]:
    """Le JSON, ou `None` s'il est absent ou illisible.

    Un artefact corrompu ne fait pas lever : l'agent doit pouvoir tourner même
    quand dbt a mal fini. C'est le même raisonnement que pour la mémoire — un
    confort qui manque ne doit pas empêcher le travail.
    """
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _table_du_noeud(noeud: dict, registre) -> Optional[str]:
    """`model.pfa_dbt.stg_customers` -> `STAGING.STG_CUSTOMERS`, via le registre.

    Sans registre — ou si le modèle n'y est pas déclaré — on rend le nom du
    modèle en majuscules plutôt que rien : un échec rattaché à une table qu'on ne
    surveille pas reste une information, et le taire serait le perdre.
    """
    attache = noeud.get("attached_node") or ""
    modele = attache.rsplit(".", 1)[-1] if attache else ""
    if not modele:
        return None

    if registre is not None:
        for declaree in registre.tables:
            if declaree.name.rsplit(".", 1)[-1].lower() == modele.lower():
                return declaree.name
    return modele.upper()
