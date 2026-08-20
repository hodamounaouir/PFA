"""Tool `run_sql` — lecture seule, tracée (phase 4.1.6, §5.6 du cahier).

Une échappatoire d'investigation : quand les cinq familles ont signalé un écart
et qu'un humain veut *voir*, il faut pouvoir interroger la base sans ouvrir un
terminal Snowflake à côté du projet — car ce terminal-là, lui, n'est ni bridé ni
journalisé.

## Qui l'appelle, et qui ne l'appelle pas

⚠️ **Pas le modèle.** L'ADR 004 exclut `bind_tools` : le LLM ne choisit jamais
un outil, il ne fait que diagnostiquer ce qu'on lui montre. `run_sql` est donc
appelé par un humain — depuis un terminal aujourd'hui, depuis l'écran de
décision en phase 6. C'est ce qui rend la journalisation utile : elle trace ce
qu'une *personne* a regardé pour trancher.

## Le premier brouillon du garde-fou d'`Apply`

C'est le rôle que PROGRESS lui donne, et il est tenu littéralement : le contrôle
vit dans `agent/sql_guard.py`, que la règle R4 d'`apply` réutilisera en phase 5.
Une règle écrite deux fois finit par diverger, et le jour où elle diverge, c'est
la version la plus laxiste qui gagne.

## ⚠️ Le seul endroit du projet qui rend des LIGNES BRUTES

Tout le reste de l'agent ne manipule que des agrégats — c'est la garantie R2, et
c'est ce qui permet de dire que le modèle ne voit jamais un client. Ce tool y
fait exception, par nécessité : investiguer, c'est regarder des lignes.

D'où une règle absolue, et un test qui l'impose : **le résultat de `run_sql`
n'entre jamais dans le contexte du LLM**. Il va à l'écran d'un humain, jamais
dans un prompt. `construire_contexte()` énumère champ par champ ce qui part au
modèle et ne lit pas cette sortie ; c'est ce qui rend la règle vérifiable plutôt
que promise.
"""

from typing import Optional

from langchain_core.tools import tool

from agent.connectors import fermer, ouvrir
from agent.registry import charger as charger_registre
from agent.sql_guard import lecture_seule

# Combien de lignes on ramène au maximum. Ce n'est pas une optimisation : c'est
# la borne qui empêche une investigation de devenir une extraction. Cent lignes
# suffisent à comprendre une anomalie ; au-delà, ce n'est plus regarder, c'est
# copier.
LIGNES_MAX = 100


class RequeteRefusee(Exception):
    """La requête n'est pas en lecture seule. Bruyant, jamais silencieux."""


def executer(dataset: str, sql: str, limite: int = LIGNES_MAX) -> dict:
    """Le corps du tool. **Refuse avant d'ouvrir quoi que ce soit.**

    L'ordre compte : on valide, *puis* on se connecte. Contrôler après avoir
    ouvert la session laisserait une trace de connexion pour une requête qu'on
    n'avait pas le droit de poser — et, le jour où le contrôle a un trou, la
    requête serait déjà partie.
    """
    refus = lecture_seule(sql)
    if refus:
        raise RequeteRefusee(
            "Requête refusée (lecture seule) :\n  - " + "\n  - ".join(refus)
        )

    registre = charger_registre(dataset)
    connecteur = ouvrir(registre.connector)
    try:
        resultat = connecteur.executer(sql, limite)
    finally:
        # Un run interrompu ne doit pas laisser une session ouverte derrière lui.
        fermer(connecteur)

    resultat["sql"] = sql
    return resultat


@tool
def run_sql(dataset: str, sql: str) -> dict:
    """Exécute une requête **en lecture seule** et rend ses lignes.

    `dataset` est le nom d'un registre (`datasets/<dataset>.yaml`), qui désigne
    le connecteur à ouvrir. Toute requête qui pourrait modifier quoi que ce soit
    est **refusée** — liste blanche de verbes, liste noire de mots-clés, et une
    seule instruction à la fois.

    Rend `{"columns", "rows", "truncated", "sql"}`. `truncated` à `True` signale
    que la réponse a été coupée : ce qui manque n'est pas une erreur, mais le
    lecteur doit savoir qu'il ne voit pas tout.
    """
    return executer(dataset, sql)


def resume(resultat: Optional[dict]) -> str:
    """Une ligne de journal — ce qui a été demandé, pas ce qui est revenu.

    On trace la **requête** et le **volume**, jamais les valeurs : le journal
    d'investigation ne doit pas devenir une copie de la base par accumulation.
    """
    if not resultat:
        return "run_sql : aucune requête"
    coupe = " (tronqué)" if resultat.get("truncated") else ""
    return (
        f"run_sql : {len(resultat.get('rows') or [])} ligne(s){coupe} · "
        f"{' '.join((resultat.get('sql') or '').split())[:160]}"
    )
