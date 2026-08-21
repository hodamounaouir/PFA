"""Signer un contrat — la voie **unique** (phase 6.2).

Deux interfaces valident un contrat : `scripts/discover.py --approve` et l'écran
« Contrats » de Streamlit. Elles passent par **le même code**, pour la même
raison que la reprise d'un run passe par `agent/hitl.py` : une seconde voie
serait une seconde façon de contourner le garde-fou.

Ici, le garde-fou est `accepter_avertissements`. La découverte **critique** ses
propres propositions (décision 13a) ; signer un contrat qu'elle a critiqué est
une **décision**, pas une formalité. Un bouton qui validerait sans le demander
rendrait toute cette critique décorative.

## Ce que la fonction refuse, et pourquoi

    aucun contrat sur disque    → il n'y a rien à signer
    des avertissements non lus  → la critique doit être vue, pas contournée
    un contrat déjà en vigueur  → refusé par `ecrire()`, pas ici

Le dernier point est volontaire : c'est `ecrire()` qui touche au disque, donc
c'est lui qui protège le travail d'un humain. Une première version de
`discover.approuver()` refaisait le contrôle en tête ; un sabotage l'a retiré
sans qu'aucun test ne rougisse — le contrôle en double ne portait rien et
donnait l'illusion d'une garantie qui vit ailleurs.
"""

from agent.contracts.loader import CONTRACTS_DIR, ContratInvalide, _lire, ecrire, lister
from agent.contracts.proposer import APPROUVE


def approuver(
    dataset: str,
    table: str,
    par: str,
    accepter_avertissements: bool = False,
    dossier=CONTRACTS_DIR,
) -> dict:
    """Fait passer un contrat de `proposed` à `approved`. **Relu depuis le disque.**

    Relu, et non repris d'une mémoire quelconque : c'est le fichier que l'humain
    a sous les yeux — et qu'il a peut-être corrigé à la main — qui fait foi.
    Prendre une autre copie effacerait ses corrections, ce qui est exactement ce
    que l'étape sert à produire.

    `par` est **obligatoire** : un contrat sans signataire ne prouve rien six
    mois plus tard, et c'est la même traçabilité que `decided_by` dans le cycle
    de surveillance.
    """
    if not (par or "").strip():
        raise ContratInvalide("Un contrat doit être signé : indiquez qui valide.")

    en_attente = [c for c in lister(dataset, dossier) if c["table"] == table]
    if not en_attente:
        raise ContratInvalide(f"Aucun contrat sur disque pour {table!r} ({dataset})")

    # La **dernière** version : une v2 en discussion se signe, pendant que la v1
    # validée continue de gouverner la surveillance jusqu'à ce qu'elle le soit.
    dernier = max(en_attente, key=lambda c: c["version"])
    contrat = _lire(dernier["path"])

    if contrat["warnings"] and not accepter_avertissements:
        raise ContratInvalide(
            f"{len(contrat['warnings'])} avertissement(s) — relisez-les puis "
            f"confirmez explicitement."
        )

    contrat["status"] = APPROUVE
    contrat["approved_by"] = par
    ecrire(contrat, dataset, dossier)
    return contrat
