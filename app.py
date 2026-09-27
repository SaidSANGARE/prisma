"""PRISMA - interface Streamlit. Lancer : streamlit run app.py"""
import json
import os
import time
from datetime import date

import pandas as pd
import streamlit as st

import db
import pipeline as pr
import report as pdf_report
import storage

db.init_db()

st.set_page_config(page_title="PRISMA", page_icon="🔺", layout="wide")
st.title("🔺 PRISMA")
st.caption("Chaque exigence, une facette claire. Analysez un DAO, vérifiez votre dossier, sachez quoi corriger.")

ss = st.session_state
for k in ("exigences", "resultats", "plan", "checklist", "report_id", "user"):
    ss.setdefault(k, None)
DEMO_MODE = os.getenv("PRISMA_DEMO_MODE", "").lower() in {"1", "true", "oui"}

if not ss.user:
    st.header("Accès à PRISMA")
    login_tab, register_tab = st.tabs(["Se connecter", "Créer un compte"])
    with login_tab:
        with st.form("login_form"):
            login_email = st.text_input("E-mail")
            login_password = st.text_input("Mot de passe", type="password")
            login_submit = st.form_submit_button("Se connecter", type="primary")
        if login_submit:
            user = db.authenticate(login_email, login_password)
            if user:
                ss.user = user
                st.rerun()
            st.error("E-mail ou mot de passe incorrect.")
    with register_tab:
        with st.form("register_form"):
            register_email = st.text_input("E-mail", key="register_email")
            register_password = st.text_input("Mot de passe (10 caractères minimum)", type="password")
            register_confirmation = st.text_input("Confirmer le mot de passe", type="password")
            register_submit = st.form_submit_button("Créer le compte")
        if register_submit:
            if register_password != register_confirmation:
                st.error("Les mots de passe ne correspondent pas.")
            else:
                try:
                    ss.user = db.create_user(register_email, register_password)
                    st.success("Compte créé. Connexion en cours...")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    st.stop()

with st.expander("🧭 0. Je n'ai pas encore de DAO : que dois-je préparer selon mon secteur ?", expanded=False):
    st.write("Avant même de recevoir un appel d'offres précis, préparez à l'avance les pièces "
             "les plus souvent demandées dans votre secteur.")
    SECTEURS = ["Informatique / Numérique", "BTP / Construction", "Fourniture de biens / équipements",
                "Services / Conseil", "Transport / Logistique", "Agroalimentaire", "Santé / Pharmaceutique",
                "Éducation / Formation", "Autre (préciser ci-dessous)"]
    col1, col2 = st.columns([1, 1])
    secteur = col1.selectbox("Secteur d'activité", SECTEURS)
    precisions = col2.text_input("Précisions (optionnel)", placeholder="ex : formation professionnelle en informatique")
    if st.button("Générer ma checklist de préparation"):
        with st.spinner("Préparation de votre checklist..."):
            try:
                ss["checklist"] = pr.checklist_secteur(secteur, precisions)
            except Exception as e:
                st.error(f"Échec : {e}")
    if ss.get("checklist"):
        lignes_md = [f"# Checklist de préparation — {secteur}\n"]
        for cat in ss["checklist"].get("categories", []):
            st.subheader(cat.get("nom", ""))
            lignes_md.append(f"## {cat.get('nom', '')}\n")
            for el in cat.get("elements", []):
                st.markdown(f"- **{el.get('document', '')}** — {el.get('pourquoi', '')}"
                           + (f" *(à obtenir : {el.get('ou_obtenir')})*" if el.get("ou_obtenir") else ""))
                lignes_md.append(f"- **{el.get('document', '')}** — {el.get('pourquoi', '')}"
                                 + (f" (à obtenir : {el.get('ou_obtenir')})" if el.get("ou_obtenir") else ""))
        st.caption("Liste indicative et générale : le DAO réel, une fois reçu, prévaut toujours sur cette checklist.")
        st.download_button("Télécharger la checklist (Markdown)", "\n".join(lignes_md).encode("utf-8"),
                           f"checklist_{secteur.split(' ')[0].lower()}.md", "text/markdown")

if not os.getenv("NVIDIA_API_KEY") and not DEMO_MODE:
    st.error("Clé NVIDIA_API_KEY absente. Ajoutez-la dans les Secrets (Streamlit Cloud) ou dans le fichier .env.")
    st.stop()

TYPES = ["pdf", "png", "jpg", "jpeg", "docx", "txt"]

with st.sidebar:
    st.header("Options")
    st.caption(f"Connecté : {ss.user['email']}")
    if st.button("Se déconnecter"):
        ss.clear()
        st.rerun()
    if not storage.is_configured():
        st.warning("Stockage chiffré inactif : configurez PRISMA_STORAGE_KEY.")
    with st.expander("Mes rapports"):
        rapports = db.list_reports(ss.user["id"])
        if rapports:
            choix = st.selectbox("Rapport à charger", rapports, format_func=lambda r: r["name"])
            if st.button("Charger ce rapport"):
                charge = db.load_report(ss.user["id"], choix["id"])
                ss.exigences = charge["exigences"]
                ss.resultats = charge["resultats"]
                ss.plan = charge.get("plan")
                ss.report_id = choix["id"]
                st.rerun()
        else:
            st.caption("Aucun rapport sauvegardé.")
    if DEMO_MODE:
        st.warning("Mode démonstration local : aucun appel NVIDIA ne sera effectué.")
        if st.button("Charger les données de démonstration"):
            rapport_demo = pr.rapport_demo()
            ss.exigences = rapport_demo["exigences"]
            ss.resultats = rapport_demo["resultats"]
            ss.plan = None
            ss.report_id = str(__import__("uuid").uuid4())
    api_active = not DEMO_MODE
    ocr = st.checkbox("Lire les scans et photos (OCR par IA)", value=True)
    limite = st.date_input("Date limite de dépôt (optionnel)", value=None)
    st.caption(f"Texte : {pr.LLM_MODEL}\n\nVision : {pr.VISION_MODEL}")
    st.caption("Les documents sont envoyés à l'API NVIDIA pour analyse. Ne déposez pas de données confidentielles réelles pendant les tests.")
    with st.expander("🔧 Diagnostic OCR"):
        st.caption("Testez la lecture d'UN scan ou d'UNE photo, sans lancer toute l'analyse.")
        test = st.file_uploader("Image ou PDF scanné", type=TYPES, key="diag")
        if test and st.button("Tester la lecture", disabled=DEMO_MODE):
            t0 = time.time()
            progression_ocr = st.progress(0.0, text="Lecture de la page...")
            with st.spinner("Lecture en cours (2 à 3 minutes au maximum)..."):
                pages_test = pr.lire_fichier(test.getvalue(), test.name, ocr=True,
                                             progression=lambda x: progression_ocr.progress(x))
            progression_ocr.empty()
            st.write(f"Durée : {time.time() - t0:.0f} s")
            for pg in pages_test:
                st.write(f"Page {pg['page']} : {'lue par OCR' if pg['ocr'] else 'texte natif'}")
                if pg["erreur"]:
                    st.error(pg["erreur"])
                st.text(pg["texte"][:1500])
jours = (limite - date.today()).days if limite else None

with st.expander("Reprendre une analyse exportée", expanded=False):
    rapport_charge = st.file_uploader("Fichier JSON PRISMA", type=["json"], key="rapport_charge")
    if rapport_charge and st.button("Charger le rapport"):
        try:
            rapport = pr.charger_rapport(rapport_charge.getvalue())
            ss.exigences = rapport["exigences"]
            ss.resultats = rapport["resultats"]
            ss.plan = None
            st.success("Analyse chargée. Les résultats sont disponibles ci-dessous.")
        except ValueError as e:
            st.error(str(e))



def lire_fichiers(fichiers, barre_txt):
    items = [(f.getvalue(), f.name) for f in fichiers]
    barre = st.progress(0.0, text=barre_txt)
    pages = pr.lire_fichiers(items, ocr=ocr, progression=lambda x: barre.progress(x))
    barre.empty()
    avert = [f"{p['doc']} p.{p['page']} : {p['erreur']}" for p in pages if p["erreur"]]
    return pages, avert


# ------------------------------------------------ Étape 1 : le DAO
st.header("1. Le dossier d'appel d'offres (DAO)")
dao = st.file_uploader("Déposez le DAO (PDF, scan ou photo)", type=TYPES, key="dao")

if dao and st.button("Extraire les exigences", type="primary", disabled=DEMO_MODE):
    ss.report_id = str(__import__("uuid").uuid4())
    pages, avert = lire_fichiers([dao], "Lecture du DAO...")
    for a in avert:
        st.warning(a)
    if sum(len(p["texte"]) for p in pages) < 200:
        st.error("Aucun texte lisible dans ce document.")
    else:
        if storage.is_configured():
            storage.save_document(ss.user["id"], ss.report_id, dao.name, dao.getvalue())
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

    if pieces and st.button("Vérifier la conformité", type="primary", disabled=DEMO_MODE):
        if storage.is_configured():
            for piece in pieces:
                storage.save_document(ss.user["id"], ss.report_id, piece.name, piece.getvalue())
        pages_pme, avert = lire_fichiers(pieces, "Lecture des pièces (les scans prennent plus de temps)...")
        for a in avert:
            st.warning(a)
        n_ocr = sum(p["ocr"] for p in pages_pme)
        if n_ocr:
            st.info(f"{n_ocr} page(s) lue(s) par OCR IA.")
        with st.spinner("Indexation des pièces..."):
            index = pr.Index(pages_pme)
        barre = st.progress(0.0, text="Vérification des exigences (en parallèle)...")
        res = pr.verifier_toutes(ss.exigences, index, progression=lambda x: barre.progress(x))
        barre.empty()
        ss.resultats, ss.plan = res, None

# ------------------------------------------------ Étape 3 : résultats
if ss.resultats:
    res = ss.resultats
    st.header("3. Résultats")

    # ---- Décision Go / No-go
    d = pr.decision(res)
    payload = {"exigences": ss.exigences, "resultats": res, "decision": d, "plan": ss.plan}
    if ss.report_id:
        db.save_report(ss.user["id"], ss.report_id, "Analyse PRISMA", payload)
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
        rapport_json = json.dumps({"exigences": ss.exigences, "resultats": res,
                       "decision": d}, ensure_ascii=False, indent=2, default=str)
        st.download_button("Télécharger l'analyse complète (JSON)", rapport_json.encode("utf-8"),
                   "rapport_prisma.json", "application/json")
        st.download_button("Télécharger le rapport PDF", pdf_report.build_pdf(res, d, pr.score_global(res)),
                   "rapport_prisma.pdf", "application/pdf")

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
