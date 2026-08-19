"""Nœud `profile` — mesure le lot du jour et le range dans l'historique (4.3).

**Aucun nom de table ni de colonne n'apparaît ici** : tout vient du registre et
de l'état. C'est la condition pour que l'agent tourne sur n'importe quel dataset
(ADR 010, décision 2).

Ce qui est profilé : **le lot qui arrive**, pas la table entière. Profiler la
table entière diluerait l'anomalie — 30 % de nulls sur un jour ne pèsent plus
que 0,3 % noyés dans 92 jours cumulés. C'est l'exact inverse du cycle Découverte
(4.2.5), qui profile la table entière parce qu'il cherche ce qui est *normal* :
la dilution est l'ennemie de l'une et la condition de l'autre.

Le nœud fait trois choses, et l'ordre compte moins qu'il n'y paraît :

  1. **lire l'historique** des lots précédents (`OPS._PROFILES`) ;
  2. **mesurer** le lot du jour (`profile_table`) ;
  3. **ranger** cette mesure dans l'historique.

Le plan (§4.3) posait l'ordre comme impératif : lire avant d'écrire, sinon le
jour courant entre dans sa propre référence. L'ordre est respecté, mais ce n'est
**pas** lui qui porte la garantie — `lire_historique(avant=batch_id)` exclut le
lot courant dans le SQL. La nuance vaut d'être dite : l'ordre suffit au premier
passage et casse au rejeu, puisqu'un lot déjà profilé hier serait relu
aujourd'hui comme s'il était du passé. Airflow rejoue une tâche en cas d'échec,
donc ce cas n'est pas théorique.

Règle intangible, inchangée depuis la phase 3 : le profil ne contient **que des
agrégats**, jamais de lignes brutes (R2). C'est ce qui garantit que `diagnose`
ne verra jamais une donnée réelle — il raisonne sur des chiffres, pas sur des
clients.
"""

from agent import config
from agent.connectors import fermer, ouvrir
from agent.connectors import ops
from agent.contracts import loader
from agent.registry import charger as charger_registre
from agent.state import AgentState, log_entry
from agent.tools.profile_table import profile_table


def profile(state: AgentState) -> dict:
    dataset, table, lot = state["dataset"], state["table"], state["batch_id"]

    memoire = ops.MemoireOps()
    try:
        historique = memoire.lire_historique(
            dataset, table, avant=lot, jours=config.FENETRE_HISTORIQUE_LOTS
        )
        # Le dernier schéma connu **avant** ce lot : l'ingestion a déjà écrit
        # celui d'aujourd'hui, et comparer le lot à lui-même ne trouverait
        # jamais un renommage de colonne.
        schema_connu = memoire.lire_schema(table, avant=lot)
        contrat = loader.charger(dataset, table) or {}
        inventaire = _inventaire(dataset)
        # La mémoire (4.4) : seulement les incidents qu'un humain a tranchés
        # (R5, filtre porté par le SQL). Chargée ici plutôt que dans `detect`
        # pour la même raison que le reste — les cinq familles restent des
        # fonctions pures, donc rejouables à l'identique au benchmark.
        incidents = memoire.lire_incidents(dataset, table)

        fiche = profile_table.invoke(
            {"dataset": dataset, "table": table, "batch_id": lot}
        )

        # `None` = la table déclarée n'existe pas. On ne lève **pas** : c'est
        # une anomalie que la famille *inventaire* de `detect` doit constater,
        # et un agent qui plante sur une table absente disparaît au moment
        # précis où il servirait le plus. On range un profil vide et on le dit.
        if fiche is None:
            return {
                "profile": {},
                "profile_history": historique,
                "schema_history": schema_connu,
                "contract": contrat,
                "contract_version": contrat.get("version"),
                "inventory": inventaire,
                "past_incidents": incidents,
                "logs": [
                    log_entry(
                        "profile",
                        "table absente — rien à profiler",
                        table=table,
                        batch_id=lot,
                        lots_de_reference=_lots(historique),
                    )
                ],
            }

        ecrites = memoire.ecrire_profil(dataset, table, lot, fiche)

        return {
            "profile": fiche,
            "profile_history": historique,
            "schema_history": schema_connu,
            "contract": contrat,
            "contract_version": contrat.get("version"),
            "inventory": inventaire,
            "past_incidents": incidents,
            "logs": [
                log_entry(
                    "profile",
                    "profil calculé et archivé",
                    table=table,
                    batch_id=lot,
                    lignes=fiche.get("row_count"),
                    colonnes=len(fiche.get("columns", {})),
                    mesures_archivees=ecrites,
                    lots_de_reference=_lots(historique),
                )
            ],
        }
    finally:
        # Un run interrompu ne doit pas laisser une session Snowflake derrière
        # lui : le warehouse se suspend au bout de 60 s, la session non.
        memoire.close()


def _lots(historique: dict) -> int:
    """Combien de lots la référence contient — la longueur de la plus longue série.

    C'est ce chiffre que `detect` comparera à `HISTORIQUE_MIN_LOTS` pour décider
    s'il a le droit de comparer. Le journaliser dès `profile` rend lisible, dans
    `INCIDENTS`, *pourquoi* un run n'a rien détecté statistiquement — « 4 lots de
    référence » est une explication, « aucune anomalie » n'en est pas une.
    """
    return max((len(v) for v in historique.values()), default=0)


def _inventaire(dataset: str) -> dict:
    """Ce que la base contient, face à ce que le registre déclare.

    Le relevé des **schémas** est volontairement restreint aux tables présentes
    et *non déclarées* : ce sont les seules qu'on ne connaît pas, et les seules
    qui puissent porter le schéma d'une table disparue — donc étayer une
    hypothèse de renommage. Dans le cas normal il n'y en a aucune, et
    l'inventaire ne coûte qu'une requête.

    Relever le schéma de **toutes** les tables aurait coûté une requête par
    table à chaque run — dix-sept fois quatre-vingt-douze jours chez Olist, pour
    une information dont on n'a besoin qu'en cas d'anomalie.

    Une panne d'inventaire n'est pas une panne de profilage : on rend un
    inventaire vide et la famille *inventaire* se taira, plutôt que de conclure
    d'une liste absente que toutes les tables ont disparu.
    """
    registre = charger_registre(dataset)
    connecteur = ouvrir(registre.connector)
    try:
        presentes = list(connecteur.list_tables())
        declarees = [t.name for t in registre.tables]
        inconnues = sorted(set(presentes) - set(declarees))
        schemas = {
            nom: [c["name"] for c in (connecteur.get_schema(nom) or [])]
            for nom in inconnues
        }
        return {"present": presentes, "declared": declarees, "schemas": schemas}
    finally:
        fermer(connecteur)
