"""Tests locaux du pipeline, sans appel à l'API NVIDIA."""
import unittest

import numpy as np

import pipeline as pr


class PipelineTest(unittest.TestCase):
    def test_parse_json_ignore_reasoning_and_markdown(self):
        texte = "reponse interne </think>```json\n[{\"id\": \"E1\"}]\n```"

        self.assertEqual(pr._parse_json(texte), [{"id": "E1"}])

    def test_empty_embedding_has_stable_matrix_shape(self):
        vecteurs = pr._embed([], "query")

        self.assertEqual(vecteurs.shape, (0, 0))
        self.assertEqual(vecteurs.dtype, np.float32)

    def test_index_without_text_returns_no_results(self):
        index = pr.Index([{"doc": "vide.txt", "page": 1, "texte": ""}])

        self.assertEqual(index.recherche("attestation"), [])

    def test_invalid_verdict_is_safe(self):
        verdict = pr._normaliser_verdict({"verdict": "inconnu", "citation": 12})

        self.assertEqual(verdict["verdict"], "manquant")
        self.assertEqual(verdict["citation"], "")

    def test_citation_must_be_fully_present_in_source(self):
        class FakeIndex:
            def recherche(self, _query, k=6):
                return [{"doc": "piece.txt", "page": 1, "texte": "Attestation fiscale valable en 2026."}]

        original = pr.appel_json
        pr.appel_json = lambda *_args, **_kwargs: {
            "verdict": "conforme",
            "justification": "La piece est presente.",
            "citation": "Attestation fiscale valable en 2026 et signee par une personne absente",
            "action": "",
        }
        try:
            resultat = pr.verifier({"texte": "Fournir une attestation fiscale"}, FakeIndex())
        finally:
            pr.appel_json = original

        self.assertEqual(resultat["verdict"], "partiel")
        self.assertFalse(resultat["citation_verifiee"])

    def test_load_exported_report(self):
        rapport = pr.charger_rapport(b'{"exigences": [], "resultats": [], "decision": {}}')

        self.assertEqual(rapport["exigences"], [])
        self.assertEqual(rapport["resultats"], [])

    def test_reject_invalid_report(self):
        with self.assertRaises(ValueError):
            pr.charger_rapport(b'{"resultats": []}')

    def test_demo_report_is_complete_and_deterministic(self):
        rapport = pr.rapport_demo()

        self.assertEqual(len(rapport["exigences"]), 4)
        self.assertEqual(rapport["decision"]["niveau"], "nogo")
        self.assertEqual(pr.score_global(rapport["resultats"]), 50)

    def test_malformed_exigence_is_ignored(self):
        pages = [{"doc": "dao.txt", "page": 1,
                  "texte": "Une exigence très importante à fournir avec toutes les pièces justificatives."}]
        original = pr.appel_json
        pr.appel_json = lambda *_args, **_kwargs: [None, {"texte": "Pièce fiscale obligatoire"}]
        try:
            exigences = pr.extraire_exigences(pages, workers=1)
        finally:
            pr.appel_json = original

        self.assertEqual([item["texte"] for item in exigences], ["Pièce fiscale obligatoire"])

    def test_score_ignores_engagements_when_pieces_exist(self):
        resultats = [
            {"type": "administrative", "verdict": "conforme"},
            {"type": "technique", "verdict": "partiel"},
            {"type": "engagement", "verdict": "manquant"},
        ]

        self.assertEqual(pr.score_global(resultats), 75)

    def test_decision_prioritizes_missing_mandatory_piece(self):
        resultats = [
            {"id": "E1", "type": "administrative", "verdict": "partiel", "obligatoire": True},
            {"id": "E2", "type": "technique", "verdict": "manquant", "obligatoire": True},
            {"id": "E3", "type": "engagement", "verdict": "manquant", "obligatoire": True},
        ]

        decision = pr.decision(resultats)

        self.assertEqual(decision["niveau"], "nogo")
        self.assertEqual([item["id"] for item in decision["bloquants"]], ["E2"])
        self.assertEqual([item["id"] for item in decision["engagements"]], ["E3"])


if __name__ == "__main__":
    unittest.main()