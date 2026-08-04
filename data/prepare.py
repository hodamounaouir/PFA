"""Préparation du socle : rendre la fenêtre de référence propre (phase 1.5).

Troisième opération du pipeline de données, à côté du rejeu et de l'injection —
et la seule qui *retire* du désordre au lieu d'en ajouter :

    data/replay.py    découpe l'historique Olist en batchs quotidiens
    data/prepare.py   nettoie ce qui doit l'être, au jour 1 uniquement  ← ici
    data/inject.py    corrompt des jours choisis, après le rejeu

## Pourquoi elle existe (décision du 2026-08-04)

Le contrat de l'agent (phase 4.2) est construit sur la fenêtre de référence.
S'il apprend sur des données déjà sales, il grave le désordre comme la norme :
`sao paulo` et `são paulo` deviennent deux villes légitimes, et le cas d'école
du projet est perdu **avant** d'avoir commencé.

Or `geolocation_city` porte 2 042 collisions naturelles, mesurées le 2026-08-04.
C'est la seule colonne sale de tout le dataset — les 4 autres colonnes texte du
registre ont été contrôlées et sont propres. On la normalise donc au J1, et les
collisions reviennent plus tard, **datées et quantifiées**, par l'injecteur.

## Pourquoi c'est déclaré et pas codé en dur

Le projet a une règle : on ne modifie jamais les données sans que ce soit
inscrit dans `ground_truth.yaml`. Elle valait pour la corruption ; elle vaut
aussi pour le nettoyage. Un lecteur du benchmark doit pouvoir reconstruire
**tout** ce qui a été fait au dataset, sinon il verra une fenêtre de référence
propre sans savoir qu'elle a été rendue propre.

## Trois règles, et pourquoi il en faut trois

La première replie casse, accents et espaces multiples. Mesurée sur Olist, elle
ramène `geolocation_city` de 8 011 à 5 967 valeurs — mais il **reste 22 paires**
qui ne diffèrent que par un espace mal placé :

    ['arcoverde', 'arco verde']       ['mogi das cruzes', 'mogidascruzes']
    ['dias davila', 'dias d avila']   ['herval d oeste', 'herval doeste']

Ce sont la même ville à chaque fois. Une règle qui supprimerait *tous* les
espaces les attraperait, mais fusionnerait aussi des villes réellement
différentes — un nettoyage qui invente des égalités est pire que le désordre
qu'il corrige.

D'où la seconde règle : elle ne replie que les valeurs dont la forme sans espace
est **déjà partagée**, et elle les aligne sur la **forme majoritaire observée**.
Elle ne décide donc jamais que deux villes sont la même : elle constate que le
dataset les écrit déjà pareil à un espace près, et tranche par le nombre. C'est
exactement ce que l'agent proposera à un humain en phase 4.3, appliqué ici en
amont et déclaré.

La troisième répare du **mojibake** : `sa£o paulo`, `maceia³`, `´teresopolis` —
quatre lignes sur un million, où l'octet lui-même est corrompu. Aucune règle
générale ne peut les rattraper : rien dans la chaîne ne dit que `£` valait `ã`.
On les énumère donc nommément, et le mapping doit s'appliquer à quelque chose
(une entrée qui ne correspond à rien fait échouer le nettoyage — c'est une
faute de saisie, pas une réparation).

Découvertes le 2026-08-04 en écrivant le test « aucun accent ne survit » : les
deux premières règles déclaraient la fenêtre propre alors qu'un `são paulo`
cassé s'y cachait encore. Un invariant qui ne mesure que ce qu'il sait replier
ne prouve pas la propreté — d'où le test réel, « aucune valeur restante n'est
le doublon caché d'une autre ».

Les trois ensemble rendent la fenêtre de référence **vérifiablement** propre :
cardinalité normalisée == cardinalité brute, et aucun doublon caché.

## Une règle reçoit la colonne entière, pas une valeur

La seconde a besoin de compter pour choisir la forme majoritaire. Les deux
signatures sont donc `Series -> Series`, ce qui garde un seul mécanisme au lieu
de deux (pures / dépendantes des données).
"""

import re
import sys
import unicodedata
from datetime import date, timedelta

import pandas as pd
import yaml

from data import config

GROUND_TRUTH = config.DATA_DIR / "ground_truth.yaml"

_ESPACES = re.compile(r"\s+")


def normaliser(valeur: str) -> str:
    """Casse, accents et espaces multiples repliés. Rien d'autre.

    `"  São   PAULO "` -> `"sao paulo"`. La forme canonique est l'ASCII
    minuscule, qui est déjà celle de `customer_city` dans Olist : après
    normalisation, les deux colonnes de villes parlent la même langue, et toute
    valeur accentuée qui apparaîtra ensuite sera **forcément** une injection.
    """
    if not isinstance(valeur, str):
        return valeur
    decompose = unicodedata.normalize("NFD", valeur)
    sans_accent = "".join(c for c in decompose if unicodedata.category(c) != "Mn")
    return _ESPACES.sub(" ", sans_accent).strip().lower()


def _replier_accents_casse_espaces(colonne: pd.Series, prep: dict) -> pd.Series:
    return colonne.map(normaliser)


def _reparer_mojibake_declare(colonne: pd.Series, prep: dict) -> pd.Series:
    """Remplace des valeurs **nommément désignées** par leur forme canonique.

    Aucune règle générale ici, et c'est volontaire : `sa£o paulo` n'est pas un
    problème d'accent mais de **corruption d'octets** — un `são paulo` passé
    par un mauvais encodage. Rien dans la chaîne ne permet de deviner que `£`
    valait `ã` ; seule une décision humaine peut le dire.

    Donc on énumère. Trois valeurs sur un million de lignes, chacune doublon
    caché d'une forme déjà massivement présente. `4º centenario` n'y figure
    pas : c'est un vrai nom de commune (Paraná), pas une corruption.
    """
    mapping = prep.get("mapping") or {}
    inconnues = set(mapping) - set(colonne.unique())
    if inconnues:
        sys.exit(
            f"❌ préparation {prep['id']} : {sorted(inconnues)} absent(es) des "
            f"données — un mapping qui ne s'applique à rien est une erreur de "
            f"saisie, pas un nettoyage."
        )
    return colonne.replace(mapping)


def _replier_variantes_d_espace(colonne: pd.Series, prep: dict) -> pd.Series:
    """Aligne sur la forme majoritaire les valeurs qui ne diffèrent que d'un espace.

    Ne touche qu'aux groupes où le dataset écrit **déjà** la même chaîne à un
    espace près. Une ville dont l'écriture est unique n'est jamais modifiée.

    Départage déterministe : à égalité de fréquence, l'ordre alphabétique. Sans
    lui, deux exécutions pourraient choisir deux formes canoniques différentes,
    et le rejeu cesserait d'être reproductible.
    """
    comptes = colonne.value_counts()
    sans_espace = pd.Series(comptes.index, index=comptes.index).str.replace(
        " ", "", regex=False
    )
    canoniques: dict[str, str] = {}
    for cle, groupe in comptes.groupby(sans_espace, sort=True):
        gagnante = sorted(groupe.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        canoniques[cle] = gagnante
    return colonne.str.replace(" ", "", regex=False).map(canoniques)


REGLES = {
    "strip_accents_lower_collapse_spaces": _replier_accents_casse_espaces,
    "fold_space_variants_on_majority": _replier_variantes_d_espace,
    "repair_declared_mojibake": _reparer_mojibake_declare,
}


def charger_preparations() -> list[dict]:
    """La section `preparation` du corrigé, avec sa cohérence jour ↔ date vérifiée.

    Même contrôle que pour les anomalies : une préparation qui déclare un jour
    et une date incompatibles est une erreur de saisie, pas une préparation.
    """
    spec = yaml.safe_load(GROUND_TRUTH.read_text(encoding="utf-8"))
    debut = date.fromisoformat(config.WINDOW_START)
    preparations = spec.get("preparation") or []
    for prep in preparations:
        declaree = date.fromisoformat(str(prep["date"]))
        calculee = debut + timedelta(days=prep["day"] - 1)
        if declaree != calculee:
            sys.exit(
                f"❌ ground_truth.yaml incohérent : {prep['id']} déclare "
                f"date={declaree} mais J{prep['day']} = {calculee}"
            )
        if prep["rule"] not in REGLES:
            sys.exit(
                f"❌ ground_truth.yaml : {prep['id']} demande la règle "
                f"{prep['rule']!r}, inconnue — connues : {', '.join(REGLES)}"
            )
    return preparations


def appliquer(batch: dict[str, pd.DataFrame], jour: date) -> list[str]:
    """Applique les préparations prévues pour ce jour. Rend un compte rendu.

    Une préparation qui vise une table absente du batch est **ignorée en
    silence** : les référentiels ne sont livrés qu'au J1, et une préparation du
    J1 n'a rien à faire les 91 autres jours. En revanche une colonne absente
    d'une table présente fait lever — c'est une déclaration fausse.
    """
    rapport = []
    for prep in charger_preparations():
        if prep["day"] != (jour - date.fromisoformat(config.WINDOW_START)).days + 1:
            continue
        table = prep["table"]
        if table not in batch:
            continue
        colonne = prep["column"]
        df = batch[table]
        if colonne not in df.columns:
            sys.exit(
                f"❌ préparation {prep['id']} : colonne {colonne!r} absente de "
                f"{table} — colonnes présentes : {list(df.columns)}"
            )
        avant = int(df[colonne].nunique())
        # `assign` plutôt qu'une écriture en place : au J1 le batch porte les
        # référentiels tels quels, sans copie. Muter ici modifierait la table
        # source chargée par `replay.load_tables()` — invisible sur un run d'un
        # seul jour, faux dès qu'on rejoue le J1 deux fois dans le même process.
        df = df.assign(**{colonne: REGLES[prep["rule"]](df[colonne], prep)})
        batch[table] = df
        apres = int(df[colonne].nunique())
        rapport.append(
            f"🧼 {jour} {prep['id']:<28} {table}.{colonne} "
            f"({avant} → {apres} valeurs distinctes)"
        )
    return rapport
