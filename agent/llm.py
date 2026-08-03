"""La frontière avec le LLM — le seul endroit du projet qui appelle un modèle.

Isolé dans son propre module pour trois raisons :

  - **Un seul point d'entrée réseau.** Si un jour un appel LLM apparaît ailleurs
    que derrière ce module, la règle R1 (« le LLM n'est appelé que dans
    `Diagnose` ») est cassée, et ça se voit d'un `grep`.
  - **Une seule couture à simuler.** Les tests remplacent `diagnostiquer()` et
    n'ont jamais besoin de clé API : la CI reste déterministe et gratuite.
  - **Un seul endroit à changer.** Passer de Groq à Snowflake Cortex (l'option
    « zéro fuite » de l'ADR) ne touchera ni les nœuds ni le graphe.

**Ce que le modèle voit** : des agrégats et des métadonnées, jamais de lignes
brutes (règle R2). C'est `construire_contexte()`, dans le nœud `diagnose`, qui
en répond — ce module ne fait que transmettre ce qu'on lui donne.

**Sortie structurée** : on combine deux mécanismes plutôt qu'un.

  1. `response_format={"type": "json_object"}` — l'API **contraint** le modèle à
     produire du JSON syntaxiquement valide. Plus fiable que demander poliment
     dans le prompt et espérer.
  2. Validation Pydantic — le JSON valide n'est pas forcément le *bon* JSON. Un
     modèle peut renvoyer `{"cause": …}` au lieu de `{"root_cause": …}`, ou
     omettre un champ. C'est cette seconde barrière qui l'attrape.

Le PROGRESS mentionnait `PydanticOutputParser` (LangChain). On s'en écarte
volontairement : cet outil injecte des consignes de format dans le prompt puis
parse la réponse, là où le mode JSON natif de Groq empêche le format invalide
d'exister. Le résultat est plus court et plus sûr ; la validation Pydantic, elle,
est conservée.
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

# Validé en phase 0.2 (`scripts/check_access.py`) — modèle gratuit chez Groq.
MODELE = "llama-3.3-70b-versatile"

# Le LLM n'a pas à être créatif : on veut un diagnostic reproductible, pas une
# variation à chaque appel. La phase 8 mesurera quand même chaque métrique
# plusieurs fois, parce que 0 ne garantit pas le déterminisme.
TEMPERATURE = 0.0

TIMEOUT_S = 30

RACINE = Path(__file__).resolve().parent.parent


class Diagnostic(BaseModel):
    """La forme imposée à la réponse du modèle.

    Trois champs, pas un de plus. Le LLM explique — il ne décide pas, ne chiffre
    pas de seuil, ne classe pas par gravité. Tout ce qui ressemblerait à une
    décision appartient à l'humain, et tout ce qui ressemblerait à une mesure
    appartient à `detect`.
    """

    root_cause: str = Field(description="La cause probable, en une ou deux phrases")
    proposed_fix: str = Field(
        description="L'action proposée — jamais une valeur devinée"
    )
    explanation: str = Field(description="Pourquoi cette cause plutôt qu'une autre")


CONSIGNES = """Tu es un expert en qualité de données. On te donne le résumé \
chiffré d'un lot de données et les écarts constatés par un système de détection \
déterministe.

Ton rôle est d'expliquer POURQUOI ces écarts sont apparus, et de proposer une \
action. Tu ne mesures rien : les chiffres qu'on te donne sont établis, ne les \
recalcule pas et ne les remets pas en cause.

RÈGLE ABSOLUE — tu ne dois JAMAIS proposer de remplacer une valeur par une autre \
valeur que tu aurais devinée. Face à une valeur aberrante, tu ne peux pas savoir \
si c'est une erreur de saisie, un problème d'unité ou un cas réel. Proposer une \
substitution reviendrait à fabriquer de la donnée qui n'a jamais existé.

Actions autorisées : isoler les lignes concernées en quarantaine, les mettre à \
NULL en les marquant, les exclure d'un agrégat, alerter l'équipe amont, corriger \
la transformation fautive.
Action interdite : « remplacer X par Y ».

Réponds en français, en JSON strict, avec exactement ces trois clés :
  "root_cause"   : la cause probable, une ou deux phrases
  "proposed_fix" : l'action proposée, concrète
  "explanation"  : pourquoi cette cause plutôt qu'une autre"""


def _client():
    """Le client Groq, construit à l'appel.

    `load_dotenv` est fait ici plutôt qu'à l'import : un import ne doit pas avoir
    d'effet de bord, et surtout les tests importent ce module sans jamais avoir
    de clé API.
    """
    from dotenv import load_dotenv
    from groq import Groq

    load_dotenv(RACINE / ".env")
    return Groq(api_key=os.environ["GROQ_API_KEY"], timeout=TIMEOUT_S)


def diagnostiquer(contexte: dict) -> Diagnostic:
    """Demande un diagnostic au modèle. **Lève** si quoi que ce soit échoue.

    Ne rattrape rien volontairement : réseau coupé, clé absente, quota dépassé,
    JSON mal formé, champ manquant — c'est l'appelant (`diagnose`) qui décide
    quoi faire d'un échec, et il en fait toujours la même chose : `diagnosis`
    reste à None et le run continue. Mettre la décision ici la disperserait.
    """
    reponse = _client().chat.completions.create(
        model=MODELE,
        temperature=TEMPERATURE,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": CONSIGNES},
            {
                "role": "user",
                "content": json.dumps(contexte, ensure_ascii=False, indent=2),
            },
        ],
    )
    return Diagnostic.model_validate_json(reponse.choices[0].message.content)


CONSIGNES_REPONSE = """Tu es un expert en qualité de données. Tu as déjà rendu un \
diagnostic sur un lot de données, et la personne qui doit décider te pose une \
question avant de trancher.

Réponds à sa question, en français, en quelques phrases. Sois direct et concret.

Trois limites à respecter :
- Tu ne disposes que des informations qu'on te donne. Si la question demande une \
donnée que tu n'as pas, dis-le franchement au lieu d'inventer un chiffre.
- Tu ne décides pas à sa place. Tu éclaires, elle tranche.
- La règle absolue tient toujours : ne propose JAMAIS de remplacer une valeur par \
une valeur devinée."""


def repondre(contexte: dict, conversation: list, question: str) -> str:
    """Répond à une question de l'humain avant qu'il tranche. **Lève** en cas d'échec.

    Deuxième et dernier usage du modèle dans tout le projet — et il reste appelé
    depuis le **même nœud** (`diagnose`), ce qui préserve la règle R1 : un seul
    endroit parle au LLM, donc un seul endroit à auditer et à simuler.

    Sortie en **texte libre**, contrairement à `diagnostiquer()` : une réponse à
    une question n'a pas de forme imposable. Le risque de format y est nul —
    personne ne route le graphe sur ce texte, il est seulement affiché à l'humain
    et journalisé.
    """
    historique = [
        {
            "role": "assistant" if e["role"] == "agent" else "user",
            "content": e["message"],
        }
        for e in conversation
    ]
    reponse = _client().chat.completions.create(
        model=MODELE,
        temperature=TEMPERATURE,
        messages=[
            {"role": "system", "content": CONSIGNES_REPONSE},
            {
                "role": "user",
                "content": json.dumps(contexte, ensure_ascii=False, indent=2),
            },
            *historique,
            {"role": "user", "content": question},
        ],
    )
    return reponse.choices[0].message.content.strip()
