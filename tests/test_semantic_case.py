"""Le fil rouge sémantique, en trois temps (phases 1.4 et 1.5, ADR 009).

Ce fichier suit une valeur — `sao paulo` — à travers les trois opérations que
le projet fait subir aux données, et prouve chacune :

    1. le dataset SOURCE porte réellement les collisions   -> justifie 2.
    2. la PRÉPARATION les efface de la fenêtre de référence -> data/prepare.py
    3. l'INJECTION les réintroduit, datées et quantifiées   -> data/inject.py

Révision du 2026-08-04 : avant, ce fichier prouvait que le cas était *réel et
permanent*. Il ne l'est plus — la référence est nettoyée au J1 et la collision
revient au J50 comme anomalie datée. Ce qu'on y gagne : le cas devient
**mesurable** en phase 8 (« détecté au jour J ») au lieu d'être constaté.

Les tests 1 et 2 lisent le CSV Olist et se sautent s'il est absent ; le test 3
n'a besoin de rien — il éprouve l'injecteur sur un lot fabriqué, donc il tourne
toujours, y compris avant qu'un seul batch ait été rejoué.
"""

import numpy as np
import pandas as pd
import pytest

from data import config
from data.inject import SemanticVariants, spread_anomalies
from data.prepare import normaliser

GEOLOCATION_CSV = config.OLIST_DIR / config.CSV_BY_TABLE["geolocation"]

besoin_du_dataset = pytest.mark.skipif(
    not GEOLOCATION_CSV.exists(),
    reason="dataset Olist absent (téléchargement manuel, cf. ADR 009)",
)


def _sans_accent(colonne: pd.Series) -> pd.Series:
    return colonne.map(normaliser).str.replace(" ", "", regex=False)


@pytest.fixture(scope="module")
def villes_source() -> pd.Series:
    return pd.read_csv(GEOLOCATION_CSV, usecols=["geolocation_city"])[
        "geolocation_city"
    ]


@pytest.fixture(scope="module")
def derive() -> dict:
    """L'anomalie étalée du corrigé, prise à son premier jour (J50)."""
    return next(a for a in spread_anomalies() if a["id"] == "semantic_drift_j50")


# --- 1. Le dataset source est bien sale --------------------------------------


@besoin_du_dataset
def test_le_dataset_source_porte_les_collisions(villes_source):
    """Sans ça, la préparation n'aurait aucune raison d'exister."""
    comptes = villes_source.value_counts()
    assert comptes["sao paulo"] > 100_000
    assert comptes["são paulo"] > 20_000


@besoin_du_dataset
def test_l_ampleur_du_desordre_source(villes_source):
    """2 042 collisions : c'est le chiffre qui a motivé la décision du 2026-08-04."""
    brut = villes_source.nunique()
    normalise = _sans_accent(villes_source).nunique()
    assert brut - normalise > 2_000


# --- 2. La préparation rend la référence propre ------------------------------


@besoin_du_dataset
def test_la_preparation_rend_la_reference_verifiablement_propre(villes_source):
    """L'invariant de la fenêtre de référence : cardinalité normalisée == brute.

    C'est la clause que le contrat de la phase 4.2 pourra graver sans mentir.
    Tant qu'elle tient, aucune collision sémantique ne survit dans le socle.
    """
    from data import prepare

    batch = {"geolocation": pd.DataFrame({"geolocation_city": villes_source})}
    rapport = prepare.appliquer(batch, __import__("datetime").date(2018, 3, 1))
    # Comparé au corrigé plutôt qu'à un nombre en dur : ajouter une règle sans
    # la déclarer, ou l'inverse, doit se voir ici.
    attendues = [p for p in prepare.charger_preparations() if p["day"] == 1]
    assert len(rapport) == len(attendues)

    nettoyees = batch["geolocation"]["geolocation_city"]
    assert nettoyees.nunique() == _sans_accent(nettoyees).nunique()


@besoin_du_dataset
def test_aucune_valeur_restante_n_est_le_doublon_cache_d_une_autre(villes_source):
    """Le VRAI invariant de propreté — plus fort que la cardinalité normalisée.

    Écrit après s'être fait prendre le 2026-08-04 : les deux premières règles
    déclaraient la fenêtre propre alors que `sa£o paulo` s'y cachait encore.
    C'était du mojibake, pas un accent — la cardinalité normalisée ne pouvait
    pas le voir, puisqu'elle ne mesure que ce qu'elle sait replier.

    Ici on prend le problème par l'autre bout : toute valeur qui contient un
    caractère non-ASCII est suspecte ; si en retirant ces caractères on retombe
    sur une valeur qui existe déjà, c'est un doublon caché.
    """
    from data import prepare

    batch = {"geolocation": pd.DataFrame({"geolocation_city": villes_source})}
    prepare.appliquer(batch, __import__("datetime").date(2018, 3, 1))
    nettoyees = batch["geolocation"]["geolocation_city"]

    presentes = set(nettoyees.unique())
    suspectes = {v for v in presentes if any(ord(c) > 127 for c in v)}
    caches = {
        v: depouillee
        for v in suspectes
        if (depouillee := "".join(c for c in v if ord(c) < 128).strip()) in presentes
    }
    assert not caches, f"doublons cachés survivants : {caches}"


@besoin_du_dataset
def test_le_seul_non_ascii_restant_est_un_vrai_nom_de_commune(villes_source):
    """`4º centenario` (Paraná) n'est pas une corruption : le `º` y est légitime.

    Le test le nomme pour qu'un futur nettoyage trop zélé se signale, et pour
    que personne ne « corrige » un vrai toponyme en croyant bien faire.
    """
    from data import prepare

    batch = {"geolocation": pd.DataFrame({"geolocation_city": villes_source})}
    prepare.appliquer(batch, __import__("datetime").date(2018, 3, 1))
    nettoyees = batch["geolocation"]["geolocation_city"]

    restantes = {v for v in nettoyees.unique() if any(ord(c) > 127 for c in v)}
    assert restantes == {"4º centenario"}


def test_le_rejeu_applique_vraiment_la_preparation(tmp_path, monkeypatch):
    """Le CÂBLAGE, pas la règle : `prepare` peut être parfait et jamais appelé.

    Sabotage joué le 2026-08-04 : retirer l'appel dans `replay.write_batch` ne
    faisait rougir aucun test — tous les autres appellent `prepare.appliquer()`
    en direct, donc ils éprouvent la règle et jamais son branchement. Les batchs
    seraient sortis sales en silence.

    Même leçon que la phase 3.3 : une règle qu'on peut oublier n'est pas une
    règle. Ici on écrit un vrai batch et on relit le fichier produit.
    """
    from data import replay

    monkeypatch.setattr(config, "INCOMING_DIR", tmp_path)
    # Les trois formes de saleté d'un coup — casse/accent, espace double,
    # mojibake — plus les deux autres valeurs que le mapping déclaré exige.
    sale = pd.DataFrame(
        {
            "geolocation_zip_code_prefix": ["01", "02", "03", "04", "05"],
            "geolocation_city": [
                "São PAULO",
                "sao  paulo",
                "sa£o paulo",
                "maceia³",
                "´teresopolis",
            ],
        }
    )
    jour = __import__("datetime").date.fromisoformat(config.WINDOW_START)
    replay.write_batch({"geolocation": sale}, jour)

    ecrit = pd.read_csv(tmp_path / jour.isoformat() / "geolocation.csv", dtype=str)
    assert set(ecrit["geolocation_city"]) == {"sao paulo", "maceio", "teresopolis"}


def test_la_preparation_ne_fusionne_pas_des_villes_differentes():
    """Le garde-fou : elle ne replie que ce que le dataset écrit déjà pareil.

    `sao paulo` et `santos` n'ont aucune raison de se rejoindre, quelles que
    soient les fréquences. Un nettoyage qui invente des égalités serait pire
    que le désordre qu'il corrige.
    """
    from data.prepare import _replier_variantes_d_espace

    colonne = pd.Series(
        ["sao paulo"] * 10 + ["santos"] * 3 + ["arcoverde"] * 4 + ["arco verde"]
    )
    replie = _replier_variantes_d_espace(colonne, {})
    assert set(replie.unique()) == {"sao paulo", "santos", "arcoverde"}


def test_le_departage_a_egalite_est_deterministe():
    """Sans lui, deux exécutions pourraient élire deux formes canoniques.

    Le rejeu cesserait d'être reproductible — et la reproductibilité est ce que
    le projet a payé le plus cher (seed figé, hash des batchs, ADR 004).
    """
    from data.prepare import _replier_variantes_d_espace

    colonne = pd.Series(["arco verde", "arcoverde"])  # 1 partout : égalité stricte
    elues = {_replier_variantes_d_espace(colonne, {}).iloc[0] for _ in range(5)}
    assert elues == {"arco verde"}, "à égalité, l'ordre alphabétique tranche"


# --- 3. L'injection les réintroduit, datées et mesurées ----------------------


def test_l_injection_reintroduit_les_variantes_au_taux_annonce(derive):
    """Le taux s'applique aux lignes CANDIDATES, pas au batch entier.

    Sinon l'ampleur réelle dépendrait de la composition du jour — un batch
    pauvre en grandes villes produirait moins d'anomalies que le corrigé
    n'en annonce, et le benchmark serait faux.
    """
    variants = derive["params"]["variants"]
    lot = pd.DataFrame(
        {"customer_city": ["sao paulo"] * 60 + ["santos"] * 40, "id": range(100)}
    )
    injecte = SemanticVariants({**derive["params"], "rate": 0.10}).apply(
        lot, np.random.default_rng(config.SEED)
    )

    accentuees = injecte["customer_city"].isin(variants.values()).sum()
    assert accentuees == 6, "10 % des 60 candidates, et non 10 % des 100 lignes"
    assert (injecte["customer_city"] == "santos").sum() == 40, "non-candidates intactes"
    assert len(injecte) == len(lot), "une variante ne crée ni ne supprime de ligne"


def test_l_injection_est_deterministe(derive):
    lot = pd.DataFrame({"customer_city": ["sao paulo", "brasilia"] * 50})
    params = {**derive["params"], "rate": 0.40}
    premier = SemanticVariants(params).apply(lot, np.random.default_rng(config.SEED))
    second = SemanticVariants(params).apply(lot, np.random.default_rng(config.SEED))
    pd.testing.assert_frame_equal(premier, second)


def test_l_agregat_par_ville_eclate_apres_injection(derive):
    """La requête témoin, version 2026-08-04 : le double comptage est mesurable.

    C'est le trou exact que la baseline dbt ne peut pas voir — aucun test de
    complétude, d'unicité ou de format ne bronche, et pourtant la métropole
    compte deux fois moins.
    """
    lot = pd.DataFrame({"customer_city": ["sao paulo"] * 100})
    injecte = SemanticVariants({**derive["params"], "rate": 0.40}).apply(
        lot, np.random.default_rng(config.SEED)
    )

    naif = injecte["customer_city"].value_counts()
    normalise = injecte["customer_city"].map(normaliser).value_counts()

    assert len(naif) == 2, "l'agrégat naïf éclate la ville en deux lignes"
    assert naif["sao paulo"] == 60
    assert normalise["sao paulo"] == 100, "la normalisation récupère les 40 perdues"


def test_la_rampe_monte_bien(derive):
    """Le signal doit être faible au début et fort à la fin (mesure de sensibilité)."""
    taux = {
        a["day"]: a["params"]["rate"]
        for a in spread_anomalies()
        if a["id"] == "semantic_drift_j50"
    }
    assert taux[50] < taux[65] < taux[78]
    assert taux[64] == taux[50], "un palier vaut jusqu'au suivant"
    assert taux[92] == taux[78], "le dernier palier court jusqu'à la fin de fenêtre"


def test_les_variantes_declarees_sont_de_vraies_variantes(derive):
    """Une entrée qui ne change rien gonflerait le compte des candidates.

    Piège rencontré le 2026-08-04 : `juiz de fora` figurait dans la table alors
    qu'il n'a aucun accent — il aurait produit un remplacement à vide, et le
    corrigé aurait annoncé plus d'anomalies qu'il n'en existe.
    """
    for brut, accentuee in derive["params"]["variants"].items():
        assert brut != accentuee, f"{brut!r} n'a pas de forme accentuée distincte"
        assert normaliser(accentuee) == brut, (
            f"{accentuee!r} ne se replie pas sur {brut!r}"
        )
