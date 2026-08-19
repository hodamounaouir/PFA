"""Famille *statistique* — le lot s'écarte de ses prédécesseurs (phase 4.3).

Compare chaque mesure du lot du jour à la **même mesure sur les N lots
précédents** (`OPS._PROFILES`, chargé par `profile`). C'est la famille qui
attrape ce qu'aucune règle n'avait prévu : un volume qui s'effondre, un taux de
nulls qui apparaît, un format qui casse.

## Médiane + MAD, jamais moyenne + écart-type

Une anomalie non corrigée entre dans l'historique. Avec une moyenne et un
écart-type, les 30 % de nulls du J60 gonfleraient σ, et la **récidive du J85 —
identique — paraîtrait moins grave**. La référence se contaminerait
elle-même, et l'agent deviendrait progressivement aveugle à ce qu'il vient de
signaler. La médiane et le MAD encaissent une valeur aberrante sans bouger.

C'est mesurable, et ce sera mesuré : la récidive J60 → J85 est l'objectif O7 du
benchmark.

## Le cas « historique parfaitement constant »

Un MAD nul fait exploser le score z. Le plan prévoyait un plancher ; on n'en
pose pas, et c'est une décision documentée dans `agent/config.py` :

- les métriques n'ont pas la même échelle, donc aucun plancher unique n'a de
  sens ;
- surtout, **un MAD nul n'est pas un problème, c'est une information** : la
  métrique n'a jamais bougé. Si elle bouge aujourd'hui, aucun score n'est
  nécessaire pour le dire. Inventer une variabilité qui n'a pas été observée,
  c'est ce que la décision 10b interdit déjà à la mesure elle-même.

Ce cas produit donc un écart de type `rupture_de_constante`, rapporté par son
écart **brut** — pas par un z qui vaudrait l'infini.

## Démarrage à froid

En dessous de `HISTORIQUE_MIN_LOTS`, aucune détection. Une médiane sur trois
lots est un chiffre, pas une référence : elle signalerait des variations
parfaitement normales, et on apprendrait en une semaine à ignorer l'agent. Se
taire **en le disant** vaut mieux que crier sans fondement — c'est `profile` qui
journalise la taille de la référence.
"""

from statistics import median

from agent import config
from agent.detect import EXACTITUDE, STATISTIQUE, ecart

# Quelle dimension DAMA porte quelle métrique. Une dérive du taux de nulls est
# un défaut de **complétude**, un volume qui s'effondre aussi ; une borne
# numérique qui saute est un défaut d'**exactitude**. Sans cette table, tous les
# écarts statistiques porteraient la même étiquette et la phase 8 ne pourrait
# pas dire *quelle sorte* de qualité s'améliore.
DAMA_PAR_METRIQUE = {
    "row_count": "completude",
    "null_count": "completude",
    "null_rate": "completude",
    "distinct": "unicite",
    "coverage": "coherence",
    "numeric_rate": "validite",
}


def detecter(state: dict) -> list[dict]:
    """Les mesures du jour qui s'écartent de leur propre historique."""
    profil = state.get("profile") or {}
    historique = state.get("profile_history") or {}
    if not profil:
        return []

    ecarts = []
    for cle, valeur in _mesures_du_jour(profil):
        serie = historique.get(cle)
        # Le démarrage à froid se constate par série et non globalement : une
        # colonne apparue il y a trois jours n'a pas d'historique même si la
        # table en a trente. Comparer quand même reviendrait à juger une
        # nouveauté sur la foi de ses premiers instants.
        if not serie or len(serie) < config.HISTORIQUE_MIN_LOTS:
            continue

        constate = _comparer(cle, valeur, serie, state["table"])
        if constate is not None:
            ecarts.append(constate)
    return ecarts


def _mesures_du_jour(profil: dict):
    """`((colonne, métrique), valeur)` — `colonne` à None pour la table.

    Même clé que celle de `OPS._PROFILES` : c'est ce qui permet de retrouver la
    série sans traduction, donc sans endroit où les deux formats pourraient
    diverger.
    """
    if _nombre(profil.get("row_count")):
        yield (None, "row_count"), float(profil["row_count"])

    for colonne, stats in (profil.get("columns") or {}).items():
        for metrique, valeur in stats.items():
            if _nombre(valeur):
                yield (colonne, metrique), float(valeur)


def _nombre(valeur) -> bool:
    return isinstance(valeur, (int, float)) and not isinstance(valeur, bool)


def _comparer(cle, valeur: float, serie: list, table: str):
    colonne, metrique = cle
    mediane = median(serie)
    ecarts_absolus = [abs(v - mediane) for v in serie]
    mad = median(ecarts_absolus)

    dama = DAMA_PAR_METRIQUE.get(metrique, EXACTITUDE)

    if mad == 0:
        # Historique constant. Toute différence est un fait, et le rapporter
        # par un score z demanderait de diviser par zéro — c'est-à-dire
        # d'inventer la variabilité qui manque.
        if valeur == mediane:
            return None
        return ecart(
            STATISTIQUE,
            table,
            type="rupture_de_constante",
            dama=dama,
            colonne=colonne,
            observe=valeur,
            reference=mediane,
            metrique=metrique,
            ecart_brut=valeur - mediane,
            lots_de_reference=len(serie),
        )

    z = config.CONSTANTE_Z * (valeur - mediane) / mad
    if abs(z) <= config.SEUIL_Z:
        return None

    return ecart(
        STATISTIQUE,
        table,
        type="derive_statistique",
        dama=dama,
        colonne=colonne,
        observe=valeur,
        reference=mediane,
        metrique=metrique,
        z=round(z, 2),
        mad=mad,
        lots_de_reference=len(serie),
    )
