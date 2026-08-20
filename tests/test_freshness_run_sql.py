"""Contrôle des deux derniers tools du §5.6 : fraîcheur et `run_sql` (4.1.4, 4.1.6).

Rien ici ne touche à une base. La fraîcheur est une **interprétation** de bornes
déjà mesurées — c'est sa propriété centrale, elle ne coûte aucune requête. Et
`run_sql` est éprouvé sur son garde-fou et sur son ordre d'exécution, pas sur ce
que Snowflake renvoie.
"""

import datetime
import importlib

import pytest

from agent.freshness import fraicheur
from agent.sql_guard import VERBES_DE_LECTURE, lecture_seule
from agent.tools.run_sql import LIGNES_MAX, RequeteRefusee, executer, resume

run_sql_mod = importlib.import_module("agent.tools.run_sql")


# ===========================================================================
# 4.1.4 — la fraîcheur
# ===========================================================================


def bornes(mini, maxi):
    return {"min": mini, "max": maxi}


def test_un_lot_a_jour_n_a_aucun_retard():
    assert (
        fraicheur(bornes("2018-04-29", "2018-04-29"), "2018-04-29")["retard_jours"] == 0
    )


def test_une_livraison_en_retard_se_chiffre():
    faits = fraicheur(bornes("2018-04-20", "2018-04-27"), "2018-04-29")
    assert faits["retard_jours"] == 2
    assert faits["amplitude_jours"] == 7


def test_des_dates_futures_sont_signalees():
    """Un lot qui prétend couvrir le 29 avril et contient du 15 mai : soit
    l'horloge d'une source est fausse, soit le lot n'est pas celui qu'il dit."""
    assert (
        fraicheur(bornes("2018-04-29", "2018-05-15"), "2018-04-29")["dates_futures"]
        == 1
    )


def test_le_fait_ne_pretend_pas_etre_un_decompte():
    """⭐ `max` dit qu'il **existe** des dates futures, pas combien. Les compter
    demanderait la requête que cette étape existe pour éviter — et « il y en a »
    suffit à alerter, tout en restant exact."""
    faits = fraicheur(bornes("2018-01-01", "2019-01-01"), "2018-04-29")
    assert faits["dates_futures"] == 1, "un fait binaire, pas une estimation"


def test_l_amplitude_denonce_un_rechargement():
    """Un lot journalier qui couvre 91 jours n'est pas un lot, c'est un
    rechargement complet — et personne ne l'aurait vu dans un taux de nulls."""
    assert (
        fraicheur(bornes("2018-03-01", "2018-05-31"), "2018-04-29")["amplitude_jours"]
        == 91
    )


def test_la_reference_est_le_lot_et_non_l_horloge():
    """⭐ Comparer à `now()` n'aurait aucun sens : le dataset est rejoué, ses
    dates sont de 2018, et tout paraîtrait vieux de sept ans.

    Effet secondaire décisif : la mesure est **reproductible**. Rejouer le même
    lot dans deux ans rendra exactement le même retard — indispensable au
    benchmark, qu'une fraîcheur mesurée à l'horloge aurait rendu instable.
    """
    faits = fraicheur(bornes("2018-04-27", "2018-04-27"), "2018-04-29")
    assert faits["retard_jours"] == 2
    assert datetime.date.today().year > 2018, "le test n'aurait pas de sens sinon"


@pytest.mark.parametrize(
    "mini,maxi",
    [("N/A", "2018-04-29"), ("2018-04-29", "inconnu"), (None, None), ("8000", "90")],
)
def test_des_bornes_illisibles_ne_donnent_rien(mini, maxi):
    """Ne rien dire vaut mieux qu'un retard calculé sur `"N/A"`. Même symétrie
    que partout : on constate ce qu'on a mesuré, on n'extrapole pas."""
    assert fraicheur(bornes(mini, maxi), "2018-04-29") == {}


def test_les_dates_typees_sont_acceptees():
    """En Bronze tout est VARCHAR, en Silver la colonne arrive en `DATE`. Le même
    module doit lire les deux, sinon la fraîcheur ne vaudrait que pour une couche."""
    faits = fraicheur(
        bornes(datetime.date(2018, 4, 28), datetime.datetime(2018, 4, 29, 10, 56)),
        "2018-04-29",
    )
    assert faits["retard_jours"] == 0 and faits["amplitude_jours"] == 1


def test_sans_lot_de_reference_l_amplitude_reste():
    """Un mart Gold n'a pas de colonne de lot : le retard n'a pas de sens, mais
    l'étendue couverte, si. Rendre ce qu'on peut plutôt que rien."""
    faits = fraicheur(bornes("2018-03-01", "2018-05-31"), None)
    assert faits == {"amplitude_jours": 91}


def test_la_fraicheur_ne_coute_aucune_requete():
    """⭐ La propriété qui justifie l'étape.

    Le critère de 4.1.5 avait déjà tranché : une colonne temporelle ne reçoit
    aucune mesure dédiée parce que ses `min`/`max` **sont** la fraîcheur. Si
    cette fonction demandait un connecteur, elle rouvrirait une requête par
    colonne temporelle — il y en a 40 sur les 128 du dataset.
    """
    import inspect

    parametres = set(inspect.signature(fraicheur).parameters)
    assert parametres == {"stats", "batch_id"}, "aucune source de données en argument"


def test_les_metriques_de_fraicheur_entrent_dans_l_historique():
    """C'est ce qui les rend **détectables sans écrire de détecteur** : la
    famille statistique compare toute métrique numérique à son historique, donc
    un `dates_futures` constant à 0 qui passe à 1 déclenche une
    `rupture_de_constante`."""
    from agent.connectors.ops import METRIQUES_COLONNE
    from agent.detect.statistique import DAMA_PAR_METRIQUE

    for mesure in ("retard_jours", "amplitude_jours", "dates_futures"):
        assert mesure in METRIQUES_COLONNE, mesure
        assert DAMA_PAR_METRIQUE[mesure] == "fraicheur", mesure


# ===========================================================================
# 4.1.6 — `run_sql`, lecture seule
# ===========================================================================


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM RAW.ORDERS LIMIT 10",
        "with x as (select 1) select * from x",
        "SHOW TABLES IN SCHEMA RAW",
        "SELECT count(*) FROM RAW.ORDERS;",  # point-virgule final : une habitude
    ],
)
def test_une_lecture_passe(sql):
    assert lecture_seule(sql) == []


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM RAW.ORDERS",
        "UPDATE RAW.ORDERS SET x = 1",
        "DROP TABLE RAW.ORDERS",
        "TRUNCATE TABLE RAW.ORDERS",
        "MERGE INTO a USING b ON x",
        "CREATE TABLE t AS SELECT 1",
        "GRANT SELECT ON t TO r",
    ],
)
def test_une_ecriture_est_refusee(sql):
    assert lecture_seule(sql)


def test_la_liste_blanche_refuse_ce_qu_on_n_a_pas_prevu():
    """⭐ Une liste noire ne protège que de ce qu'on a pensé à y mettre.

    `COPY INTO` et `PUT` écrivent sans porter aucun des verbes évidents, et une
    version future du moteur en ajoutera d'autres. La liste blanche inverse la
    charge : ce qui n'est pas explicitement autorisé est refusé, **y compris ce
    qui n'existe pas encore**.
    """
    for sql in ("COPY INTO t FROM @s", "PUT file://x @s", "CALL ma_procedure()"):
        assert lecture_seule(sql), sql


def test_une_ecriture_cachee_apres_un_verbe_autorise_est_refusee():
    """⭐ La barrière qu'on oublie. `SELECT 1; DROP TABLE x` commence bien par
    SELECT — la liste blanche seule le laisserait passer."""
    refus = lecture_seule("SELECT 1; DROP TABLE RAW.ORDERS")
    assert refus
    assert any("DROP" in r for r in refus)


def test_plusieurs_instructions_sont_refusees():
    refus = lecture_seule("SELECT 1; SELECT 2")
    assert any("instruction" in r for r in refus)


def test_une_requete_vide_est_refusee():
    assert lecture_seule("") and lecture_seule(None) and lecture_seule("   ;  ")


def test_les_verbes_autorises_sont_nommes_dans_le_refus():
    """Le message part sous les yeux d'un humain : il doit dire quoi faire, pas
    seulement que c'est non."""
    refus = lecture_seule("DELETE FROM t")[0]
    assert all(v in refus for v in VERBES_DE_LECTURE[:2])


# --- l'ordre des opérations -------------------------------------------------


def test_la_requete_est_refusee_AVANT_toute_connexion(monkeypatch):
    """⭐ On valide, *puis* on se connecte.

    Contrôler après avoir ouvert la session laisserait une trace de connexion
    pour une requête qu'on n'avait pas le droit de poser — et le jour où le
    contrôle a un trou, la requête serait déjà partie.
    """
    ouvertures = []
    monkeypatch.setattr(
        run_sql_mod, "ouvrir", lambda nom: ouvertures.append(nom) or object()
    )
    monkeypatch.setattr(run_sql_mod, "charger_registre", lambda ds: None)

    with pytest.raises(RequeteRefusee):
        executer("olist", "DROP TABLE RAW.ORDERS")
    assert ouvertures == [], "une connexion a été ouverte pour une requête refusée"


class ConnecteurJouet:
    connector = "jouet"
    tables = ()

    def __init__(self):
        self.recu = None
        self.ferme = False

    def executer(self, sql, limite):
        self.recu = (sql, limite)
        return {"columns": ["a"], "rows": [{"a": 1}], "truncated": False}

    def close(self):
        self.ferme = True


@pytest.fixture
def jouet(monkeypatch):
    connecteur = ConnecteurJouet()
    monkeypatch.setattr(run_sql_mod, "charger_registre", lambda ds: connecteur)
    monkeypatch.setattr(run_sql_mod, "ouvrir", lambda nom: connecteur)
    return connecteur


def test_une_lecture_valide_atteint_le_connecteur(jouet):
    resultat = executer("olist", "SELECT 1 FROM t")
    assert jouet.recu == ("SELECT 1 FROM t", LIGNES_MAX)
    assert resultat["rows"] == [{"a": 1}]
    assert resultat["sql"] == "SELECT 1 FROM t"


def test_le_connecteur_est_ferme_meme_si_la_requete_echoue(monkeypatch, jouet):
    """Un run interrompu ne doit pas laisser une session Snowflake derrière lui."""

    def explose(sql, limite):
        raise RuntimeError("Snowflake indisponible")

    monkeypatch.setattr(jouet, "executer", explose)
    with pytest.raises(RuntimeError):
        executer("olist", "SELECT 1 FROM t")
    assert jouet.ferme


def test_le_journal_trace_la_requete_pas_les_valeurs():
    """⭐ Le journal d'investigation ne doit pas devenir une copie de la base par
    accumulation : on trace ce qui a été demandé et le volume, jamais ce qui est
    revenu."""
    ligne = resume(
        {
            "rows": [{"client": "Jean Dupont"}],
            "truncated": True,
            "sql": "SELECT * FROM c",
        }
    )
    assert "1 ligne" in ligne and "tronqué" in ligne and "SELECT * FROM c" in ligne
    assert "Jean Dupont" not in ligne


def test_run_sql_est_bien_un_tool():
    from agent.tools import run_sql

    assert run_sql.name == "run_sql"
    assert set(run_sql.args_schema.model_fields) == {"dataset", "sql"}
