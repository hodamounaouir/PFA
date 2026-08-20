"""Garde-fous de la suite : **ni vrai LLM, ni vraie base**.

La règle vient du `CONTRIBUTING` — la CI doit être déterministe, gratuite, et
tourner sans clé API. Jusqu'ici elle reposait sur la discipline : chaque test
appelant `diagnose` devait penser à simuler le modèle. On l'a vérifié à nos
dépens en écrivant l'étape 3.3 : trois helpers l'avaient oublié, la suite est
passée de 6 à 172 secondes, et les tests dépendaient soudain du réseau, d'un
quota et du bon vouloir d'un modèle.

Une règle qu'on peut oublier n'est pas une règle. Cette fixture `autouse`
remplace donc la couture LLM pour **toute** la suite : un test qui oublierait de
simuler le modèle obtient une réponse factice au lieu d'un appel réseau.

Les tests qui veulent un autre comportement (un modèle en panne, un modèle qui
enregistre ce qu'il reçoit) redéfinissent simplement la même couture ; leur
`monkeypatch` s'applique après celui-ci et l'emporte.
"""

import importlib
from contextlib import contextmanager

import pytest

from agent.llm import Diagnostic

# `agent.nodes.__init__` réexporte les fonctions sous le nom de leur module :
# `agent.nodes.diagnose` désigne la **fonction**, pas le module. On va donc
# chercher le module explicitement, sans quoi le `monkeypatch` ne remplacerait
# rien — silencieusement, en laissant partir de vrais appels réseau.
diagnose_mod = importlib.import_module("agent.nodes.diagnose")
profile_mod = importlib.import_module("agent.nodes.profile")
apply_mod = importlib.import_module("agent.nodes.apply")
amend_mod = importlib.import_module("agent.nodes.amend")
validate_mod = importlib.import_module("agent.nodes.validate")

DIAGNOSTIC_FACTICE = Diagnostic(
    root_cause="(diagnostic factice — aucun LLM appelé en test)",
    proposed_fix="Isoler en quarantaine les lignes concernées.",
    explanation="(explication factice)",
)


@pytest.fixture(autouse=True)
def pas_de_vrai_llm(monkeypatch):
    monkeypatch.setattr(
        diagnose_mod, "diagnostiquer", lambda contexte: DIAGNOSTIC_FACTICE
    )
    # Second usage du modèle : répondre à une question de l'humain avant qu'il
    # tranche. Même nœud, même règle — donc même simulation.
    monkeypatch.setattr(
        diagnose_mod,
        "repondre",
        lambda contexte, conversation, question: f"(réponse factice à : {question})",
    )


@pytest.fixture(autouse=True)
def aucun_client_groq(monkeypatch):
    """Seconde barrière : interdire la **création** d'un client Groq.

    La fixture précédente neutralise la seule couture LLM connue aujourd'hui.
    Celle-ci couvre celles de demain : si un appel au modèle apparaît ailleurs
    — dans un nœud, un tool, un script — la suite échoue bruyamment au lieu de
    partir sur l'API sans que personne ne le remarque.

    C'est le même raisonnement que pour les garde-fous du graphe : on préfère un
    échec visible à un comportement silencieux qu'on ne découvre qu'à la facture.
    """

    def refus():
        raise AssertionError(
            "Un test a tenté d'ouvrir un client Groq. Les tests ne doivent jamais "
            "appeler un vrai LLM — simulez `diagnostiquer` (cf. tests/conftest.py)."
        )

    monkeypatch.setattr("agent.llm._client", refus)


# ---------------------------------------------------------------------------
# Seconde règle, ajoutée en 4.3 : aucun test n'ouvre de connexion Snowflake
# ---------------------------------------------------------------------------
#
# Jusqu'à la phase 4.3, `profile` était un stub sans entrée-sortie et la question
# ne se posait pas. Le nœud réel lit `OPS._PROFILES`, profile la table et
# réécrit : brancher le vrai code a fait passer la suite de 16 secondes à
# 5 minutes, avec 82 échecs — la suite ne testait plus l'agent, elle testait le
# réseau. Exactement l'incident du LLM en 3.3, à un an d'intervalle et sur une
# autre couture.
#
# La parade est la même, et elle est structurelle : un double par défaut pour
# que les tests du graphe n'aient rien à câbler, **plus** une barrière qui fait
# échouer bruyamment toute tentative de connexion réelle.


class ProfilFactice:
    """Ce que `profile_table` rend en test — piloté par les tests, jamais par une base.

    Reproduit le comportement de l'ancien stub, dont les tests du graphe
    dépendent : des nulls sur les colonnes de position 1, 5, 9… (`position % 4
    == 1`), pour que `detect` ait quelque chose à constater quel que soit le
    dataset branché. Ce n'est pas une régression : cette génération était du
    décor de test depuis le début, elle vivait simplement dans le code de
    production faute d'endroit où la mettre.
    """

    COLONNES_PAR_DEFAUT = ("col_1", "col_2", "col_3", "col_4")
    LIGNES = 351

    def __init__(self):
        self.reinitialiser()

    def reinitialiser(self) -> None:
        self.colonnes = list(self.COLONNES_PAR_DEFAUT)
        self.row_count = self.LIGNES
        self.absente = False  # simule une table déclarée mais disparue
        # ⭐ Depuis 5.3, `validate` **re-profile** pour vérifier que l'écart a
        # disparu. Le double doit donc pouvoir jouer les deux moments : la
        # mesure d'avant (anormale) et celle d'après (saine).
        #
        # Le 1ᵉʳ appel est celui de `profile`, le 2ᵉ celui de `validate` : par
        # défaut le double **guérit**, c'est-à-dire simule une correction qui a
        # marché. Un test qui veut l'échec pose `guerit = False`, et il le dit
        # ainsi explicitement au lieu de le subir.
        self.guerit = True
        self.appels = []
        self.deja_profiles = set()  # (table, lot) déjà mesurés une fois

    def invoke(self, arguments: dict):
        self.appels.append(arguments)
        if self.absente:
            return None
        # La clé est **(table, lot)** et non un compteur global : dans un run,
        # `profile` puis `validate` mesurent la même table ; dans un balayage de
        # couche, deux tables différentes sont chacune à leur premier passage.
        cle = (arguments["table"], arguments.get("batch_id"))
        premiere = cle not in self.deja_profiles
        self.deja_profiles.add(cle)
        return {
            "table": arguments["table"],
            "batch_id": arguments.get("batch_id"),
            "row_count": self.row_count,
            "columns": {
                nom: self._colonne(position, anormale=premiere or not self.guerit)
                for position, nom in enumerate(self.colonnes)
            },
        }

    def _colonne(self, position: int, anormale: bool = True) -> dict:
        """Les agrégats d'une colonne, calculés sur sa **position**.

        Sur la position et jamais sur le nom : c'est ce qui garantit que le
        double se comporte pareil quel que soit le dataset branché — un test
        qui passerait grâce à un nom de colonne ne prouverait rien de la
        généricité de l'agent.

        Les colonnes de position 1, 5, 9… (`position % 4 == 1`) portent une
        **collision sémantique**. Depuis 4.3, c'est ce que le vrai `detect`
        attrape sans référence extérieure : les tests du graphe ont besoin d'un
        écart qui existe sans contrat signé, sans historique et sans inventaire.
        Un taux de nulls n'aurait plus suffi — seul le contrat ou l'historique
        savent qu'il est anormal.
        """
        anormale = anormale and position % 4 == 1
        stats = {
            "null_rate": 0.301 if anormale else 0.0,
            "null_count": int(self.row_count * (0.301 if anormale else 0.0)),
            "distinct": max(1, self.row_count - position * 10),
            "role": "categorical",
            "measure": None,
        }
        if anormale:
            stats["measure"] = "top_values"
            stats["coverage"] = 1.0
            stats["top"] = [
                {"value": "sao paulo", "count": 200},
                {"value": "são paulo", "count": 151},
            ]
        return stats


PROFIL_FACTICE = ProfilFactice()


class MemoireFactice:
    """`OPS._PROFILES` en mémoire : écrit, relit, et n'ouvre rien.

    Partagée par toute la suite via l'instance ci-dessous, pour qu'un test
    puisse constituer un historique de plusieurs lots sans base — c'est ce dont
    la famille statistique de `detect` aura besoin.
    """

    def __init__(self):
        self.reinitialiser()

    def reinitialiser(self) -> None:
        # {(dataset, table, batch_id): {(colonne, métrique): valeur}}
        self.lots = {}
        # `OPS.INCIDENTS` : une ligne par run, append-only comme la vraie.
        self.incidents = []
        self.ecriture_leve = False  # pour éprouver la panne de journal
        self.fermee = False

    def ecrire_incident(self, incident):
        if self.ecriture_leve:
            raise RuntimeError("INCIDENTS indisponible")
        self.incidents.append(dict(incident))
        return incident.get("incident_id")

    def lire_incidents(self, dataset, table, limite=200):
        # Même filtre R5 que le SQL : un incident sans décision humaine n'a rien
        # tranché, et le lire comme un refus ferait taire l'agent sur une
        # question que personne n'a lue.
        retenus = [
            i
            for i in self.incidents
            if i.get("dataset") == dataset
            and i.get("table_name") == table
            and i.get("human_decision") is not None
        ]
        return list(reversed(retenus))[:limite]

    def ecrire_profil(self, dataset, table, batch_id, profil):
        mesures = {}
        if isinstance(profil.get("row_count"), (int, float)):
            mesures[(None, "row_count")] = float(profil["row_count"])
        for colonne, stats in profil.get("columns", {}).items():
            for nom, valeur in stats.items():
                if isinstance(valeur, (int, float)) and not isinstance(valeur, bool):
                    mesures[(colonne, nom)] = float(valeur)
        self.lots[(dataset, table, batch_id)] = mesures
        return len(mesures)

    def lire_schema(self, table, batch_id=None, avant=None):
        return list(REFERENCES.schema_connu)

    def lire_historique(self, dataset, table, avant=None, jours=None):
        lots = sorted(
            (lot, m)
            for (d, t, lot), m in self.lots.items()
            if d == dataset and t == table and (avant is None or lot < avant)
        )
        if jours:
            lots = lots[-jours:]
        series = {}
        for _lot, mesures in lots:
            for cle, valeur in mesures.items():
                series.setdefault(cle, []).append(valeur)
        return series

    def close(self):
        self.fermee = True


MEMOIRE_FACTICE = MemoireFactice()


class TableJouet:
    def __init__(self, name):
        self.name = name


class ReferencesFactices:
    """Les trois références que `profile` charge en plus de son historique.

    Rassemblées dans un seul objet piloté par les tests : contrat signé,
    registre, et contenu réel de la base. Sans ça, chaque test du graphe devrait
    câbler quatre `monkeypatch` pour appeler un nœud.
    """

    connector = "factice"

    def __init__(self):
        self.reinitialiser()

    def reinitialiser(self) -> None:
        self.contrat = None  # aucun contrat signé par défaut
        self.declarees = ["UNE.TABLE", "RAW.ORDERS"]
        self.presentes = ["UNE.TABLE", "RAW.ORDERS"]
        self.schemas = {}  # {table: [colonnes]}
        self.schema_connu = []  # ce que `_SCHEMA_HISTORY` rendrait
        self.corrections = []  # ce qu'`apply` a exécuté (5.3)
        self.contrats_ecrits = []  # ce qu'`amend` a écrit (5.3)
        self.ecriture_leve = False

    # -- vu comme un registre
    @property
    def tables(self):
        return tuple(TableJouet(n) for n in self.declarees)

    # -- vu comme un connecteur
    def list_tables(self):
        return list(self.presentes)

    def get_schema(self, table):
        colonnes = self.schemas.get(table)
        return None if colonnes is None else [{"name": c} for c in colonnes]

    # -- vu comme la cible d'une correction (5.3)
    batch_column = "_batch_id"

    def ecrire_contrat(self, contrat, dataset, dossier=None):
        self.contrats_ecrits.append(contrat)
        return f"/tmp/{dataset}/{contrat['table']}.v{contrat['version']}.yaml"

    def appliquer(self, sql, table, batch_column=None, batch_id=None):
        self.corrections.append((sql, table, batch_id))
        if self.ecriture_leve:
            raise RuntimeError("Snowflake indisponible")
        return {"lignes_affectees": 51, "lignes_avant": 351, "lignes_apres": 351}


REFERENCES = ReferencesFactices()


@pytest.fixture(autouse=True)
def pas_de_vraie_base(monkeypatch):
    """Le double par défaut : `profile` mesure et archive, sans rien ouvrir."""
    PROFIL_FACTICE.reinitialiser()
    MEMOIRE_FACTICE.reinitialiser()
    REFERENCES.reinitialiser()
    monkeypatch.setattr(profile_mod, "profile_table", PROFIL_FACTICE)
    monkeypatch.setattr(profile_mod.ops, "MemoireOps", lambda *a, **k: MEMOIRE_FACTICE)
    # Les trois références chargées par `profile` depuis 4.3.
    monkeypatch.setattr(profile_mod, "charger_registre", lambda dataset: REFERENCES)
    monkeypatch.setattr(profile_mod, "ouvrir", lambda nom: REFERENCES)
    monkeypatch.setattr(profile_mod, "fermer", lambda connecteur: None)
    monkeypatch.setattr(profile_mod.loader, "charger", lambda ds, t: REFERENCES.contrat)

    # `apply` écrit vraiment depuis 5.3 : même double par défaut, même raison —
    # aucun test ne doit toucher une base, et surtout pas en écriture.
    @contextmanager
    def _connecteur_factice(dataset, table):
        yield REFERENCES, REFERENCES

    monkeypatch.setattr(apply_mod, "connecteur_pour", _connecteur_factice)

    # `amend` écrit un contrat v2 sur disque depuis 5.3 : sans double, la suite
    # sèmerait des fichiers dans `contracts/` du dépôt.
    REFERENCES.contrats_ecrits.clear()
    monkeypatch.setattr(amend_mod, "ecrire", REFERENCES.ecrire_contrat)

    # `validate` re-profile depuis 5.3 : il importe **sa propre** référence au
    # tool, donc patcher celle de `profile` ne suffit pas. C'est le piège de la
    # réexportation sous une autre forme — un `monkeypatch` qui vise le mauvais
    # objet ne remplace rien, silencieusement.
    monkeypatch.setattr(validate_mod, "profile_table", PROFIL_FACTICE)
    MEMOIRE_FACTICE.schema_connu = REFERENCES.schema_connu


@pytest.fixture(autouse=True)
def aucune_connexion_snowflake(monkeypatch):
    """Seconde barrière, jumelle d'`aucun_client_groq`.

    La fixture précédente neutralise les coutures connues aujourd'hui ; celle-ci
    couvre celles de demain. Si une connexion apparaît ailleurs — un nœud, un
    tool, un script — la suite échoue bruyamment au lieu d'attendre le réseau,
    de consommer des crédits, et de dépendre d'un trial qui expire.
    """

    def refus(*args, **kwargs):
        raise AssertionError(
            "Un test a tenté d'ouvrir une connexion Snowflake. Les tests ne "
            "touchent jamais une vraie base — utilisez les doubles de "
            "tests/conftest.py (PROFIL_FACTICE, MEMOIRE_FACTICE) ou un "
            "connecteur en mémoire."
        )

    monkeypatch.setattr("agent.connectors.snowflake.ouvrir_connexion", refus)
