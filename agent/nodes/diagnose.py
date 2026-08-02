"""Nœud `diagnose` — le seul nœud qui appellera le LLM (stub, phase 3.1).

Répartition des rôles, à ne jamais brouiller :

    detect    (code)  →  QUOI      « telle colonne : 30,1 % de nulls, seuil 10 % »
    diagnose  (LLM)   →  POURQUOI  « probable échec du job amont »

Si le LLM faisait la détection, elle cesserait d'être reproductible et le
benchmark de la phase 8 n'aurait plus de sens. Il reçoit des **agrégats**, jamais
des lignes : il raisonne sur des chiffres, pas sur des clients.

Réel à l'étape 7 (appel Groq + sortie forcée par Pydantic), puis enrichi en
phase 4.4 : le prompt recevra aussi `past_incidents` — la mémoire, qui permet
de citer un incident identique déjà tranché (objectif O7).

Deux garde-fous que ce nœud doit respecter dès maintenant :

  - **Ne jamais inventer une valeur.** Face à une valeur hors bornes, l'agent ne
    peut pas savoir si `8000` vaut `80,00` ou vraiment `8000`. Proposer une
    substitution, c'est fabriquer de la donnée. Il propose donc d'**isoler**,
    de **mettre à NULL** ou d'**exclure d'un agrégat** — jamais de deviner.
    (La barrière dure est dans `apply`, phase 5.2 ; ici c'est la ligne éditoriale.)
  - **Un échec ne tue pas le run.** Si la sortie du LLM n'est pas parsable,
    `diagnosis` reste à None et le run se termine en « à traiter manuellement ».
"""

from agent.state import AgentState, log_entry


def diagnose(state: AgentState) -> dict:
    anomalies = state["anomalies"]

    # Le graphe ne route pas ici sans écart, mais un nœud ne doit jamais
    # supposer d'où il vient. C'est aussi la forme qu'aura l'échec de parsing
    # à l'étape 7 : diagnosis = None, et le run se termine proprement.
    if not anomalies:
        return {
            "diagnosis": None,
            "logs": [log_entry("diagnose", "aucun écart à diagnostiquer")],
        }

    # Le stub ne raisonne que sur le premier écart. Le LLM réel, lui, les verra
    # tous d'un coup — c'est même l'intérêt : relier deux écarts entre eux
    # (« le pic de nulls en Silver vient du renommage en Bronze »).
    principal = anomalies[0]
    colonne = principal.get("colonne", "?")

    return {
        "diagnosis": {
            "root_cause": (
                f"Écart de {principal.get('type', '?')} sur « {colonne} » "
                f"({principal.get('observe')} contre {principal.get('reference')} "
                f"en référence) : cause amont probable."
            ),
            # isoler, pas deviner
            "proposed_fix": (
                f"Isoler en quarantaine les lignes de {principal.get('table')} "
                f"dont « {colonne} » s'écarte, sans modifier les valeurs existantes."
            ),
            "explanation": (
                "Un écart aussi net et aussi partiel évoque un incident technique "
                "en amont plutôt qu'un changement métier délibéré."
            ),
        },
        "logs": [
            log_entry(
                "diagnose",
                "diagnostic produit (stub, sans LLM)",
                anomalies=len(anomalies),
                colonne=colonne,
            )
        ],
    }
