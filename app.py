"""PRISMA - interface Streamlit. Lancer : streamlit run app.py"""
import os
from datetime import date

import pandas as pd
import streamlit as st

import pipeline as pr

st.set_page_config(page_title="PRISMA", page_icon="🔺", layout="wide")
st.title("🔺 PRISMA")
st.caption("Chaque exigence, une facette claire. Analysez un DAO, vérifiez votre dossier, sachez quoi corriger.")

if not os.getenv("NVIDIA_API_KEY"):
    st.error("Clé NVIDIA_API_KEY absente. Ajoutez-la dans les Secrets (Streamlit Cloud) ou dans le fichier .env.")
    st.stop()

ss = st.session_state
for k in ("exigences", "resultats", "plan"):
    ss.setdefault(k, None)

with st.sidebar:
    st.header("Options")
    ocr = st.checkbox("Lire les scans et photos (OCR par IA)", value=True)
    limite = st.date_input("Date limite de dépôt (optionnel)", value=None)
    st.caption(f"Texte : {pr.LLM_MODEL}\n\nVision : {pr.VISION_MODEL}")
    st.caption("Les documents sont envoyés à l'API NVIDIA pour analyse. Ne déposez pas de données confidentielles réelles pendant les tests.")
jours = (limite - date.today()).days if limite else None

TYPES = ["pdf", "png", "jpg", "jpeg"]


def lire_fichiers(fichiers, barre_txt):
    pages, avert = [], []
    barre = st.progress(0.0, text=barre_txt)
    for n, f in enumerate(fichiers):
        try:
            p = pr.lire_fichier(f.getvalue(), f.name, ocr=ocr)
        except Exception as e:
            avert.append(f"{f.name} : illisible ({e})")
            continue
        pages += p
        avert += [f"{f.name} p.{x['page']} : {x['erreur']}" for x in p if x["erreur"]]
        barre.progress((n + 1) / len(fichiers))
    barre.empty()
    return pages, avert


# ------------------------------------------------ Étape 1 : le DAO
st.header("1. Le dossier d'appel d'offres (DAO)")
dao = st.file_uploader("Déposez le DAO (PDF, scan ou photo)", type=TYPES, key="dao")

if dao and st.button("Extraire les exigences", type="primary"):
    pages, avert = lire_fichiers([dao], "Lecture du DAO...")
    for a in avert:
        st.warning(a)
    if sum(len(p["texte"]) for p in pages) < 200:
        st.error("Aucun texte lisible dans ce document.")
    else:
        n_ocr = sum(p["ocr"] for p in pages)
        if n_ocr:
            st.info(f"{n_ocr} page(s) lue(s) par OCR IA.")
        barre = st.progress(0.0, text="Analyse du DAO...")
        ss.exigences = pr.extraire_exigences(pages, progression=lambda x: barre.progress(x))
        ss.resultats, ss.plan = None, None
        barre.empty()

if ss.exigences:
    st.success(f"{len(ss.exigences)} exigences détectées. Vous pouvez corriger le tableau.")
    df = pd.DataFrame(ss.exigences).reindex(columns=["id", "texte", "type", "obligatoire", "page"])
    edite = st.data_editor(df, num_rows="dynamic", use_container_width=True, key="editeur")
    exi = [e for e in edite.to_dict("records") if isinstance(e.get("texte"), str) and e["texte"].strip()]
    for i, e in enumerate(exi, 1):
        if not isinstance(e.get("id"), str) or not e["id"]:
            e["id"] = f"E{i}"
    ss.exigences = exi

    # ------------------------------------------------ Étape 2 : les pièces
    st.header("2. Le dossier de l'entreprise")
    pieces = st.file_uploader("Déposez les pièces (PDF, scans ou photos, plusieurs possibles)",
                              type=TYPES, accept_multiple_files=True, key="pieces")

    if pieces and st.button("Vérifier la conformité", type="primary"):
        pages_pme, avert = lire_fichiers(pieces, "Lecture des pièces (les scans prennent plus de temps)...")
        for a in avert:
            st.warning(a)
        n_ocr = sum(p["ocr"] for p in pages_pme)
        if n_ocr:
            st.info(f"{n_ocr} page(s) lue(s) par OCR IA.")
        with st.spinner("Indexation des pièces..."):
            index = pr.Index(pages_pme)
        barre = st.progress(0.0, text="Vérification exigence par exigence...")
        res = []
        for i, ex in enumerate(ss.exigences):
            res.append({**ex, **pr.verifier(ex, index)})
            barre.progress((i + 1) / len(ss.exigences))
        barre.empty()
        ss.resultats, ss.plan = res, None

# ------------------------------------------------ Étape 3 : résultats
if ss.resultats:
    res = ss.resultats
    st.header("3. Résultats")

    # ---- Décision Go / No-go
    d = pr.decision(res)
    if d["niveau"] == "nogo":
        st.error(f"🚫 **{d['titre']}** : {d['message']}")
    elif d["niveau"] == "corriger":
        st.warning(f"🟠 **{d['titre']}** : {d['message']}")
    else:
        st.success(f"✅ **{d['titre']}** : {d['message']}")
    if jours is not None:
        st.caption(f"Il reste {jours} jour(s) avant la date limite de dépôt.")
    if d["bloquants"]:
        st.markdown("**Pièces bloquantes :** " + " · ".join(f"{r['id']}" for r in d["bloquants"]))

    n = lambda v: sum(r["verdict"] == v for r in res)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Score de conformité", f"{pr.score_global(res)} %")
    c2.metric("✅ Conformes", n("conforme"))
    c3.metric("🟠 Partielles", n("partiel"))
    c4.metric("🔴 Manquantes", n("manquant"))
    if d["engagements"]:
        st.caption(f"{len(d['engagements'])} engagement(s) à prendre dans l'offre (délais, garanties) : non comptés dans le score.")

    tab1, tab2, tab3 = st.tabs(["Verdicts et preuves", "Plan d'action", "Mesure de précision"])

    # ---- Onglet 1 : verdicts
    with tab1:
        filtre = st.multiselect("Filtrer", ["conforme", "partiel", "manquant"],
                                default=["conforme", "partiel", "manquant"])
        icone = {"conforme": "✅", "partiel": "🟠", "manquant": "🔴"}
        for r in res:
            if r["verdict"] not in filtre:
                continue
            eng = " · engagement" if r.get("type") == "engagement" else ""
            with st.expander(f"{icone.get(r['verdict'], '')} {r['id']} · {str(r['texte'])[:110]}{eng}"):
                st.write(f"**Verdict :** {r['verdict']}")
                st.write(f"**Justification :** {r.get('justification', '')}")
                if r.get("citation"):
                    src = f"{r['document']} p.{r['page']}" if r.get("document") else "source non retrouvée"
                    st.info(f"« {r['citation']} »  \n*{src}*")
                if r.get("action"):
                    st.warning(f"**À faire :** {r['action']}")
        export = pd.DataFrame(res).reindex(columns=["id", "texte", "type", "obligatoire", "verdict",
                                                    "justification", "citation", "document", "page", "action"])
        st.download_button("Télécharger le rapport (CSV)", export.to_csv(index=False).encode("utf-8-sig"),
                           "rapport_prisma.csv", "text/csv")

    # ---- Onglet 2 : plan d'action
    with tab2:
        st.write("PRISMA transforme chaque écart en action concrète, avec un brouillon quand c'est possible.")
        if st.button("Générer le plan d'action"):
            with st.spinner("Rédaction du plan d'action..."):
                try:
                    ss.plan = pr.plan_action(res, jours)
                except Exception as e:
                    st.error(f"Échec : {e}")
        if ss.plan:
            md = ["# Plan d'action PRISMA\n"]
            for i, a in enumerate(ss.plan):
                tag = {"bloquant": "🚫 BLOQUANT", "regulariser": "⚠️ À RÉGULARISER",
                       "engagement": "📝 ENGAGEMENT"}.get(a.get("categorie"), "⚠️")
                titre = f"{a.get('priorite', '?')}. {tag} · {a.get('id', '')} · {str(a.get('action', ''))[:90]}"
                with st.expander(titre, expanded=(i < 2)):
                    st.write(f"**Exigence :** {a.get('exigence', '')}")
                    st.write(f"**Où l'obtenir :** {a.get('ou_obtenir', '')}")
                    st.write(f"**Délai estimé (indicatif) :** {a.get('delai_estime', '')}")
                    if a.get("brouillon"):
                        st.text_area("Brouillon à adapter (complétez les [crochets])", a["brouillon"],
                                     height=200, key=f"brouillon_{i}")
                md.append(f"## {titre}\n- Exigence : {a.get('exigence', '')}\n- Où l'obtenir : {a.get('ou_obtenir', '')}\n"
                          f"- Délai estimé : {a.get('delai_estime', '')}\n\n{a.get('brouillon', '')}\n")
            st.download_button("Télécharger le plan (Markdown)", "\n".join(md).encode("utf-8"),
                               "plan_action_prisma.md", "text/markdown")
            st.caption("Les délais sont des estimations. Vérifiez auprès des organismes concernés.")

    # ---- Onglet 3 : précision
    with tab3:
        st.write("Indiquez le verdict que VOUS jugez correct pour chaque exigence. PRISMA calcule son exactitude.")
        base = pd.DataFrame({
            "id": [r["id"] for r in res],
            "exigence": [str(r["texte"])[:90] for r in res],
            "PRISMA": [r["verdict"] for r in res],
            "Verdict attendu": [None] * len(res),
        })
        annot = st.data_editor(
            base, hide_index=True, use_container_width=True, key="annotation",
            disabled=["id", "exigence", "PRISMA"],
            column_config={"Verdict attendu": st.column_config.SelectboxColumn(
                "Verdict attendu (votre avis)", options=["conforme", "partiel", "manquant"])},
        )
        rempli = annot.dropna(subset=["Verdict attendu"])
        if len(rempli):
            bons = int((rempli["Verdict attendu"] == rempli["PRISMA"]).sum())
            st.metric("Exactitude de PRISMA", f"{round(100 * bons / len(rempli))} %",
                      f"{bons} juste(s) sur {len(rempli)} évaluée(s)")
            st.download_button("Télécharger l'évaluation (CSV)", annot.to_csv(index=False).encode("utf-8-sig"),
                               "evaluation_prisma.csv", "text/csv")
        else:
            st.info("Remplissez au moins une ligne de la colonne « Verdict attendu ».")
