"""Test rapide : python test_api.py
Vérifie la clé, le modèle de texte (JSON) et le modèle d'embeddings."""
import pipeline as pr

print("Modèle texte      :", pr.LLM_MODEL)
print("Modèle embeddings :", pr.EMB_MODEL)
print("Adresse API       :", pr.BASE_URL)
print()

try:
    rep = pr.appel_json(
        "Réponds uniquement par un tableau JSON.",
        'Donne [{"id":"E1","texte":"exemple"}]',
    )
    print("✅ Modèle texte OK, JSON reçu :", rep)
except Exception as e:
    print("❌ Modèle texte : ÉCHEC ->", e)

print()
try:
    v = pr._embed(["attestation fiscale"], "query")
    print("✅ Embeddings OK, taille du vecteur :", v.shape[1])
except Exception as e:
    print("❌ Embeddings : ÉCHEC ->", e)
