"""PRISMA - interface Streamlit. Lancer : streamlit run app.py"""
import os

import pandas as pd
import streamlit as st

import pipeline as pr

st.set_page_config(page_title="PRISMA", page_icon="🔺", layout="wide")
st.title("🔺 PRISMA")
st.caption("Chaque exigence, une facette claire. Analysez un DAO et vérifiez votre dossier.")

if not os.getenv("NVIDIA_API_KEY"):
    st.error("Clé NVIDIA_API_KEY absente. Créez le fichier .env (voir .env.example).")
    st.stop()

ss = st.session_state
ss.setdefault("exigences", None)
ss.setdefault("resultats", None)

# ------------------------------------------------ Étape 1 : le DAO
st.header("1. Le dossier d'appel d'offres (DAO)")
dao = st.file_uploader("Déposez le DAO (PDF)", type="pdf", key="dao")

if dao and st.button("Extraire les exigences", type="primary"):
    pages = pr.lire_pdf(dao.getvalue(), dao.name)
    if sum(len(p["texte"]) for p in pages) < 200:
        st.warning("Ce PDF semble être un scan (peu de texte). Utilisez un PDF texte pour la démo.")
    else:
        barre = st.progress(0.0, text="Analyse du DAO...")
        ss.exigences = pr.extraire_exigences(pages, progression=lambda x: barre.progress(x))
        ss.resultats = None
        barre.empty()

if ss.exigences:
    st.success(f"{len(ss.exigences)} exigences détectées. Vous pouvez corriger le tableau.")
    df = pd.DataFrame(ss.exigences)[["id", "texte", "type", "obligatoire", "page"]]
    edite = st.data_editor(df, num_rows="dynamic", use_container_width=True, key="editeur")
    ss.exigences = edite.to_dict("records")

    # ------------------------------------------------ Étape 2 : les pièces
    st.header("2. Le dossier de l'entreprise")
    pieces = st.file_uploader("Déposez les pièces (PDF, plusieurs possibles)",
                              type="pdf", accept_multiple_files=True, key="pieces")

    if pieces and st.button("Vérifier la conformité", type="primary"):
        pages_pme = []
        for f in pieces:
            pages_pme += pr.lire_pdf(f.getvalue(), f.name)
        with st.spinner("Indexation des pièces..."):
            index = pr.Index(pages_pme)
        barre = st.progress(0.0, text="Vérification exigence par exigence...")
        res = []
        for i, ex in enumerate(ss.exigences):
            v = pr.verifier(ex, index)
            res.append({**ex, **v})
            barre.progress((i + 1) / len(ss.exigences))
        barre.empty()
        ss.resultats = res

# ------------------------------------------------ Étape 3 : résultats
if ss.resultats:
    st.header("3. Résultats")
    res = ss.resultats
    n = lambda v: sum(r["verdict"] == v for r in res)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Score de conformité", f"{pr.score_global(res)} %")
    c2.metric("✅ Conformes", n("conforme"))
    c3.metric("🟠 Partielles", n("partiel"))
    c4.metric("🔴 Manquantes", n("manquant"))

    filtre = st.multiselect("Filtrer", ["conforme", "partiel", "manquant"],
                            default=["conforme", "partiel", "manquant"])
    icone = {"conforme": "✅", "partiel": "🟠", "manquant": "🔴"}
    for r in res:
        if r["verdict"] not in filtre:
            continue
        with st.expander(f"{icone.get(r['verdict'], '')} {r['id']} · {r['texte'][:110]}"):
            st.write(f"**Verdict :** {r['verdict']}")
            st.write(f"**Justification :** {r.get('justification', '')}")
            if r.get("citation"):
                src = f"{r['document']} p.{r['page']}" if r.get("document") else "source non retrouvée"
                st.info(f"« {r['citation']} »  \n*{src}*")
            if r.get("action"):
                st.warning(f"**À faire :** {r['action']}")

    export = pd.DataFrame(res)[["id", "texte", "type", "obligatoire", "verdict",
                                "justification", "citation", "document", "page", "action"]]
    st.download_button("Télécharger le rapport (CSV)", export.to_csv(index=False).encode("utf-8-sig"),
                       "rapport_prisma.csv", "text/csv")
