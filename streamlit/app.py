"""Le poste de travail de l'agent qualité (phases 6.1 et 6.2).

    uv run streamlit run streamlit/app.py

**Ce fichier ne contient que de l'affichage.** Tout ce qui se raisonne vit dans
`streamlit/donnees.py`, `agent/hitl.py` et `agent/contracts/validation.py` — et
se teste donc sans navigateur. Une logique enfermée dans un `st.button()` n'est
éprouvable qu'à la main, et *un écran de décision qu'on ne peut pas tester est
un écran dont on ne sait pas s'il montre la vérité*.

## ⭐ Écrit pour quelqu'un qui connaît le métier, pas le projet

La personne qui décide sait si les ventes par ville sont justes. Elle ne sait
pas ce qu'est « un écart de famille sémantique d'octave −2 », et elle n'a pas à
l'apprendre pour trancher. Tout le vocabulaire interne est donc traduit dans
`donnees.py` — à un seul endroit, donc corrigeable d'un seul geste.

Trois questions, dans cet ordre, et un écran pour chacune :

    Où en est-on ?      🏠 Accueil — quatre chiffres et ce qui vous attend
    Que dois-je faire ? ✅ Décisions · 📜 Contrats — la zone d'action
    Que s'est-il passé ? 📊 Données · 📚 Historique · 🔕 Alertes désactivées
"""

import sys
from pathlib import Path

import streamlit as st

RACINE = Path(__file__).resolve().parent.parent
ICI = Path(__file__).resolve().parent
for chemin in (str(ICI), str(RACINE)):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

# ⚠️ `import donnees` et **non** `from streamlit import donnees` : ce dossier
# porte le nom du paquet installé, et le second résoudrait vers `site-packages`
# — ImportError à l'ouverture de l'application, pas au chargement des tests.
import donnees  # noqa: E402

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

DATASET = "olist"

st.set_page_config(page_title="Qualité des données", page_icon="🔎", layout="wide")


def _erreur(exc: Exception) -> None:
    """Une panne s'affiche, elle n'efface pas l'écran.

    Sans ce garde-fou, une table absente ou un accès expiré ferait disparaître
    l'application entière derrière une trace — et la personne qui devait décider
    perdrait aussi les écrans qui, eux, fonctionnaient.
    """
    st.error(f"Source indisponible — {type(exc).__name__} : {exc}")
    st.caption("Les autres écrans restent utilisables.")


# ===========================================================================
# 🏠 Accueil
# ===========================================================================


def accueil() -> None:
    st.title("🔎 Qualité des données")
    st.caption(
        "Un agent surveille vos tables à chaque livraison. Il ne corrige jamais "
        "rien tout seul : il constate, il explique, **vous décidez**."
    )

    etat = donnees.vue_ensemble(DATASET)

    a, b, c, d = st.columns(4)
    a.metric("Tables surveillées", etat["tables"])
    b.metric(
        "Règles en vigueur",
        etat["contrats_en_vigueur"],
        delta=f"{etat['contrats_a_signer']} à signer"
        if etat["contrats_a_signer"]
        else None,
        delta_color="off",
    )
    c.metric("Décisions en attente", etat["decisions_en_attente"])
    d.metric(
        "Contrôles effectués",
        etat["runs"],
        delta=f"{etat['runs_avec_ecart']} avec anomalie"
        if etat["runs_avec_ecart"]
        else None,
        delta_color="off",
    )

    st.divider()

    # ⭐ « Ce qui vous attend » plutôt qu'un tableau de bord contemplatif :
    # l'écran d'accueil doit répondre à *que dois-je faire ?*, pas seulement à
    # *comment ça va ?*.
    st.subheader("Ce qui vous attend")
    if not etat["a_faire"]:
        st.success(
            "Rien à décider pour le moment. L'agent continue de surveiller à "
            "chaque livraison."
        )
    else:
        if etat["decisions_en_attente"]:
            st.warning(
                f"**{etat['decisions_en_attente']} anomalie(s)** attendent votre "
                f"décision → onglet **Décisions**"
            )
            for p in etat["attente"][:5]:
                st.markdown(
                    f"- `{p['table']}` · lot {p['batch_id']} — {p['resume'] or ''}"
                )
        if etat["contrats_a_signer"]:
            st.info(
                f"**{etat['contrats_a_signer']} règle(s)** proposées par l'agent "
                f"attendent votre relecture → onglet **Contrats**"
            )

    if etat["erreurs"]:
        st.divider()
        st.caption("Sources indisponibles : " + " · ".join(etat["erreurs"]))


# ===========================================================================
# ✅ Décisions
# ===========================================================================


def decisions() -> None:
    st.header("✅ Décisions")
    st.caption(
        "L'agent a trouvé quelque chose et s'est arrêté. Il attend votre "
        "réponse avant de toucher à quoi que ce soit."
    )
    try:
        attente = donnees.file_attente()
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    if not attente:
        st.success("Aucune décision en attente.")
        return

    choix = st.selectbox(
        "Anomalie à traiter",
        [p["thread_id"] for p in attente],
        format_func=lambda t: next(
            f"{p['table']} · {p['batch_id']} — {p['resume'] or '?'}"
            for p in attente
            if p["thread_id"] == t
        ),
    )
    payload = proposition(choix)
    if payload is None:
        st.warning("Cette anomalie vient d'être traitée ailleurs.")
        return

    _presenter(payload)
    _repondre(choix)


def _presenter(payload: dict) -> None:
    impact = payload.get("impact") or {}
    st.subheader(
        f"{payload.get('table', '?')} · livraison du {payload.get('batch_id')}"
    )

    # ⭐ L'impact en tête, et en gros : sans lui, on n'approuve pas — on signe.
    st.metric(
        "Combien de données sont concernées", impact.get("resume") or "non calculé"
    )
    if impact.get("aval"):
        st.caption(f"Effet sur les tableaux de bord : {impact['aval']}")

    st.markdown("**Ce que l'agent a constaté** — des faits, pas un jugement")
    for anomalie in payload.get("anomalies") or []:
        st.markdown(f"- {donnees.anomalie_lisible(anomalie)}")

    st.markdown("**Ce qu'il en pense** — une hypothèse, pas un verdict")
    st.info(payload.get("root_cause") or "aucune explication disponible")
    if payload.get("proposed_fix"):
        with st.expander("La correction qu'il propose (SQL)"):
            st.code(payload["proposed_fix"], language="sql")

    if payload.get("alertes_p6"):
        # Montré **avant** la décision : la correction sera refusée de toute
        # façon, mais l'apprendre après avoir approuvé serait inutile.
        st.error(
            "L'agent a proposé d'inventer une valeur — refusé. "
            + " · ".join(payload["alertes_p6"])
        )
        st.caption(
            "Vous pouvez écrire la correction vous-même : vous savez ce que la "
            "valeur aurait dû être, l'agent ne peut pas le savoir."
        )

    with st.expander("Ce que l'agent a le droit de faire"):
        st.caption(
            "Il ne remplace **jamais** une valeur par une valeur devinée. "
            "Face à 8000 dans une colonne à [1–100], il ne peut pas savoir s'il "
            "s'agit de 80,00 € en centimes, d'une faute de frappe ou d'une vraie "
            "grosse commande."
        )
        for geste, explication in (payload.get("gestes_autorises") or {}).items():
            st.markdown(f"- **{geste.replace('_', ' ')}** — {explication}")

    if payload.get("past_incidents"):
        with st.expander(f"Déjà vu {len(payload['past_incidents'])} fois"):
            for passe in payload["past_incidents"]:
                st.markdown(
                    f"- livraison du {passe.get('lot')} — {passe.get('decision_humaine')}"
                    f" par {passe.get('decide_par') or '?'}"
                )

    for echange in payload.get("conversation") or []:
        st.chat_message(echange["role"]).write(echange["message"])


def _repondre(thread_id: str) -> None:
    st.divider()
    par = st.text_input("Votre nom", key="decideur", placeholder="obligatoire")
    fix = st.text_area(
        "Écrire la correction moi-même (facultatif)",
        key="fix",
        placeholder="UPDATE …",
    )

    a, b, c = st.columns(3)
    for colonne, libelle, aide, decision in [
        (a, "✅ Corriger", "la donnée est fausse", DECISION_APPROVED),
        (b, "📝 Ajuster la règle", "la donnée est juste", DECISION_AMEND),
        (c, "❌ Écarter", "cas isolé, ne rien faire", DECISION_REJECTED),
    ]:
        # ⚠️ Désactivé plutôt que refusé après coup : apprendre un refus après
        # avoir cliqué n'apprend rien. Une correction réécrite n'a de sens
        # qu'avec « Corriger » — les deux autres n'écrivent rien dans les données.
        interdit = bool(fix) and decision != DECISION_APPROVED
        if colonne.button(
            libelle, help=aide, disabled=not par or interdit, width="stretch"
        ):
            _trancher(thread_id, decision, par, fix)

    question = st.text_input("…ou poser une question avant de décider")
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
            st.caption("Effacez la correction, ou choisissez « Corriger ».")
        return

    st.success("Décision enregistrée.")
    if resultat["applied_fix"]:
        st.caption("Correction appliquée :")
        st.code(resultat["applied_fix"], language="sql")
    if resultat["contract_version"]:
        st.caption(f"Règle ajustée — version {resultat['contract_version']}")


# ===========================================================================
# 📜 Contrats — consultation ET validation
# ===========================================================================


def contrats() -> None:
    st.header("📜 Règles de qualité")
    st.caption(
        "Ce que l'agent tient pour vrai sur vos données. Une règle **proposée** "
        "n'est pas appliquée : tant qu'elle attend votre signature, elle ne "
        "déclenche aucune alerte."
    )
    try:
        liste = donnees.contrats(DATASET)
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    if not liste:
        st.info("Aucune règle — l'agent n'a pas encore analysé vos tables.")
        return

    a_signer = [c for c in liste if c["status"] != "approved"]
    if a_signer:
        st.warning(f"{len(a_signer)} règle(s) attendent votre relecture.")

    choix = st.selectbox(
        "Table",
        range(len(liste)),
        format_func=lambda i: (
            f"{'⏳' if liste[i]['status'] != 'approved' else '✅'} "
            f"{liste[i]['table']} (version {liste[i]['version']})"
        ),
    )
    entree = liste[choix]
    try:
        contrat = donnees.contrat(entree["path"])
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    st.dataframe(donnees.colonnes_lisibles(contrat), width="stretch", hide_index=True)

    avertissements = contrat.get("warnings") or []
    if avertissements:
        st.warning(f"L'agent a lui-même signalé {len(avertissements)} réserve(s) :")
        for a in avertissements:
            st.markdown(f"- **{a['column']}** — {a['detail']}")
        st.caption(
            "Ces réserves sont la raison pour laquelle certaines colonnes n'ont "
            "pas de liste de valeurs autorisées : l'agent n'avait pas assez "
            "d'éléments pour l'affirmer, donc il n'a rien écrit."
        )

    if contrat.get("status") == "approved":
        st.success(f"Règle en vigueur, signée par {contrat.get('approved_by') or '?'}.")
        return

    _signer(entree["table"], avertissements)


def _signer(table: str, avertissements: list) -> None:
    st.divider()
    par = st.text_input("Votre nom", key="signataire", placeholder="obligatoire")

    # ⭐ Le garde-fou du CLI (`--accept-warnings`) survit **tel quel** dans
    # l'interface : signer une réserve est une décision, pas une formalité.
    # Sans lui, un clic distrait rendrait décorative toute la critique que la
    # découverte produit.
    lu = True
    if avertissements:
        lu = st.checkbox(
            f"J'ai lu les {len(avertissements)} réserve(s) ci-dessus et je les accepte",
            key="accepte",
        )

    if st.button("✅ Mettre cette règle en vigueur", disabled=not par or not lu):
        try:
            donnees.valider_contrat(DATASET, table, par, accepter=bool(avertissements))
        except Exception as exc:  # noqa: BLE001
            return _erreur(exc)
        st.success(f"Règle en vigueur — signée par {par}.")
        st.caption("Elle déclenchera désormais des alertes à chaque livraison.")


# ===========================================================================
# 📊 Données · 📚 Historique · 🔕 Alertes désactivées
# ===========================================================================


def tableaux() -> None:
    st.header("📊 Vos données")
    st.caption(
        "Les tableaux que consomme le métier. C'est ici qu'un chiffre faux se "
        "voit — et qu'il redevient juste après correction."
    )
    try:
        marts = donnees.tables_gold(DATASET)
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    table = st.selectbox("Tableau", marts)
    if not table:
        return
    try:
        resultat = donnees.agregat(DATASET, table)
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    st.dataframe(resultat["rows"], width="stretch", hide_index=True)
    if resultat.get("truncated"):
        st.caption("Affichage limité aux premières lignes.")


def historique() -> None:
    st.header("📚 Historique")
    st.caption(
        "Chaque contrôle laisse une trace — **y compris** ceux qui n'ont rien "
        "trouvé. Un historique plus propre que la réalité ne servirait à rien."
    )
    couche = st.selectbox(
        "Étape du pipeline",
        ["(toutes)", "bronze", "silver", "gold"],
        format_func=lambda c: {
            "(toutes)": "Toutes les étapes",
            "bronze": "Données brutes",
            "silver": "Données nettoyées",
            "gold": "Tableaux métier",
        }.get(c, c),
    )
    try:
        lignes = donnees.journal(
            DATASET, couche=None if couche.startswith("(") else couche
        )
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    if not lignes:
        st.info("Aucun contrôle enregistré pour le moment.")
        return

    st.dataframe(
        [
            {
                "Livraison": i.get("batch_id"),
                "Table": i.get("table_name"),
                "Anomalies": len(i.get("anomalies") or []),
                "Décision": donnees.DECISIONS_LISIBLES.get(
                    donnees.statut(i), donnees.statut(i)
                ),
                "Par": i.get("decided_by") or "—",
            }
            for i in lignes
        ],
        width="stretch",
        hide_index=True,
    )

    choix = st.selectbox(
        "Voir le détail",
        range(len(lignes)),
        format_func=lambda i: f"{lignes[i]['batch_id']} · {lignes[i]['table_name']}",
    )
    incident = lignes[choix]
    for anomalie in incident.get("anomalies") or []:
        st.markdown(f"- {donnees.anomalie_lisible(anomalie)}")
    diagnostic = incident.get("diagnosis") or {}
    if diagnostic.get("root_cause"):
        st.info(diagnostic["root_cause"])


def alertes_desactivees() -> None:
    st.header("🔕 Alertes désactivées")
    st.caption(
        "Quand vous écartez une anomalie, l'agent cesse de la signaler. Cet "
        "écran liste **tout ce qu'il ne dit plus** — sans lui, il deviendrait "
        "progressivement muet sans que personne s'en aperçoive."
    )
    try:
        lignes = donnees.silences(DATASET)
    except Exception as exc:  # noqa: BLE001
        return _erreur(exc)

    if not lignes:
        st.success("Aucune alerte désactivée : l'agent signale tout ce qu'il voit.")
        return

    st.dataframe(
        [
            {
                "Table": s["table"],
                "Colonne": s["colonne"],
                "Type d'anomalie": s["type"],
                "Écartée par": s["refuse_par"] or "—",
                "Le": s["refuse_le"],
            }
            for s in lignes
        ],
        width="stretch",
        hide_index=True,
    )
    st.info(
        "L'agent **reparlera de lui-même** si l'ampleur change franchement : "
        "écarter « 3 % de valeurs manquantes » ne le fait pas taire à 85 %."
    )


ECRANS = {
    "🏠 Accueil": accueil,
    "✅ Décisions": decisions,
    "📜 Règles": contrats,
    "📊 Vos données": tableaux,
    "📚 Historique": historique,
    "🔕 Alertes désactivées": alertes_desactivees,
}


def main() -> None:
    st.sidebar.title("🔎 Qualité des données")
    st.sidebar.caption(f"données `{DATASET}`")
    ECRANS[st.sidebar.radio("Écran", list(ECRANS), label_visibility="collapsed")]()
    st.sidebar.divider()
    st.sidebar.caption(
        "L'agent ne modifie **jamais** vos données sans votre accord explicite."
    )


if __name__ == "__main__":
    main()
