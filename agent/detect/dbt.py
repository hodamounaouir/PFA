"""Famille *dbt* — les verdicts d'un autre outil, dans la forme commune (4.5).

⚠️ **Ce n'est pas un détecteur.** Les quatre autres familles constatent un écart
en comparant le lot à une référence ; celle-ci ne constate rien du tout — elle
**traduit**. Les échecs de `dbt test` sont des anomalies déjà confirmées, par un
outil déterministe, avant que l'agent ne tourne.

Pourquoi les faire entrer quand même : parce que tout ce que l'agent sait faire
ensuite s'applique. Un test `not_null` qui casse au J60 gagne alors un
diagnostic, une signature, une place dans `INCIDENTS`, et la mémoire qui fera
citer le J60 au J85. Les laisser dehors reviendrait à réserver l'intelligence de
l'agent aux anomalies qu'il a trouvées lui-même.

Et c'est aussi ce qui referme la boucle de 4.1.8 : l'agent **génère** des règles
dbt, dbt les exécute, et leurs échecs **reviennent** à l'agent. Ce qu'il a appris
une fois le protège ensuite sans lui.

Aucune entrée-sortie ici non plus : les échecs sont dans l'état, lus par
`scripts/check_layer.py` au moment où le DAG appelle l'agent.
"""

from agent.detect import DBT, ecart


def detecter(state: dict) -> list[dict]:
    """Les échecs dbt du run, convertis en écarts."""
    echecs = state.get("dbt_failures") or []
    table = state["table"]

    ecarts = []
    for echec in echecs:
        # Un échec qui porte sur une autre table n'a rien à faire dans ce run :
        # l'agent est invoqué table par table, et mélanger les verdicts ferait
        # signaler à `RAW.ORDERS` une anomalie de `STG_PRODUCTS`.
        if echec.get("table") and echec["table"] != table:
            continue

        lignes = echec.get("failures")
        ecarts.append(
            ecart(
                DBT,
                table,
                type="test_dbt_echoue",
                dama=echec.get("dama") or "exactitude",
                colonne=echec.get("colonne"),
                observe=lignes,
                reference=0,
                # Le nombre de lignes fautives : c'est l'ampleur que dbt mesure,
                # et la seule dont il dispose.
                ampleur=lignes if isinstance(lignes, (int, float)) else None,
                test=echec.get("test"),
                sorte=echec.get("sorte"),
                statut=echec.get("statut"),
            )
        )
    return ecarts
