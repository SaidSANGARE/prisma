"""PRISMA - pipeline : DAO -> exigences -> preuves -> verdicts cités -> décision -> plan d'action.
Lit aussi les scans et photos grâce à un modèle de vision (OCR par IA)."""
import base64
import json
import os
import re
import time
from datetime import date

try:
    import pymupdf as fitz  # PyMuPDF (nom récent)
except ImportError:
    import fitz  # ancien nom
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b")
EMB_MODEL = os.getenv("EMB_MODEL", "nvidia/nemotron-3-embed-1b")
# Modèle de vision pour lire les scans/photos (à vérifier dans le catalogue build.nvidia.com)
VISION_MODEL = os.getenv("VISION_MODEL", "meta/llama-3.2-90b-vision-instruct")
# Modèles de secours, essayés dans l'ordre si le premier échoue ou tarde (séparés par des virgules)
VISION_FALLBACKS = [m.strip() for m in os.getenv("VISION_FALLBACKS", "meta/llama-3.2-11b-vision-instruct").split(",") if m.strip()]


def _client(timeout=120.0, retries=2):
    return OpenAI(base_url=BASE_URL, api_key=os.environ["NVIDIA_API_KEY"],
                  timeout=timeout, max_retries=retries)


def _oblig(r):
    v = r.get("obligatoire", True)
    return True if v is None or v != v else bool(v)  # v != v : valeur NaN


# ---------------------------------------------------------------- LLM + JSON
def _parse_json(texte):
    if "</think>" in texte:  # modèles "reasoning" : on ignore la réflexion
        texte = texte.split("</think>")[-1]
    texte = re.sub(r"```(?:json)?", "", texte).strip()
    debut = min([i for i in (texte.find("["), texte.find("{")) if i != -1], default=-1)
    if debut == -1:
        raise ValueError("Pas de JSON dans la réponse")
    obj, _ = json.JSONDecoder().raw_decode(texte[debut:])
    return obj


def appel_json(system, user, tentatives=3):
    """Appelle le LLM et exige un JSON valide (nouvelle tentative sinon)."""
    derniere_erreur = None
    for t in range(tentatives):
        try:
            rep = _client().chat.completions.create(
                model=LLM_MODEL,
                temperature=0.0,
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return _parse_json(rep.choices[0].message.content or "")
        except Exception as e:  # JSON invalide, réseau, limite de débit...
            derniere_erreur = e
            time.sleep(1.5 * (t + 1))
    raise RuntimeError(f"Échec après {tentatives} tentatives : {derniere_erreur}")


# ------------------------------------------- Lecture : PDF texte, scans, photos
PROMPT_OCR = ("Transcris fidèlement TOUT le texte visible sur ce document (tampons, dates, montants, noms, "
              "numéros). Ne résume pas, n'ajoute rien. Si un passage est illisible, écris [illisible]. "
              "Réponds uniquement par la transcription.")


def _render_jpeg(page, max_dim, qualite):
    r = page.rect
    zoom = min(max_dim / max(r.width, r.height), 3.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("jpeg", jpg_quality=qualite)


def ocr_page(page, delai_max=150):
    """Lit une page (scan ou photo) avec un modèle de vision.
    Essaie plusieurs modèles et deux formats d'envoi, avec un délai de 60 s par essai
    et un délai total de `delai_max` secondes par page."""
    debut = time.monotonic()
    erreurs = []
    variantes = ((1400, 70, "openai"), (900, 55, "img"))
    for modele in [VISION_MODEL] + [m for m in VISION_FALLBACKS if m != VISION_MODEL]:
        for max_dim, qualite, style in variantes:
            if time.monotonic() - debut > delai_max:
                raise RuntimeError("Délai dépassé. " + " | ".join(erreurs[-3:]))
            b64 = base64.b64encode(_render_jpeg(page, max_dim, qualite)).decode()
            url = f"data:image/jpeg;base64,{b64}"
            if style == "openai":
                contenu = [{"type": "text", "text": PROMPT_OCR}, {"type": "image_url", "image_url": {"url": url}}]
            else:
                contenu = f'{PROMPT_OCR}\n<img src="{url}" />'
            try:
                rep = _client(timeout=60.0, retries=0).chat.completions.create(
                    model=modele, temperature=0.0, max_tokens=4096,
                    messages=[{"role": "user", "content": contenu}],
                )
                txt = rep.choices[0].message.content or ""
                if "</think>" in txt:
                    txt = txt.split("</think>")[-1]
                if txt.strip():
                    return txt.strip()
                erreurs.append(f"{modele} : réponse vide")
            except Exception as e:
                erreurs.append(f"{modele} : {str(e)[:120]}")
    raise RuntimeError("Lecture d'image impossible : " + " | ".join(erreurs[-4:]))


def lire_fichier(contenu, nom, ocr=True, progression=None):
    """PDF texte, PDF scanné, ou image (png/jpg). Retourne [{doc, page, texte, ocr, erreur}]."""
    ext = nom.lower().rsplit(".", 1)[-1]
    doc = fitz.open(stream=contenu, filetype="pdf" if ext == "pdf" else ext)
    pages = []
    for i, p in enumerate(doc):
        texte = p.get_text().strip() if ext == "pdf" else ""
        via_ocr, erreur = False, ""
        if len(texte) < 40 and ocr:  # page sans texte : scan ou photo
            try:
                texte, via_ocr = ocr_page(p), True
            except Exception as e:
                erreur = str(e)[:200]
        pages.append({"doc": nom, "page": i + 1, "texte": texte, "ocr": via_ocr, "erreur": erreur})
        if progression:
            progression((i + 1) / doc.page_count)
    return pages


# ------------------------------------------------ Extraction des exigences
PROMPT_EXIGENCES = """Tu es expert des marchés publics (Côte d'Ivoire / UEMOA).
Lis les pages d'un dossier d'appel d'offres (DAO) et extrais TOUTES les exigences
que le soumissionnaire doit satisfaire ou fournir (pièces administratives,
références, capacités techniques, moyens, garanties, exigences financières).
Ignore le contexte, les définitions, les procédures internes à l'administration et les modalités de dépôt de l'offre (date limite, lieu, nombre de copies).
Réponds UNIQUEMENT par un tableau JSON, sans texte autour :
[{"texte":"exigence reformulée clairement","type":"administrative|technique|financiere|engagement","obligatoire":true,"page":N}]
Le type "engagement" désigne ce que le soumissionnaire promet DANS son offre (délai de livraison,
durée de garantie, prix ferme...) et qui ne se prouve pas par une pièce d'archive.
Si aucune exigence dans ces pages, réponds []."""


def extraire_exigences(pages, taille_bloc=4, progression=None):
    blocs = [pages[i:i + taille_bloc] for i in range(0, len(pages), taille_bloc)]
    trouvees, vues = [], set()
    for n, bloc in enumerate(blocs):
        texte = "\n\n".join(f"[Page {p['page']}]\n{p['texte']}" for p in bloc)
        if len(texte.strip()) >= 50:
            for ex in appel_json(PROMPT_EXIGENCES, texte[:14000]):
                cle = re.sub(r"\W+", " ", ex.get("texte", "").lower())[:80]
                if cle and cle not in vues:
                    vues.add(cle)
                    trouvees.append(ex)
        if progression:
            progression((n + 1) / len(blocs))
    for i, ex in enumerate(trouvees, 1):
        ex["id"] = f"E{i}"
    return trouvees


# ------------------------------------------------------- Indexation des preuves
def _decouper(pages, taille=900, chevauchement=150):
    chunks = []
    for p in pages:
        t = p["texte"]
        pas = taille - chevauchement
        for i in range(0, max(len(t), 1), pas):
            morceau = t[i:i + taille].strip()
            if len(morceau) > 30:
                chunks.append({"doc": p["doc"], "page": p["page"], "texte": morceau})
    return chunks


def _embed(textes, type_entree):
    vecs = []
    for i in range(0, len(textes), 32):
        lot = textes[i:i + 32]
        try:
            r = _client().embeddings.create(
                model=EMB_MODEL, input=lot,
                extra_body={"input_type": type_entree, "truncate": "END"},
            )
        except Exception:  # certains modèles n'acceptent pas input_type
            r = _client().embeddings.create(model=EMB_MODEL, input=lot)
        vecs += [d.embedding for d in r.data]
    m = np.array(vecs, dtype="float32")
    return m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)


class Index:
    def __init__(self, pages):
        self.chunks = _decouper(pages)
        self.vecs = _embed([c["texte"] for c in self.chunks], "passage") if self.chunks else None

    def recherche(self, requete, k=4):
        if self.vecs is None:
            return []
        q = _embed([requete], "query")[0]
        scores = self.vecs @ q
        return [self.chunks[i] for i in np.argsort(-scores)[:k]]


# ------------------------------------------------------------- Vérification
PROMPT_VERDICT = """Tu vérifies si une entreprise satisfait une exigence d'appel d'offres.
Tu ne t'appuies QUE sur les extraits fournis. N'invente rien.
RÈGLES IMPORTANTES :
- Vérifie les dates par rapport à la DATE DU JOUR indiquée. Une pièce dont la validité est expirée, ou plus ancienne que la limite demandée, n'est PAS "conforme" : réponds "partiel" si la pièce existe mais est périmée.
- Si l'exigence demande un nombre précis (références, bilans, années, personnes) et que les extraits en montrent moins, réponds "partiel" et précise combien manquent.
- "partiel" est réservé au cas où un extrait concerne réellement l'exigence sans la satisfaire entièrement. Si l'exigence n'est simplement pas mentionnée dans les extraits, réponds "manquant" et laisse la citation vide.
- La citation doit prouver ou illustrer l'exigence elle-même. N'utilise jamais une phrase sans rapport avec elle.
- Les extraits peuvent venir d'un scan lu par OCR : tolère de petites fautes de lecture.
Réponds UNIQUEMENT en JSON :
{"verdict":"conforme|partiel|manquant","justification":"1-2 phrases","citation":"phrase EXACTE copiée de l'extrait (vide si manquant)","action":"ce que l'entreprise doit faire si non conforme (sinon vide)"}"""


def _norm(s):
    return re.sub(r"\s+", " ", s.lower()).strip()


def verifier(exigence, index):
    preuves = index.recherche(exigence["texte"], k=6)
    if not preuves:
        return {"verdict": "manquant", "justification": "Aucune pièce fournie.",
                "citation": "", "action": "Fournir les pièces justificatives.",
                "document": "", "page": None, "citation_verifiee": True}
    bloc = "\n\n".join(f"[{p['doc']} - page {p['page']}]\n{p['texte']}" for p in preuves)
    rep = appel_json(PROMPT_VERDICT,
                     f"DATE DU JOUR : {date.today():%d/%m/%Y}\n\nEXIGENCE : {exigence['texte']}\n\nEXTRAITS :\n{bloc}")
    if not isinstance(rep, dict):
        rep = {"verdict": "manquant", "justification": "Réponse invalide.", "citation": "", "action": ""}
    citation = rep.get("citation", "")
    # Anti-hallucination : la citation doit réellement exister dans les extraits
    verifiee, source = True, None
    if citation:
        for p in preuves:
            if _norm(citation)[:60] in _norm(p["texte"]):
                source = p
                break
        verifiee = source is not None
        if not verifiee and rep.get("verdict") == "conforme":
            rep["verdict"] = "partiel"
            rep["justification"] += " (citation non retrouvée dans les pièces : à vérifier)"
    rep["document"] = source["doc"] if source else ""
    rep["page"] = source["page"] if source else None
    rep["citation_verifiee"] = verifiee
    return rep


def score_global(resultats):
    base = [r for r in resultats if r.get("type") != "engagement"] or resultats
    if not base:
        return 0
    pts = {"conforme": 1.0, "partiel": 0.5, "manquant": 0.0}
    return round(100 * sum(pts.get(r["verdict"], 0) for r in base) / len(base))


# ------------------------------------------------------- Décision Go / No-go
def decision(resultats):
    """Règle déterministe (pas d'IA) : facile à expliquer et à défendre devant un jury."""
    pieces = [r for r in resultats if r.get("type") != "engagement"]
    bloquants = [r for r in pieces if r["verdict"] == "manquant" and _oblig(r)]
    a_corriger = [r for r in pieces if r["verdict"] == "partiel" and _oblig(r)]
    engagements = [r for r in resultats if r.get("type") == "engagement"]
    if bloquants:
        niveau, titre = "nogo", "NO-GO en l'état"
        msg = (f"{len(bloquants)} pièce(s) obligatoire(s) absente(s) : l'offre serait rejetée. "
               "Obtenez-les avant de déposer.")
    elif a_corriger:
        niveau, titre = "corriger", "À CORRIGER avant dépôt"
        msg = f"{len(a_corriger)} pièce(s) incomplète(s) ou périmée(s) à régulariser."
    else:
        niveau, titre = "go", "GO"
        msg = "Toutes les pièces obligatoires paraissent conformes. Relisez les citations avant de déposer."
    return {"niveau": niveau, "titre": titre, "message": msg,
            "bloquants": bloquants, "a_corriger": a_corriger, "engagements": engagements}


# ---------------------------------------------------------- Plan d'action
PROMPT_PLAN = """Tu es conseiller en marchés publics (Côte d'Ivoire / UEMOA) et tu aides une PME à finaliser son dossier.
Pour chaque exigence non conforme, propose une action concrète. Réponds UNIQUEMENT par un tableau JSON :
[{"id":"E4","priorite":1,"bloquant":true,"action":"action concrète en une phrase","ou_obtenir":"organisme ou service à contacter","delai_estime":"ex : 2 à 5 jours ouvrés (estimation)","brouillon":"texte prêt à adapter si l'élément se rédige (déclaration sur l'honneur, lettre de demande...), sinon chaîne vide"}]
- priorite 1 = le plus urgent. bloquant = true si l'absence entraîne le rejet de l'offre.
- Les délais sont des estimations indicatives : n'invente ni tarifs, ni numéros d'articles de loi.
- Dans les brouillons, mets des crochets pour les informations à compléter : [NOM], [DATE], [MONTANT].
- Tiens compte de "jours_restants_avant_depot" s'il est renseigné."""


def plan_action(resultats, jours_restants=None):
    a_traiter = [r for r in resultats if r["verdict"] != "conforme"]
    plan = []
    for i in range(0, len(a_traiter), 5):  # lots de 5 pour éviter les réponses tronquées
        entree = {
            "jours_restants_avant_depot": jours_restants,
            "exigences": [{
                "id": r["id"], "exigence": r["texte"], "obligatoire": _oblig(r),
                "type": str(r.get("type", "")), "verdict": r["verdict"],
                "constat": r.get("justification", ""), "action_suggeree": r.get("action", ""),
            } for r in a_traiter[i:i + 5]],
        }
        rep = appel_json(PROMPT_PLAN, json.dumps(entree, ensure_ascii=False))
        plan += [rep] if isinstance(rep, dict) else rep
    infos = {r["id"]: r for r in a_traiter}
    rang = {"bloquant": 0, "regulariser": 1, "engagement": 2}
    for a in plan:
        r = infos.get(a.get("id"), {})
        a["exigence"] = r.get("texte", "")
        if r.get("type") == "engagement":
            a["categorie"] = "engagement"
        elif r.get("verdict") == "manquant" and _oblig(r):
            a["categorie"] = "bloquant"
        else:
            a["categorie"] = "regulariser"
        a["bloquant"] = a["categorie"] == "bloquant"
    plan.sort(key=lambda a: (rang[a["categorie"]],
                             a["priorite"] if isinstance(a.get("priorite"), int) else 99))
    for i, a in enumerate(plan, 1):
        a["priorite"] = i
    return plan
