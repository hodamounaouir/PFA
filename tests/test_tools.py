"""Contrôle des tools (phase 4.1), testés **isolément** — sans base, sans réseau.

Deux niveaux :
  - `MemoireOps` est éprouvée avec un curseur factice : on vérifie le SQL émis
    et la normalisation, pas Snowflake ;
  - le tool lui-même est éprouvé avec une mémoire factice : on vérifie qu'il
    délègue et qu'il referme, pas ce que la requête renvoie.

Et un garde-fou structurel : **aucun `bind_tools` dans le projet** (ADR 004).
"""

import importlib
import re
from pathlib import Path

import pytest

from agent.connectors.ops import MemoireOps, _cle_de_table
from agent.tools import read_schema_history

RACINE = Path(__file__).resolve().parent.parent

# ⚠️ Même piège que pour `agent.nodes` (cf. conftest.py) : `agent.tools`
# réexporte le tool sous le nom de son module. `agent.tools.read_schema_history`
# désigne donc le **tool**, pas le module — un `monkeypatch` dessus ne
# remplacerait rien, silencieusement. On va chercher le module explicitement.
tool_mod = importlib.import_module("agent.tools.read_schema_history")


# Ce que l'ingestion a réellement écrit en phase 2.1 : nom de fichier CSV,
# colonnes en minuscules. C'est la forme d'origine, pas une simplification.
LIGNES_HISTORIQUE = [
    ("order_id", 1, "2018-04-29"),
    ("customer_id", 2, "2018-04-29"),
    ("payment_value", 3, "2018-04-29"),
]


class CurseurFactice:
    """Enregistre le SQL émis, rend les lignes qu'on lui a préparées.

    Volontairement redéfini ici plutôt qu'importé de `test_socle.py` : les
    fichiers de test restent autonomes, aucun ne dépend d'un autre.
    """

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []
        self._courant = []

    def execute(self, sql, parametres=None):
        self.appels.append((" ".join(sql.split()), parametres))
        self._courant = self.reponses.pop(0) if self.reponses else []

    def fetchall(self):
        return self._courant

    @property
    def sql(self):
        return self.appels[-1][0]


def brancher(monkeypatch, reponses):
    memoire = MemoireOps(base="TEST_DB")
    curseur = CurseurFactice(reponses)
    monkeypatch.setattr(memoire, "_curseur", lambda: curseur)
    return memoire, curseur


# ---------------------------------------------------------------------------
# MemoireOps : les deux pièges hérités de la phase 2.1
# ---------------------------------------------------------------------------


def test_les_colonnes_sont_rendues_en_majuscules(monkeypatch):
    """LE test qui évite un faux positif permanent en 4.3.

    L'ingestion a écrit les colonnes avec la casse du CSV (`order_id`), alors
    que `INFORMATION_SCHEMA` les rend en majuscules (`ORDER_ID`). Comparer les
    deux telles quelles ferait apparaître **toutes** les colonnes comme
    renommées, à chaque run, sur chaque table.
    """
    memoire, _ = brancher(monkeypatch, [LIGNES_HISTORIQUE])

    colonnes = memoire.lire_schema("RAW.ORDERS")
    assert [c["name"] for c in colonnes] == ["ORDER_ID", "CUSTOMER_ID", "PAYMENT_VALUE"]


def test_le_schema_du_registre_retrouve_la_table_de_l_ingestion(monkeypatch):
    """Le registre déclare `RAW.ORDERS` ; l'ingestion avait écrit `orders`."""
    memoire, curseur = brancher(monkeypatch, [LIGNES_HISTORIQUE])

    memoire.lire_schema("RAW.ORDERS")
    assert curseur.appels[-1][1] == ("orders", "orders")
    assert "LOWER(table_name)" in curseur.sql


@pytest.mark.parametrize(
    "declare,attendu",
    [
        ("RAW.ORDERS", "orders"),
        ("STAGING.STG_ORDERS", "stg_orders"),
        ("orders", "orders"),
    ],
)
def test_cle_de_table(declare, attendu):
    assert _cle_de_table(declare) == attendu


def test_table_jamais_observee_rend_une_liste_vide(monkeypatch):
    """Une table réelle a toujours au moins une colonne : la liste vide est sans ambiguïté."""
    memoire, _ = brancher(monkeypatch, [[]])
    assert memoire.lire_schema("RAW.CE_QUI_N_EXISTE_PAS") == []


def test_sans_batch_on_prend_le_dernier_observe(monkeypatch):
    """`batch_id` est un VARCHAR ISO : MAX() y vaut « le plus récent »."""
    memoire, curseur = brancher(monkeypatch, [LIGNES_HISTORIQUE])
    memoire.lire_schema("RAW.ORDERS")
    assert "MAX(batch_id)" in curseur.sql


def test_avec_un_batch_on_ne_prend_pas_le_dernier(monkeypatch):
    """Pouvoir remonter à une date donnée : c'est ce qui permettra de dire
    « la colonne existait encore au J44 »."""
    memoire, curseur = brancher(monkeypatch, [LIGNES_HISTORIQUE])
    memoire.lire_schema("RAW.ORDERS", "2018-04-14")
    assert "MAX(batch_id)" not in curseur.sql
    assert curseur.appels[-1][1] == ("orders", "2018-04-14")


# ---------------------------------------------------------------------------
# Le tool
# ---------------------------------------------------------------------------


class MemoireFactice:
    def __init__(self, resultat=None, plante=False):
        self.resultat = resultat or []
        self.plante = plante
        self.ferme = False
        self.appels = []

    def lire_schema(self, table, batch_id=None):
        self.appels.append((table, batch_id))
        if self.plante:
            raise RuntimeError("Snowflake indisponible")
        return self.resultat

    def close(self):
        self.ferme = True


def brancher_memoire(monkeypatch, memoire):
    monkeypatch.setattr(tool_mod, "MemoireOps", lambda *a, **k: memoire)
    return memoire


def test_le_tool_delegue_et_rend_le_schema(monkeypatch):
    memoire = brancher_memoire(monkeypatch, MemoireFactice([{"name": "ORDER_ID"}]))

    resultat = read_schema_history.invoke({"table": "RAW.ORDERS"})

    assert resultat == [{"name": "ORDER_ID"}]
    assert memoire.appels == [("RAW.ORDERS", None)]


def test_un_batch_vide_veut_dire_le_dernier(monkeypatch):
    """La signature d'un `@tool` n'accepte que des valeurs simples : `""` tient
    lieu de « non précisé », et ne doit pas être transmis tel quel."""
    memoire = brancher_memoire(monkeypatch, MemoireFactice())
    read_schema_history.invoke({"table": "RAW.ORDERS", "batch_id": ""})
    assert memoire.appels == [("RAW.ORDERS", None)]


def test_la_connexion_est_fermee_meme_si_la_lecture_echoue(monkeypatch):
    """Un run interrompu ne doit pas laisser une session Snowflake derrière lui."""
    memoire = brancher_memoire(monkeypatch, MemoireFactice(plante=True))

    with pytest.raises(RuntimeError):
        read_schema_history.invoke({"table": "RAW.ORDERS"})
    assert memoire.ferme


def test_le_tool_est_bien_un_tool():
    """Le §5.6 du cahier demande le format `@tool` — vérifié, pas supposé."""
    assert hasattr(read_schema_history, "invoke")
    assert read_schema_history.name == "read_schema_history"
    assert read_schema_history.args_schema is not None


# ---------------------------------------------------------------------------
# Le garde-fou de l'ADR 004
# ---------------------------------------------------------------------------


def test_aucun_bind_tools():
    """Le format `@tool` sans la délégation de flux (ADR 004).

    `bind_tools` est ce qui donnerait les tools au modèle pour qu'il choisisse
    quoi appeler — soit exactement l'agent ReAct que `DESIGN.md` §2 rejette, et
    la fin de P1 (« le graphe contrôle le flux »).

    Ce test n'interdit pas ce choix pour toujours : il le rend **visible**. S'il
    devient rouge un jour, c'est qu'une décision d'architecture a été prise, et
    elle doit passer par un ADR — pas par un import.

    On cherche un **appel** (`.bind_tools` ou `bind_tools(`) et non le mot seul :
    sinon le test attrape la documentation qui explique pourquoi on ne l'utilise
    pas. Même leçon que le test anti-fuite SQL de la phase 4.0.
    """
    appel = re.compile(r"\.bind_tools\b|\bbind_tools\s*\(")
    fautifs = [
        str(f.relative_to(RACINE))
        for dossier in ("agent", "scripts")
        for f in sorted((RACINE / dossier).rglob("*.py"))
        if appel.search(f.read_text(encoding="utf-8"))
    ]
    assert not fautifs, (
        "`bind_tools` est apparu : le modèle pourrait désormais choisir le flux "
        f"(ADR 004, DESIGN §2) — {fautifs}"
    )
