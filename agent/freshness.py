"""La fraîcheur d'une colonne temporelle (phase 4.1.4).

⭐ **Aucune requête.** Le critère de 4.1.5 avait déjà tranché : une colonne
`temporal` ne reçoit aucune mesure dédiée parce que *les `min`/`max` du profil
**sont** déjà la fraîcheur*. Cette étape n'ajoute donc pas une lecture de plus,
elle ajoute **l'interprétation** de ce qu'on a déjà mesuré — et c'est ce qui la
rend gratuite là où `top_values` et `robust_stats` coûtent une requête par
colonne.

## La référence est le lot, pas l'horloge

Comparer à `now()` n'aurait aucun sens ici : le dataset est rejoué, ses dates
sont de 2018, et tout paraîtrait vieux de sept ans. La question utile est
autre — *ce lot contient-il ce qu'il prétend contenir ?* La référence est donc
le **`batch_id`**, c'est-à-dire le jour que le lot déclare couvrir.

Cette bascule a un effet secondaire heureux : la mesure devient reproductible.
Rejouer le J45 deux ans plus tard rendra exactement le même retard, ce qui est
indispensable au benchmark (phase 8) — une fraîcheur mesurée à l'horloge aurait
changé à chaque exécution.

## Trois faits, tous tirés de deux bornes

    retard_jours     de combien le plus récent est en retard sur le lot
    amplitude_jours  l'étendue couverte — un lot d'un jour qui en couvre 90
                     n'est pas un lot, c'est un rechargement
    dates_futures    1 si le lot contient des dates postérieures à lui-même

Le dernier ne dit **pas combien** : `max` seul ne le permet pas, et le compter
demanderait la requête qu'on refuse de payer. Mais savoir qu'il en existe suffit
à alerter, et c'est un fait exact plutôt qu'une estimation.

## Ce qui n'est pas ici, et pourquoi

Les **trous** (un jour sans donnée) ne se voient pas dans un lot : ils se voient
d'un lot à l'autre. C'est une comparaison à un historique, donc le travail de la
famille statistique — qui les attrapera d'elle-même, puisque ces trois mesures
rejoignent `OPS._PROFILES` comme les autres.
"""

import datetime
from typing import Optional

from agent.characterize import lisible_comme_date

# Ce qu'on sait lire comme un instant. On ne garde que la partie date : un
# horodatage à la seconde près donnerait un « retard » de 0,3 jour qui n'aiderait
# personne à décider, et le lot, lui, n'a qu'une granularité journalière.
FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


def _jour(valeur) -> Optional[datetime.date]:
    """La date d'une valeur, ou `None` si ce n'en est pas une.

    Accepte le texte **et** le typé : en Bronze tout est VARCHAR, en Silver la
    colonne arrive déjà en `DATE`. C'est le même écart que `lisible_comme_date`
    absorbe pour le classement — ici on va plus loin, on veut la valeur.
    """
    if isinstance(valeur, datetime.datetime):
        return valeur.date()
    if isinstance(valeur, datetime.date):
        return valeur
    if not lisible_comme_date(valeur):
        return None

    texte = str(valeur).strip()
    for forme in FORMATS:
        try:
            return datetime.datetime.strptime(
                texte[: len(forme.replace("%Y", "0000"))], forme
            ).date()
        except ValueError:
            continue
    # Dernier recours : les dix premiers caractères d'un ISO sont toujours la
    # date, quelle que soit la précision qui suit.
    try:
        return datetime.date.fromisoformat(texte[:10])
    except ValueError:
        return None


def fraicheur(stats: dict, batch_id: Optional[str]) -> dict:
    """Les faits de fraîcheur d'une colonne, à partir de ses seules bornes.

    Rend un dictionnaire vide si les bornes ne se lisent pas comme des dates :
    ne rien dire vaut mieux que rendre un retard calculé sur `"N/A"`. C'est la
    même symétrie que partout — on constate ce qu'on a mesuré, on n'extrapole
    pas.
    """
    debut, fin = _jour(stats.get("min")), _jour(stats.get("max"))
    if debut is None or fin is None:
        return {}

    faits = {"amplitude_jours": (fin - debut).days}

    lot = _jour(batch_id)
    if lot is not None:
        faits["retard_jours"] = (lot - fin).days
        # ⚠️ Un fait, pas un décompte : `max` dit qu'il existe des dates
        # postérieures au lot, il ne dit pas combien. Les compter demanderait la
        # requête que cette étape existe pour éviter — et « il y en a » suffit à
        # alerter, tout en restant exact.
        faits["dates_futures"] = 1 if fin > lot else 0

    return faits
