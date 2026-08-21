"""Contrôle des contrats (phases 4.2.2 et 4.2.4) : proposer, écrire, relire.

Le contrat est le 3ᵉ pilier de détection, et il a un défaut de naissance connu :
un générateur naïf **grave ce qu'il observe**. Sur `customer_city`, il écrirait
`accepted_values: [sao paulo, são paulo]` et légitimerait l'anomalie que tout le
projet existe pour attraper.

Une bonne moitié de ce fichier éprouve donc ce que le système **refuse** de
faire : proposer une clause sans preuve, et appliquer un contrat que personne
n'a signé.
"""

import pytest

from agent.characterize import grouper_collisions, normaliser
from agent.contracts import (
    AUCUNE_DONNEE,
    COLLISION,
    DOUBLONS,
    NOMBRES_ILLISIBLES,
    PREUVE_PARTIELLE,
    PROPOSE,
    ContratInvalide,
    charger,
    ecrire,
    lister,
    proposer,
)


def fiche(colonnes, row_count=1000, table="RAW.ORDERS", batch_id="2018-04-29"):
    return {
        "table": table,
        "batch_id": batch_id,
        "row_count": row_count,
        "columns": colonnes,
    }


def categorielle(valeurs, coverage=1.0, nulls=0):
    return {
        "role": "categorical",
        "null_count": nulls,
        "distinct": len(valeurs),
        "measure": "top_values",
        "coverage": coverage,
        "top": [{"value": v, "count": 10} for v in valeurs],
    }


# ---------------------------------------------------------------------------
# Ce que la proposition REFUSE de dire — la moitié qui compte
# ---------------------------------------------------------------------------


def test_une_collision_semantique_retire_les_valeurs_acceptees():
    """LE test du fil rouge, pris à sa racine.

    Si `accepted_values` contenait `sao paulo` **et** `são paulo`, le contrat
    déclarerait les deux légitimes. `detect` ne pourrait plus rien signaler : la
    référence elle-même dirait que tout va bien, et le cas d'école du projet
    serait perdu avant d'avoir commencé.
    """
    villes = categorielle(["sao paulo", "são paulo", "rio de janeiro"])
    contrat = proposer(fiche({"CUSTOMER_CITY": villes}))

    assert "accepted_values" not in contrat["columns"]["CUSTOMER_CITY"]

    (alerte,) = contrat["warnings"]
    assert alerte["kind"] == COLLISION
    assert "sao paulo" in alerte["detail"] and "são paulo" in alerte["detail"]


def test_la_clause_anti_collision_est_proposee_meme_quand_elle_est_violee():
    """Un contrat dit ce qui **devrait** être vrai ; l'avertissement dit que ça
    ne l'est pas encore.

    Escamoter la clause parce qu'elle est déjà violée reviendrait à choisir à la
    place de l'humain — alors que « nettoie-t-on, ou accepte-t-on ? » est
    exactement la question qu'il faut lui poser.
    """
    villes = categorielle(["sao paulo", "são paulo"])
    contrat = proposer(fiche({"CUSTOMER_CITY": villes}))

    assert contrat["columns"]["CUSTOMER_CITY"]["no_semantic_collisions"] is True
    assert contrat["warnings"][0]["kind"] == COLLISION


def test_un_top_k_tronque_ne_donne_pas_de_valeurs_acceptees():
    """Le refus le plus sournois des trois.

    `top_values` rend les K valeurs les **plus fréquentes**. Si elles ne
    couvrent que 60 % des lignes, les 40 % restants sont des valeurs légitimes
    absentes de la liste. Un contrat construit là-dessus crierait dès le
    lendemain, sur des données parfaitement saines — et on apprendrait à
    ignorer ses alertes.
    """
    statuts = categorielle(["approved", "delivered"], coverage=0.6)
    contrat = proposer(fiche({"ORDER_STATUS": statuts}))

    assert "accepted_values" not in contrat["columns"]["ORDER_STATUS"]
    (alerte,) = contrat["warnings"]
    assert alerte["kind"] == PREUVE_PARTIELLE
    assert "60" in alerte["detail"]


def test_le_texte_libre_ne_recoit_jamais_de_valeurs_acceptees():
    """Énumérer des commentaires clients n'aurait aucun sens — et les faire
    figurer dans un contrat versionné dans git ferait **sortir la donnée** du
    système observé (règle R2).

    ⚠️ La colonne porte ici un `top`, **exprès**, alors qu'aucune colonne de
    texte libre n'en reçoit aujourd'hui : `profile_table` ne mesure que les
    colonnes catégorielles. Première version de ce test : sans `top`. Un
    sabotage qui ajoutait la fuite est passé inaperçu — la propriété tenait par
    construction, pas par vérification, et le jour où quelqu'un mesurera les
    colonnes de texte libre (pour leurs longueurs, prévu au tableau des rôles),
    rien n'aurait signalé la fuite.
    """
    commentaires = {
        "role": "free_text",
        "null_count": 0,
        "distinct": 940,
        "measure": "top_values",
        "coverage": 1.0,
        "top": [{"value": "adorei o produto", "count": 3}],
    }
    clauses = proposer(fiche({"REVIEW_COMMENT": commentaires}))["columns"]

    assert "accepted_values" not in clauses["REVIEW_COMMENT"]
    assert clauses["REVIEW_COMMENT"] == {"role": "free_text", "not_null": True}


# ---------------------------------------------------------------------------
# Ce qu'elle propose, rôle par rôle
# ---------------------------------------------------------------------------


def test_une_colonne_categorielle_propre_donne_ses_valeurs():
    statuts = categorielle(["shipped", "approved", "delivered"])
    clauses = proposer(fiche({"ORDER_STATUS": statuts}))["columns"]["ORDER_STATUS"]

    assert clauses["accepted_values"] == ["approved", "delivered", "shipped"]
    assert clauses["no_semantic_collisions"] is True


def test_un_identifiant_donne_unicite_et_non_nullite():
    identifiant = {"role": "identifier", "null_count": 0, "distinct": 1000}
    contrat = proposer(fiche({"ORDER_ID": identifiant}))

    assert contrat["columns"]["ORDER_ID"] == {
        "role": "identifier",
        "unique": True,
        "not_null": True,
    }
    assert contrat["warnings"] == []


def test_des_doublons_deja_presents_sont_signales_sans_retirer_la_clause():
    """Même raisonnement que pour les collisions : la clause dit ce qui devrait
    être vrai, l'avertissement dit combien il manque."""
    identifiant = {"role": "identifier", "null_count": 0, "distinct": 997}
    contrat = proposer(fiche({"ORDER_ID": identifiant}))

    assert contrat["columns"]["ORDER_ID"]["unique"] is True
    (alerte,) = contrat["warnings"]
    assert alerte["kind"] == DOUBLONS
    assert "3 doublon" in alerte["detail"]


def test_une_colonne_numerique_donne_ses_bornes_numeriques():
    """⚠️ `numeric_min`/`numeric_max`, jamais `min`/`max`.

    Sur Bronze ces derniers sont **lexicographiques** — `"8000" < "90"`. Graver
    une borne lexicographique dans un contrat ne veut rien dire, et la
    comparaison de 4.3 porterait sur deux grandeurs différentes selon la couche.
    """
    montant = {
        "role": "numeric",
        "null_count": 0,
        "distinct": 800,
        "min": "0.00",  # lexicographique — le piège
        "max": "90",  # lexicographique — le piège
        "numeric_min": 0.0,
        "numeric_max": 13664.08,
        "numeric_rate": 1.0,
    }
    clauses = proposer(fiche({"PAYMENT_VALUE": montant}))["columns"]["PAYMENT_VALUE"]

    assert clauses["between"] == [0.0, 13664.08]
    assert "90" not in str(clauses["between"])


def test_des_valeurs_illisibles_comme_nombres_sont_signalees():
    """Sur Bronze tout est texte : une colonne de montants dont 30 % ne se lisent
    plus comme des nombres est une **dérive de format**."""
    montant = {
        "role": "numeric",
        "null_count": 0,
        "distinct": 800,
        "numeric_min": 0.0,
        "numeric_max": 99.0,
        "numeric_rate": 0.7,
    }
    contrat = proposer(fiche({"PAYMENT_VALUE": montant}))

    (alerte,) = contrat["warnings"]
    assert alerte["kind"] == NOMBRES_ILLISIBLES
    assert "30" in alerte["detail"]


def test_une_colonne_temporelle_ne_recoit_pas_de_clause_de_fraicheur():
    """La fraîcheur, les dates futures et les trous demandent des mesures que
    4.1.4 n'a pas livrées. Proposer une clause qu'on ne saurait pas vérifier
    serait pire que n'en proposer aucune."""
    horodatage = {"role": "temporal", "null_count": 0, "distinct": 990}
    clauses = proposer(fiche({"PURCHASED_AT": horodatage}))["columns"]["PURCHASED_AT"]

    assert clauses == {"role": "temporal", "not_null": True}


def test_une_colonne_vide_ne_recoit_aucun_controle():
    vide = {"role": "unknown", "null_count": 1000, "distinct": 0}
    contrat = proposer(fiche({"VIDE": vide}))

    assert contrat["columns"]["VIDE"] == {"role": "unknown"}
    assert contrat["warnings"][0]["kind"] == AUCUNE_DONNEE


def test_une_colonne_avec_des_nuls_ne_recoit_pas_not_null():
    """`not_null` proposé sur une colonne déjà trouée serait violé le jour même,
    et l'humain apprendrait à valider sans lire."""
    troue = categorielle(["a", "b"], nulls=12)
    clauses = proposer(fiche({"OPTIONNEL": troue}))["columns"]["OPTIONNEL"]

    assert "not_null" not in clauses


# ---------------------------------------------------------------------------
# Le document lui-même
# ---------------------------------------------------------------------------


def test_rien_n_est_normatif_sans_decision_humaine():
    """Le point le plus important du module.

    Ce qu'on mesure est *descriptif* (« observé entre 0 et 13 664 ») ; ce qu'un
    contrat affirme est *normatif* (« 13 664 est une vraie borne métier »). Le
    passage de l'un à l'autre n'est pas un calcul.

    ⚠️ La chaîne est écrite **en dur**, pas comparée à `PROPOSE`. Première
    version : `assert contrat["status"] == PROPOSE`. Un sabotage qui changeait
    la constante en `"approved"` est passé inaperçu — les deux côtés bougeaient
    ensemble. Un test qui compare une constante à elle-même n'affirme rien.
    """
    contrat = proposer(fiche({"ORDER_STATUS": categorielle(["a", "b"])}))
    assert contrat["status"] == "proposed"
    assert contrat["version"] == 1


def test_le_vocabulaire_du_contrat_est_stable():
    """Ces chaînes sortent du module : elles iront dans `contracts/*.yaml`, dans
    `OPS.INCIDENTS` et dans les écrans de la phase 6.

    Les renommer sans le vouloir casserait des consommateurs qui ne sont pas
    encore écrits — et aucun test ne le verrait, puisque tous les autres passent
    par les constantes. Celui-ci les épingle une fois pour toutes.
    """
    assert (
        PROPOSE,
        COLLISION,
        DOUBLONS,
        PREUVE_PARTIELLE,
        NOMBRES_ILLISIBLES,
        AUCUNE_DONNEE,
    ) == (
        "proposed",
        "semantic_collision",
        "duplicates_observed",
        "partial_evidence",
        "unreadable_numbers",
        "no_data",
    )


def test_le_contrat_dit_de_quoi_il_a_ete_tire():
    """Sans ça, personne ne peut refaire le raisonnement six semaines plus tard,
    ni savoir si la fenêtre était propre quand les clauses ont été écrites."""
    contrat = proposer(fiche({"ORDER_STATUS": categorielle(["a"])}, row_count=42))

    assert contrat["source"] == {"batch_id": "2018-04-29", "row_count": 42}
    assert contrat["table"] == "RAW.ORDERS"


def test_une_table_absente_n_a_pas_de_contrat():
    """C'est la famille *inventaire* de `detect` qui dira pourquoi, pas ici."""
    assert proposer(None) is None


def test_un_role_inconnu_ne_fait_pas_planter_la_proposition():
    """Un rôle qu'on ne sait pas traiter doit produire « aucun contrôle », pas
    une exception : un run qui meurt sur une colonne exotique ne dit rien des
    seize autres."""
    exotique = {"role": "foreign_key", "null_count": 0, "distinct": 30}
    contrat = proposer(fiche({"CUSTOMER_ID": exotique}))

    assert contrat["columns"]["CUSTOMER_ID"] == {"role": "foreign_key"}


# ---------------------------------------------------------------------------
# Le repli, et ce qu'il se refuse à faire
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "brut,attendu",
    [
        ("  São   PAULO ", "sao paulo"),
        ("são paulo", "sao paulo"),
        ("BRASÍLIA", "brasilia"),
        ("niterói", "niteroi"),
    ],
)
def test_le_repli(brut, attendu):
    assert normaliser(brut) == attendu


def test_le_repli_ne_supprime_pas_les_espaces():
    """Limite connue et assumée : `sãopaulo` échappe au repli.

    Supprimer les espaces l'attraperait, mais fusionnerait aussi `arco verde` et
    `arcoverde`, deux communes brésiliennes distinctes. Un détecteur qui invente
    des égalités ferait retirer du contrat des valeurs légitimes.

    Sans coût sur le corrigé : les 18 variantes injectées au J50 sont **toutes
    accentuelles**, et les variantes d'espace réelles ont été repliées dans la
    fenêtre de référence par la phase 1.5.
    """
    assert normaliser("sãopaulo") != normaliser("são paulo")
    assert grouper_collisions(["arco verde", "arcoverde"]) == []


def test_une_valeur_seule_ne_fait_pas_une_grappe():
    assert grouper_collisions(["sao paulo", "santos"]) == []


def test_les_grappes_sont_triees_et_deterministes():
    """Deux exécutions doivent produire le même rapport — sinon une détection
    qui en dépend deviendrait intermittente.

    ⚠️ Première version : une seule grappe, et « déterministe » vérifié en
    comparant **deux appels du même processus**. Les deux idées étaient
    insuffisantes, et un sabotage l'a montré en étant détecté à un tour puis
    manqué au suivant — l'instabilité du score était elle-même le diagnostic.

    - une seule grappe ne peut pas révéler un **ordre de grappes** faux ;
    - deux appels du même processus partagent la graine de hachage de Python,
      donc un ensemble s'y parcourt toujours pareil : la comparaison passait
      quelle que soit l'implémentation.

    D'où cette version : **deux** grappes, données dans un ordre différent de
    l'ordre attendu (`sao paulo` avant `belem`, alors que le rapport doit rendre
    `belem` en premier), et une grappe à quatre écritures.
    """
    valeurs = [
        "são paulo",
        "SAO PAULO",
        "sao  paulo",  # espaces multiples : même forme repliée
        "Sao Paulo",
        "belém",
        "BELEM",
        "santos",  # seule : ne fait pas de grappe
    ]
    grappes = grouper_collisions(valeurs)

    assert grappes == [
        {"normalized": "belem", "values": ["BELEM", "belém"]},
        {
            "normalized": "sao paulo",
            "values": ["SAO PAULO", "Sao Paulo", "sao  paulo", "são paulo"],
        },
    ]
    assert grouper_collisions(list(reversed(valeurs))) == grappes


# ---------------------------------------------------------------------------
# Les contrats sur disque (4.2.4) : écrire, relire, versionner
# ---------------------------------------------------------------------------


def approuve(contrat: dict) -> dict:
    """Ce que fera la validation humaine de 4.2.5, en une ligne."""
    return {**contrat, "status": "approved"}


def contrat_simple(table="RAW.ORDERS", version=1, status="proposed"):
    return {
        "table": table,
        "version": version,
        "status": status,
        "source": {"batch_id": "2018-04-29", "row_count": 1000},
        "columns": {"ORDER_ID": {"role": "identifier", "unique": True}},
        "warnings": [],
    }


def test_un_contrat_ecrit_se_relit_a_l_identique(tmp_path):
    ecrire(approuve(contrat_simple()), "olist", dossier=tmp_path)
    assert charger("olist", "RAW.ORDERS", dossier=tmp_path) == approuve(
        contrat_simple()
    )


def test_un_contrat_propose_n_est_jamais_charge(tmp_path):
    """LE garde-fou de la phase 4.2, du même rang que R3.

    Un contrat proposé décrit ce que la machine a *observé* ; il n'a aucune
    autorité. Si `detect` pouvait l'appliquer, la validation humaine deviendrait
    décorative — le système se donnerait à lui-même la permission qu'il est
    censé demander.
    """
    ecrire(contrat_simple(), "olist", dossier=tmp_path)
    assert charger("olist", "RAW.ORDERS", dossier=tmp_path) is None


def test_un_contrat_en_attente_reste_visible(tmp_path):
    """« Aucun contrat » et « un contrat qui attend une signature » sont deux
    situations différentes. Les confondre serait un état silencieux."""
    ecrire(contrat_simple(), "olist", dossier=tmp_path)

    (vu,) = lister("olist", dossier=tmp_path)
    assert (vu["table"], vu["version"], vu["status"]) == ("RAW.ORDERS", 1, "proposed")
    assert lister("dataset_inexistant", dossier=tmp_path) == []


def test_la_derniere_version_validee_gagne(tmp_path):
    """Les contrats sont versionnés, jamais figés (décision 3) — c'est `Amend`
    qui produira les versions suivantes en phase 5."""
    ecrire(approuve(contrat_simple(version=1)), "olist", dossier=tmp_path)
    ecrire(approuve(contrat_simple(version=2)), "olist", dossier=tmp_path)

    assert charger("olist", "RAW.ORDERS", dossier=tmp_path)["version"] == 2


def test_une_version_plus_recente_mais_non_validee_ne_prime_pas(tmp_path):
    """Une v2 proposée n'annule pas la v1 validée : la surveillance continue de
    s'appuyer sur ce qui a été signé, pas sur ce qui est en discussion."""
    ecrire(approuve(contrat_simple(version=1)), "olist", dossier=tmp_path)
    ecrire(contrat_simple(version=2), "olist", dossier=tmp_path)

    assert charger("olist", "RAW.ORDERS", dossier=tmp_path)["version"] == 1


def test_ecraser_une_proposition_est_permis(tmp_path):
    """Rejouer une découverte sur une table non encore validée est normal."""
    ecrire(contrat_simple(), "olist", dossier=tmp_path)
    ecrire(contrat_simple(), "olist", dossier=tmp_path)  # ne doit pas lever


def test_ecraser_un_contrat_valide_est_refuse(tmp_path):
    """Une découverte rejouée par mégarde détruirait le travail d'un humain."""
    ecrire(approuve(contrat_simple()), "olist", dossier=tmp_path)

    with pytest.raises(ContratInvalide, match="déjà validé"):
        ecrire(contrat_simple(), "olist", dossier=tmp_path)


def test_le_nom_du_fichier_n_est_pas_l_identite(tmp_path):
    """Un `git mv` malheureux ferait appliquer les clauses d'une table à une
    autre — silencieusement, et avec des violations partout."""
    ecrit = ecrire(approuve(contrat_simple()), "olist", dossier=tmp_path)
    ecrit.rename(ecrit.with_name("RAW.CUSTOMERS.v1.yaml"))

    with pytest.raises(ContratInvalide, match="RAW.CUSTOMERS"):
        lister("olist", dossier=tmp_path)


def test_une_version_renommee_est_refusee(tmp_path):
    ecrit = ecrire(approuve(contrat_simple()), "olist", dossier=tmp_path)
    ecrit.rename(ecrit.with_name("RAW.ORDERS.v7.yaml"))

    with pytest.raises(ContratInvalide, match="version"):
        lister("olist", dossier=tmp_path)


def test_un_statut_inconnu_est_refuse(tmp_path):
    """`validé`, `ok`, `yes` : autant de façons de croire qu'on a signé. La liste
    est fermée, comme celle des couches Medallion dans le registre."""
    ecrire(contrat_simple(status="proposed"), "olist", dossier=tmp_path)
    fichier = tmp_path / "olist" / "RAW.ORDERS.v1.yaml"
    fichier.write_text(
        fichier.read_text(encoding="utf-8").replace("proposed", "presque"),
        encoding="utf-8",
    )

    with pytest.raises(ContratInvalide, match="status"):
        lister("olist", dossier=tmp_path)


def test_un_yaml_illisible_echoue_au_chargement(tmp_path):
    """Pas trois nœuds plus loin par un `KeyError` sur `columns`."""
    (tmp_path / "olist").mkdir(parents=True)
    (tmp_path / "olist" / "RAW.ORDERS.v1.yaml").write_text(
        "table: [non fermé\n", encoding="utf-8"
    )

    with pytest.raises(ContratInvalide, match="illisible"):
        lister("olist", dossier=tmp_path)


def test_les_accents_survivent_a_l_ecriture(tmp_path):
    """⚠️ Sans `allow_unicode`, `são paulo` s'écrit `s\\xE3o paulo` dans le
    fichier.

    Le contrat deviendrait illisible **précisément** sur le cas que le projet
    existe pour montrer — et un humain ne peut pas valider ce qu'il ne peut pas
    lire. On relit le fichier brut, pas l'objet rechargé : c'est ce que
    l'humain verra.
    """
    contrat = contrat_simple()
    contrat["warnings"] = [
        {"column": "CUSTOMER_CITY", "kind": "semantic_collision", "detail": "são paulo"}
    ]
    ecrit = ecrire(contrat, "olist", dossier=tmp_path)

    texte = ecrit.read_text(encoding="utf-8")
    assert "são paulo" in texte
    assert "\\xE3" not in texte and "\\u00e3" not in texte


def test_l_ordre_du_fichier_suit_le_raisonnement(tmp_path):
    """La table, son statut, d'où elle vient, ses colonnes, puis ce qui cloche.

    Un tri alphabétique mettrait `columns` avant `status` et `warnings` en
    dernier par hasard plutôt que par intention — or c'est un fichier qu'un
    humain doit lire pour décider.
    """
    ecrit = ecrire(contrat_simple(), "olist", dossier=tmp_path)
    lignes = [
        ligne.split(":")[0]
        for ligne in ecrit.read_text(encoding="utf-8").splitlines()
        if ligne and not ligne.startswith((" ", "-"))
    ]
    assert lignes == ["table", "version", "status", "source", "columns", "warnings"]


def test_le_cycle_complet_depuis_un_profil(tmp_path):
    """De bout en bout : profil -> proposition -> disque -> validation -> relu.

    C'est le chemin que `scripts/discover.py` empruntera en 4.2.5.
    """
    villes = categorielle(["sao paulo", "são paulo"])
    propose = proposer(fiche({"CUSTOMER_CITY": villes}, table="RAW.CUSTOMERS"))

    ecrire(propose, "olist", dossier=tmp_path)
    assert charger("olist", "RAW.CUSTOMERS", dossier=tmp_path) is None, (
        "rien n'est signé"
    )

    valide = approuve(propose)
    ecrire(valide, "olist", dossier=tmp_path)
    relu = charger("olist", "RAW.CUSTOMERS", dossier=tmp_path)

    assert relu["columns"]["CUSTOMER_CITY"]["no_semantic_collisions"] is True
    assert "accepted_values" not in relu["columns"]["CUSTOMER_CITY"]
    assert relu["warnings"][0]["kind"] == COLLISION


# ---------------------------------------------------------------------------
# Signer un contrat — la voie partagée (phase 6.2)
# ---------------------------------------------------------------------------


def test_signer_exige_un_signataire(tmp_path):
    """⭐ Un contrat sans signataire ne prouve rien six mois plus tard.

    C'est la même traçabilité que `decided_by` dans le cycle de surveillance —
    et le garde-fou vit **dans le module partagé**, pas dans le `argparse` de
    `discover.py` : l'interface Streamlit doit l'hériter sans le réécrire.

    Écrit après un sabotage passé inaperçu : retirer cette vérification laissait
    la suite verte, alors qu'un bouton mal câblé aurait pu signer sous « None ».
    """
    from agent.contracts.validation import approuver

    contrat = proposer_contrat_jouet()
    ecrire(contrat, "jouet", tmp_path)

    for sans_nom in ("", "   ", None):
        with pytest.raises(ContratInvalide):
            approuver("jouet", contrat["table"], sans_nom, dossier=tmp_path)


def test_signer_une_reserve_exige_de_l_accepter(tmp_path):
    """Signer une collision sémantique est une **décision**, pas une formalité.
    Sans ce garde-fou, toute la critique de la découverte serait décorative."""
    from agent.contracts.validation import approuver

    contrat = proposer_contrat_jouet()
    contrat["warnings"] = [
        {"column": "VILLE", "kind": "partial_evidence", "detail": "43%"}
    ]
    ecrire(contrat, "jouet", tmp_path)

    with pytest.raises(ContratInvalide):
        approuver("jouet", contrat["table"], "hoda", dossier=tmp_path)

    signe = approuver("jouet", contrat["table"], "hoda", True, dossier=tmp_path)
    assert signe["status"] == "approved" and signe["approved_by"] == "hoda"


def proposer_contrat_jouet() -> dict:
    return {
        "table": "RAW.JOUET",
        "version": 1,
        "status": "proposed",
        "source": {"batch_id": None, "row_count": 10},
        "columns": {"VILLE": {"role": "categorical", "not_null": True}},
        "warnings": [],
    }
