"""Les six écrans de l'agent (phase 6.1).

    uv run streamlit run streamlit/app.py

**Ce fichier ne contient que de l'affichage.** Tout ce qui se raisonne vit dans
`streamlit/donnees.py` et `agent/hitl.py`, et se teste donc sans navigateur —
même partage qu'entre le DAG Airflow et `scripts/check_layer.py`.

Une logique enfermée dans un `st.button()` n'est éprouvable qu'à la main, et un
écran de décision qu'on ne peut pas tester est un écran dont on ne sait pas s'il
montre la vérité.

## Les six écrans, et l'ordre dans lequel on les lit

    1. Dashboard BI          on VOIT le chiffre faux (le fan-out São Paulo)
    2. Validation HITL       on décide — c'est le poste de travail
    3. Incidents             ce que l'agent a fait, tout compris
    4. Décision              un incident déplié : faits, diagnostic, impact
    5. Signatures en silence ce qu'il ne dit PLUS — le garde-fou anti-cécité
    6. Contrats              ce qu'il tient pour vrai, et depuis quelle version

L'ordre n'est pas décoratif : c'est celui du fil rouge de la soutenance. On
montre le chiffre faux, on décide, on constate la trace, on déplie, puis on
montre ce que le système s'interdit d'oublier.
"""

import sys
from pathlib import Path

import streamlit as st

RACINE = Path(__file__).resolve().parent.parent
ICI = Path(__file__).resolve().parent
if str(ICI) not in sys.path:
    # Pour que `import donnees` fonctionne quel que soit le point d'entrée.
    sys.path.insert(0, str(ICI))
if str(RACINE) not in sys.path:
    # Streamlit exécute ce fichier comme un script : la racine du dépôt n'est
    # pas sur le chemin d'import, et `agent` serait introuvable.
    sys.path.insert(0, str(RACINE))

from agent.hitl import (  # noqa: E402
    CORRECTION_SANS_APPROBATION,
    proposition,
    questionner,
    trancher,
)
from agent.state import (  # noqa: E402
    DECISION_AMEND,
    DECISION_APPROVED,
    DECISION_REJECTED,
)

# ⚠️ `import donnees` et **non** `from streamlit import donnees` : ce dossier
# porte le nom du paquet installé, et le second résoudrait vers `site-packages`
# — ImportError à l'exécution, pas au chargement des tests. `streamlit run`
# place le dossier du script en tête de `sys.path`, donc l'import nu trouve bien
# le voisin.
import donnees  # noqa: E402

DATASET = "olist"

st.set_page_config(page_title="Agent qualité de données", page_icon="🔎", layout="wide")


def _erreur(exc: Exception) -> None:
    """Une panne s'affiche, elle n'efface pas l'écran.

    Sans ce garde-fou, une table absente ou un trial expiré ferait disparaître
    l'application entière derrière une trace — et l'humain qui devait décider
    perdrait aussi les écrans qui, eux, fonctionnaient.
    """
    st.error(f"{type(exc).__name__} : {exc}")
    st.caption("Les autres écrans restent utilisables.")


# ---------------------------------------------------------------------------


def dashboard_bi() -> None:
    st.header("📊 Dashboard BI")
    st.caption(
        "Les agrégats Gold, tels qu'un métier les lit. C'est ici qu'on **voit** "
        "le chiffre faux avant correction — et corrigé après."
    )
    try:
        marts = donnees.tables_gold(DATASET)
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    table = st.selectbox("Mart", marts)
    if not table:
        return
    try:
        resultat = donnees.agregat(DATASET, table)
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    st.dataframe(resultat["rows"], use_container_width=True)
    if resultat.get("truncated"):
        st.info("Affichage tronqué — ce qui manque n'est pas une erreur.")


def validation_hitl() -> None:
    st.header("✅ Validation")
    st.caption(
        "Les propositions en pause. Le clic passe par **la même voie** que "
        "`scripts/decide.py` — une seule façon de reprendre un run, donc une "
        "seule à tester."
    )
    try:
        attente = donnees.file_attente()
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    if not attente:
        st.success("Aucune proposition en attente.")
        return

    # L'impact d'abord : c'est ce qui permet de choisir **laquelle** traiter en
    # premier quand il y en a dix.
    choix = st.selectbox(
        "Proposition",
        [p["thread_id"] for p in attente],
        format_func=lambda t: next(
            f"{p['table']} · {p['batch_id']} — {p['resume'] or '?'}"
            for p in attente
            if p["thread_id"] == t
        ),
    )
    payload = proposition(choix)
    if payload is None:
        st.warning("Cette proposition vient d'être tranchée ailleurs.")
        return

    _afficher_proposition(payload)
    _boutons(choix)


def _afficher_proposition(payload: dict) -> None:
    impact = payload.get("impact") or {}
    st.subheader(payload.get("table", "?"))

    # ⭐ L'impact en tête, et en gros : sans lui l'humain ne juge pas, il signe.
    st.metric("Impact", impact.get("resume") or "non calculé")
    if impact.get("aval"):
        st.caption(f"Effet aval : {impact['aval']}")

    gauche, droite = st.columns(2)
    with gauche:
        st.markdown("**Ce qui a été constaté**")
        st.json(payload.get("anomalies") or [], expanded=False)
    with droite:
        st.markdown("**Ce que le modèle en dit**")
        st.write(payload.get("root_cause") or "—")
        st.code(payload.get("proposed_fix") or "— aucune correction proposée")

    if payload.get("alertes_p6"):
        # Montré **avant** la décision : `apply` refusera de toute façon, mais
        # découvrir le refus après avoir approuvé serait inutile — l'humain doit
        # pouvoir réécrire tout de suite, son autorité n'étant pas soumise à P6.
        st.warning(
            "Correction refusée par l'invariant P6 : "
            + " · ".join(payload["alertes_p6"])
        )
        st.caption(
            "Vous pouvez la réécrire : votre autorité n'est pas soumise à P6, "
            "celle de l'agent l'est."
        )

    with st.expander("Ce que l'agent a le droit de faire"):
        for geste, explication in (payload.get("gestes_autorises") or {}).items():
            st.markdown(f"- **{geste}** — {explication}")

    if payload.get("past_incidents"):
        with st.expander(f"{len(payload['past_incidents'])} antécédent(s)"):
            st.json(payload["past_incidents"])

    for echange in payload.get("conversation") or []:
        st.chat_message(echange["role"]).write(echange["message"])


def _boutons(thread_id: str) -> None:
    par = st.text_input("Votre nom (tracé dans INCIDENTS)", key="decideur")
    fix = st.text_area("Réécrire la correction (facultatif)", key="fix")

    a, b, c = st.columns(3)
    demandes = [
        (a, "✅ Approuver", DECISION_APPROVED),
        (b, "📝 Amender le contrat", DECISION_AMEND),
        (c, "❌ Refuser", DECISION_REJECTED),
    ]
    for colonne, libelle, decision in demandes:
        # ⚠️ Le bouton est **désactivé** plutôt que de laisser cliquer puis
        # refuser : une correction réécrite n'a de sens qu'avec une approbation,
        # et l'apprendre après coup n'apprend rien.
        interdit = bool(fix) and decision != DECISION_APPROVED
        if colonne.button(
            libelle, disabled=not par or interdit, use_container_width=True
        ):
            _trancher(thread_id, decision, par, fix)

    question = st.text_input("…ou poser une question avant de trancher")
    if st.button("💬 Demander", disabled=not question):
        reponse = questionner(thread_id, question, par or None)
        if reponse["ok"]:
            st.info(reponse["reponse"])
            st.caption(f"{reponse['questions_restantes']} question(s) restante(s)")
        else:
            st.error(reponse["erreur"])


def _trancher(thread_id: str, decision: str, par: str, fix: str) -> None:
    resultat = trancher(thread_id, decision, par=par or None, fix_override=fix or None)
    if not resultat["ok"]:
        st.error(resultat["erreur"])
        if resultat.get("code") == CORRECTION_SANS_APPROBATION:
            st.caption("Effacez la correction, ou choisissez « Approuver ».")
        return

    st.success(f"Décision {resultat['decision']!r} enregistrée.")
    st.caption("Parcours : " + " → ".join(resultat["parcours"]))
    if resultat["applied_fix"]:
        st.code(resultat["applied_fix"])
    if resultat["contract_version"]:
        st.caption(f"Contrat : version {resultat['contract_version']}")


def incidents() -> None:
    st.header("📋 Incidents")
    st.caption(
        "Le journal **complet** — y compris les runs sans anomalie et les refus. "
        "Les cacher donnerait un historique plus propre que la réalité."
    )
    couche = st.selectbox("Couche", ["(toutes)", "bronze", "silver", "gold"])
    try:
        lignes = donnees.journal(
            DATASET, couche=None if couche.startswith("(") else couche
        )
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    if not lignes:
        st.info("Aucun incident journalisé.")
        return
    st.dataframe(
        [donnees.resumer_incident(i) for i in lignes], use_container_width=True
    )
    st.session_state["incidents"] = lignes


def decision() -> None:
    st.header("🔍 Décision")
    st.caption(
        "Un incident déplié : les faits, le diagnostic, l'impact, les antécédents."
    )
    lignes = st.session_state.get("incidents")
    if not lignes:
        st.info("Ouvrez d'abord l'écran « Incidents ».")
        return

    choix = st.selectbox(
        "Incident",
        range(len(lignes)),
        format_func=lambda i: f"{lignes[i]['batch_id']} · {lignes[i]['table_name']}",
    )
    incident = lignes[choix]

    st.markdown("**Écarts constatés** — des faits, pas un jugement")
    st.json(incident.get("anomalies") or [], expanded=False)
    st.markdown("**Diagnostic du modèle** — une supposition, pas un verdict")
    st.json(incident.get("diagnosis") or {}, expanded=False)
    st.markdown(
        f"**Décision** : {donnees.statut(incident)}"
        + (f" · par {incident['decided_by']}" if incident.get("decided_by") else "")
    )


def signatures_en_silence() -> None:
    st.header("🔇 Signatures en silence")
    st.caption(
        "Tout ce que l'agent ne signale **plus**, et sur décision de qui. Sans "
        "cet écran, il deviendrait progressivement muet sans que personne s'en "
        "aperçoive — invisible **parce qu'**il ne dit plus rien."
    )
    try:
        lignes = donnees.silences(DATASET)
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    if not lignes:
        st.success("Aucune signature en silence : l'agent signale tout ce qu'il voit.")
        return

    st.dataframe(lignes, use_container_width=True)
    st.info(
        "Une signature porte un **ordre de grandeur** : un refus sur 30 % de "
        "nulls ne fait pas taire l'agent à 85 %. Il reparlera de lui-même si "
        "l'ampleur change d'échelle."
    )


def contrats() -> None:
    st.header("📜 Contrats")
    st.caption(
        "Ce que l'agent tient pour vrai. Un contrat `proposed` n'est **pas** "
        "appliqué : tant qu'il attend une signature, aucune de ses clauses ne "
        "gouverne la surveillance."
    )
    try:
        liste = donnees.contrats(DATASET)
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    if not liste:
        st.info("Aucun contrat — lancez `scripts/discover`.")
        return

    st.dataframe(
        [{k: v for k, v in c.items() if k != "path"} for c in liste],
        use_container_width=True,
    )
    choix = st.selectbox(
        "Ouvrir",
        range(len(liste)),
        format_func=lambda i: (
            f"{liste[i]['table']} v{liste[i]['version']} ({liste[i]['status']})"
        ),
    )
    try:
        st.json(donnees.contrat(liste[choix]["path"]))
    except Exception as exc:  # noqa: BLE001
        _erreur(exc)


ECRANS = {
    "📊 Dashboard BI": dashboard_bi,
    "✅ Validation": validation_hitl,
    "📋 Incidents": incidents,
    "🔍 Décision": decision,
    "🔇 Signatures en silence": signatures_en_silence,
    "📜 Contrats": contrats,
}


def main() -> None:
    st.sidebar.title("🔎 Agent qualité")
    st.sidebar.caption(f"dataset `{DATASET}`")
    ECRANS[st.sidebar.radio("Écran", list(ECRANS))]()


if __name__ == "__main__":
    main()
