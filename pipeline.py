"""PRISMA - pipeline : DAO -> exigences -> preuves -> verdicts cités."""
import json
import os
import re
import time
from datetime import date

import fitz  # PyMuPDF
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "meta/llama-3.1-70b-instruct")
EMB_MODEL = os.getenv("EMB_MODEL", "nvidia/nv-embedqa-e5-v5")


def _client():
    return OpenAI(base_url=BASE_URL, api_key=os.environ["NVIDIA_API_KEY"])


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
            return _parse_json(rep.choices[0].message.content)
        except Exception as e:  # JSON invalide, réseau, limite de débit...
            derniere_erreur = e
            time.sleep(1.5 * (t + 1))
    raise RuntimeError(f"Échec après {tentatives} tentatives : {derniere_erreur}")


# ---------------------------------------------------------------- Lecture PDF
def lire_pdf(contenu_bytes, nom="document.pdf"):
    """Retourne une liste de pages : {doc, page, texte}."""
    doc = fitz.open(stream=contenu_bytes, filetype="pdf")
    return [
        {"doc": nom, "page": i + 1, "texte": p.get_text().strip()}
        for i, p in enumerate(doc)
    ]


# ------------------------------------------------ Extraction des exigences
PROMPT_EXIGENCES = """Tu es expert des marchés publics (Côte d'Ivoire / UEMOA).
Lis les pages d'un dossier d'appel d'offres (DAO) et extrais TOUTES les exigences
que le soumissionnaire doit satisfaire ou fournir (pièces administratives,
références, capacités techniques, moyens, garanties, exigences financières).
Ignore le contexte, les définitions, les procédures internes à l'administration et les modalités de dépôt de l'offre (date limite, lieu, nombre de copies).
Réponds UNIQUEMENT par un tableau JSON, sans texte autour :
[{"texte":"exigence reformulée clairement","type":"administrative|technique|financiere","obligatoire":true,"page":N}]
Si aucune exigence dans ces pages, réponds []."""


def extraire_exigences(pages, taille_bloc=4, progression=None):
    blocs = [pages[i:i + taille_bloc] for i in range(0, len(pages), taille_bloc)]
    trouvees, vues = [], set()
    for n, bloc in enumerate(blocs):
        texte = "\n\n".join(f"[Page {p['page']}]\n{p['texte']}" for p in bloc)
        if len(texte.strip()) < 50:
            continue
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
- Ne réponds "manquant" que si aucun extrait ne se rapporte à l'exigence.
- "conforme" : un extrait prouve clairement l'exigence.
- "partiel" : preuve incomplète, périmée ou ambiguë.
- "manquant" : aucun extrait ne couvre l'exigence.
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
    rep = appel_json(PROMPT_VERDICT, f"DATE DU JOUR : {date.today():%d/%m/%Y}\n\nEXIGENCE : {exigence['texte']}\n\nEXTRAITS :\n{bloc}")
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
    if not resultats:
        return 0
    pts = {"conforme": 1.0, "partiel": 0.5, "manquant": 0.0}
    return round(100 * sum(pts.get(r["verdict"], 0) for r in resultats) / len(resultats))
